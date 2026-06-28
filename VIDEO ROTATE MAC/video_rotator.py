#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List

# Suppress console window when calling subprocesses from a windowed .exe on Windows
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
    ".mts",
    ".m2ts",
}


ROTATE_MAP = {
    "right": "transpose=1",
    "left": "transpose=2",
    "180": "transpose=1,transpose=1",
    "resize": None,
}


COLOR_ENHANCE_FILTER = "eq=contrast=0.94:brightness=0.03:saturation=1.18:gamma=1.04"


@dataclass
class JobResult:
    source: Path
    output: Path
    ok: bool
    elapsed: float
    error: str | None = None


LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rotate all video files in a folder with high-throughput parallel processing."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Input folder containing videos.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output folder (default: <input>/rotated_<direction>).",
    )
    parser.add_argument(
        "--direction",
        choices=["right", "left", "180", "resize"],
        help="Rotation direction: right, left, 180, or resize.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 4) // 2),
        help="Number of parallel workers (default: half of CPU cores).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan input folder recursively.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files.",
    )
    parser.add_argument(
        "--codec",
        default="libx264",
        help="Video codec for ffmpeg (default: libx264).",
    )
    parser.add_argument(
        "--preset",
        default="veryfast",
        help="Encoding preset (default: veryfast).",
    )
    parser.add_argument(
        "--crf",
        default="23",
        help="CRF quality value for encoders that support it (default: 23).",
    )
    parser.add_argument(
        "--ffmpeg",
        type=Path,
        help="Custom path to ffmpeg executable (optional).",
    )
    parser.add_argument(
        "--enhance-color",
        action="store_true",
        help="Apply a mild color-enhancement filter to exported videos.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch desktop UI.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Force terminal input mode.",
    )
    return parser.parse_args()


def prompt_for_missing(args: argparse.Namespace) -> argparse.Namespace:
    if args.input is None:
        user_input = input("Input folder path: ").strip().strip('"')
        args.input = Path(user_input)

    if args.direction is None:
        print("Choose direction:")
        print("1) right (90° clockwise)")
        print("2) left  (90° counter-clockwise)")
        print("3) 180")
        print("4) resize (ไม่หมุน / ย่อไฟล์)")
        mapping = {"1": "right", "2": "left", "3": "180", "4": "resize"}
        while True:
            choice = input("Direction [1/2/3/4]: ").strip()
            if choice in mapping:
                args.direction = mapping[choice]
                break
            print("Invalid choice. Please enter 1, 2, 3, or 4.")

    if args.output is None:
        if args.direction == "resize":
            args.output = args.input / f"rotated_resize{time.strftime('%Y%m%d%H%M')}"
        else:
            args.output = args.input / f"rotated_{args.direction}"

    return args


def list_videos(input_dir: Path, recursive: bool) -> List[Path]:
    if recursive:
        candidates: Iterable[Path] = input_dir.rglob("*")
    else:
        candidates = input_dir.glob("*")
    return sorted(
        p
        for p in candidates
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )


def build_output_path(src: Path, input_dir: Path, output_dir: Path, direction: str) -> Path:
    relative_path = src.relative_to(input_dir)
    if direction == "resize":
        new_name = f"{relative_path.stem}_resize.MP4"
    else:
        new_name = f"{relative_path.stem}_rotation_{direction}{relative_path.suffix}"
    output_path = output_dir / relative_path.parent / new_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def build_video_filter(rotate_filter: str | None, enhance_color: bool) -> str | None:
    filters: list[str] = []
    if rotate_filter:
        filters.append(rotate_filter)
    if enhance_color:
        filters.append(COLOR_ENHANCE_FILTER)
    return ",".join(filters) if filters else None


def build_output_dir_name(mode: str, timestamp: str | None = None) -> str:
    if mode == "resize":
        return f"rotated_resize{timestamp or ''}"
    if timestamp:
        return f"rotated_{mode}_{timestamp}"
    return f"rotated_{mode}"


def _resource_path(relative: str) -> Path:
    """Resolve path to a bundled resource (works both in dev and PyInstaller .exe)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / relative


def resolve_ffmpeg(ffmpeg_arg: Path | None) -> str | None:
    if ffmpeg_arg is not None:
        path = ffmpeg_arg.expanduser().resolve()
        return str(path) if path.exists() else None

    found = shutil.which("ffmpeg")
    if found:
        return found

    # Common Homebrew/macOS locations (Apple Silicon and Intel)
    mac_fallbacks = [
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ]
    for candidate in mac_fallbacks:
        if candidate.exists():
            return str(candidate)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_link = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        if winget_link.exists():
            return str(winget_link)

        winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        package_pattern = "Gyan.FFmpeg_Microsoft.Winget.Source_*"
        for package_dir in winget_packages.glob(package_pattern):
            for ffmpeg_exe in package_dir.glob("*/bin/ffmpeg.exe"):
                if ffmpeg_exe.exists():
                    return str(ffmpeg_exe)

    fallback_paths = [
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"),
    ]
    for candidate in fallback_paths:
        if candidate.exists():
            return str(candidate)

    return None


def run_ffmpeg(
    src: Path,
    dst: Path,
    ffmpeg_bin: str,
    video_filter: str | None,
    overwrite: bool,
    codec: str,
    preset: str,
    crf: str,
    stop_event: threading.Event | None = None,
) -> JobResult:
    start = time.perf_counter()
    overwrite_flag = "-y" if overwrite else "-n"

    def cleanup_partial_output() -> None:
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            pass

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        overwrite_flag,
        "-i",
        str(src),
    ]
    if video_filter:
        cmd.extend(["-vf", video_filter])
    cmd.extend([
        "-c:v",
        codec,
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-c:a",
        "copy",
        str(dst),
    ])

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=_NO_WINDOW,
        )
        stdout = ""
        stderr = ""
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if stop_event is not None and stop_event.is_set():
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                    cleanup_partial_output()
                    return JobResult(
                        source=src,
                        output=dst,
                        ok=False,
                        elapsed=time.perf_counter() - start,
                        error="Stopped by user",
                    )
    except KeyboardInterrupt:
        try:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
        except Exception:
            pass
        cleanup_partial_output()
        return JobResult(
            source=src,
            output=dst,
            ok=False,
            elapsed=time.perf_counter() - start,
            error="Stopped by user",
        )
    except FileNotFoundError:
        return JobResult(
            source=src,
            output=dst,
            ok=False,
            elapsed=time.perf_counter() - start,
            error="ffmpeg not found. Please install ffmpeg and add it to PATH.",
        )

    if process.returncode == 0:
        return JobResult(
            source=src,
            output=dst,
            ok=True,
            elapsed=time.perf_counter() - start,
        )

    return JobResult(
        source=src,
        output=dst,
        ok=False,
        elapsed=time.perf_counter() - start,
        error=(stderr or stdout or "Unknown ffmpeg error").strip(),
    )


def process_videos(
    args: argparse.Namespace,
    log: LogFn,
    progress: ProgressFn | None = None,
    stop_event: threading.Event | None = None,
) -> int:
    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    workers = max(1, args.workers)

    if not input_dir.exists() or not input_dir.is_dir():
        log(f"[ERROR] Input folder does not exist: {input_dir}")
        return 1

    ffmpeg_bin = resolve_ffmpeg(args.ffmpeg)
    if ffmpeg_bin is None:
        log("[ERROR] ffmpeg not found.")
        if sys.platform == "win32":
            log("Install with winget: winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements")
            log("Or run with --ffmpeg \"C:\\path\\to\\ffmpeg.exe\"")
        elif sys.platform == "darwin":
            log("Install with Homebrew: brew install ffmpeg")
            log("Or run with --ffmpeg /opt/homebrew/bin/ffmpeg")
        else:
            log("Install ffmpeg using your package manager (example: sudo apt install ffmpeg)")
            log("Or run with --ffmpeg /usr/bin/ffmpeg")
        return 1

    rotate_filter = ROTATE_MAP[args.direction]

    videos = list_videos(input_dir, args.recursive)
    if not videos:
        log("[INFO] No video files found in the selected folder.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(videos)
    if progress is not None:
        progress(0, total)

    if stop_event is not None and stop_event.is_set():
        log("[INFO] Stopped before processing started.")
        return 130

    video_filter = build_video_filter(ROTATE_MAP[args.direction], bool(getattr(args, "enhance_color", False)))

    log("=== Video Rotate Batch ===")
    log(f"Input folder : {input_dir}")
    log(f"Output folder: {output_dir}")
    log(f"Direction    : {args.direction}")
    log(f"Enhance color: {'yes' if getattr(args, 'enhance_color', False) else 'no'}")
    log(f"Videos found : {total}")
    log(f"Workers      : {workers}")
    log(f"ffmpeg       : {ffmpeg_bin}")
    log("==========================")

    jobs = []
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    stopped = False
    done = 0
    ok_count = 0
    fail_count = 0
    try:
        for src in videos:
            if stop_event is not None and stop_event.is_set():
                stopped = True
                break
            dst = build_output_path(src, input_dir, output_dir, args.direction)
            future = executor.submit(
                run_ffmpeg,
                src,
                dst,
                ffmpeg_bin,
                video_filter,
                args.overwrite,
                args.codec,
                args.preset,
                args.crf,
                stop_event,
            )
            jobs.append(future)

        for future in concurrent.futures.as_completed(jobs):
            if stop_event is not None and stop_event.is_set():
                stopped = True
                break
            result = future.result()
            done += 1
            if progress is not None:
                progress(done, total)
            if result.ok:
                ok_count += 1
                log(
                    f"[{done}/{len(videos)}] OK   {result.source.name} "
                    f"({result.elapsed:.1f}s)"
                )
            else:
                fail_count += 1
                log(
                    f"[{done}/{len(videos)}] FAIL {result.source.name} "
                    f"({result.elapsed:.1f}s)"
                )
                if result.error:
                    log(f"           -> {result.error}")

                if result.error == "Stopped by user":
                    stopped = True
                    break

        if stop_event is not None and stop_event.is_set():
            stopped = True
    except KeyboardInterrupt:
        stopped = True
        if stop_event is not None:
            stop_event.set()
        log("[INFO] Stop requested by user.")
    finally:
        executor.shutdown(wait=not stopped, cancel_futures=stopped)

    if stopped:
        log("==========================")
        log(f"Stopped. Success: {ok_count}, Failed: {fail_count}")
        log(f"Output at: {output_dir}")
        return 130

    log("==========================")
    log(f"Completed. Success: {ok_count}, Failed: {fail_count}")
    log(f"Output at: {output_dir}")
    return 0 if fail_count == 0 else 2


def run_gui(args: argparse.Namespace) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception:
        print("[ERROR] Tkinter is not available. Use --cli mode instead.")
        return 1

    root = tk.Tk()
    root.title("RUNNING.IN.TH VIDEOS ROTATE")
    _ico_path = _resource_path("favicon.ico")
    if _ico_path.exists():
        try:
            root.iconbitmap(str(_ico_path))
        except Exception:
            # iconbitmap may not support .ico on some platforms (notably macOS)
            pass
    root.geometry("880x660")
    root.minsize(760, 580)

    style = ttk.Style()
    for theme in ("vista", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    BG = "#f7f7f7"
    ACCENT = "#e30613"
    style.configure(".", font=("Tahoma", 12), background=BG)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG)
    style.configure("TRadiobutton", background=BG)
    style.configure("TCheckbutton", background=BG)
    style.configure("TLabelframe", background=BG, borderwidth=1)
    style.configure("TLabelframe.Label", background=BG, foreground="#333333", font=("Tahoma", 12))
    style.configure("TProgressbar", troughcolor="#ddd", background=ACCENT)
    root.configure(bg=BG)

    main = ttk.Frame(root, padding=(16, 12))
    main.pack(fill="both", expand=True)
    main.columnconfigure(0, weight=1)

    # Load logo
    _logo_img_ref = None
    try:
        from PIL import Image, ImageTk
        _logo_path = _resource_path("logo.png")
        if _logo_path.exists():
            _pil = Image.open(_logo_path)
            _pil.thumbnail((100, 50), Image.LANCZOS)
            _logo_img_ref = ImageTk.PhotoImage(_pil)
    except Exception:
        try:
            _logo_path = _resource_path("logo.png")
            if _logo_path.exists():
                _tk_img = tk.PhotoImage(file=str(_logo_path))
                _w, _h = _tk_img.width(), _tk_img.height()
                _factor = max(1, _h // 50)
                _logo_img_ref = _tk_img.subsample(_factor, _factor)
        except Exception:
            pass

    # Header: logo top-left, title/subtitle on the right
    header = ttk.Frame(main)
    header.grid(row=0, column=0, sticky="ew", pady=(0, 0))
    header.columnconfigure(1, weight=1)

    if _logo_img_ref is not None:
        logo_lbl = ttk.Label(header, image=_logo_img_ref)
        logo_lbl.image = _logo_img_ref
        logo_lbl.grid(row=0, column=0, sticky="nw")

    tk.Frame(main, bg="#e30613", height=3).grid(row=1, column=0, sticky="ew", pady=(4, 10))

    input_var = tk.StringVar(value=str(args.input) if args.input else "")
    direction_var = tk.StringVar(value=args.direction or "left")
    enhance_color_var = tk.BooleanVar(value=bool(getattr(args, "enhance_color", False)))

    def computed_output_path() -> str:
        src = input_var.get().strip()
        if not src:
            return ""
        ts = time.strftime("%Y%m%d%H%M")
        return str(Path(src) / build_output_dir_name(direction_var.get(), ts))

    def browse_input() -> None:
        selected = filedialog.askdirectory(title="Select video folder")
        if selected:
            input_var.set(selected)
            refresh_output_preview()

    top_card = ttk.LabelFrame(main, text="โฟลเดอร์วิดีโอ", padding=10)
    top_card.grid(row=2, column=0, sticky="ew", pady=(0, 6))
    top_card.columnconfigure(0, weight=1)

    input_entry = ttk.Entry(top_card, textvariable=input_var)
    input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    browse_input_btn = ttk.Button(top_card, text="Browse", command=browse_input)
    browse_input_btn.grid(row=0, column=1, sticky="ew")

    direction_card = ttk.LabelFrame(main, text="ทิศทางการหมุน", padding=10)
    direction_card.grid(row=3, column=0, sticky="ew", pady=(0, 6))

    direction_buttons = ttk.Frame(direction_card)
    direction_buttons.pack(anchor="w")
    left_radio = ttk.Radiobutton(direction_buttons, text="หมุนซ้าย 90°", value="left", variable=direction_var)
    right_radio = ttk.Radiobutton(direction_buttons, text="หมุนขวา 90°", value="right", variable=direction_var)
    flip_radio = ttk.Radiobutton(direction_buttons, text="หมุน 180°", value="180", variable=direction_var)
    resize_radio = ttk.Radiobutton(direction_buttons, text="ไม่หมุน / ย่อไฟล์", value="resize", variable=direction_var)
    left_radio.pack(side="left", padx=(0, 14))
    right_radio.pack(side="left", padx=(0, 14))
    flip_radio.pack(side="left")
    resize_radio.pack(side="left", padx=(14, 0))

    enhance_check = ttk.Checkbutton(
        main,
        text="ปรับสี / ลด highlight / เพิ่มสี / ยก shadow",
        variable=enhance_color_var,
    )
    enhance_check.grid(row=4, column=0, sticky="w", pady=(8, 0))

    output_preview_var = tk.StringVar(value=f"Output: {computed_output_path()}")
    output_preview = ttk.Label(main, textvariable=output_preview_var, foreground="#2f6f44")
    output_preview.grid(row=5, column=0, sticky="w", pady=(10, 0))

    controls_enabled = True

    def get_quality_settings() -> tuple[str, str, str]:
        return ("libx264", "veryfast", "23")

    def on_direction_change(*_args: object) -> None:
        refresh_output_preview()

    def refresh_output_preview() -> None:
        output_preview_var.set(f"Output: {computed_output_path()}")

    direction_var.trace_add("write", on_direction_change)
    input_var.trace_add("write", lambda *_: refresh_output_preview())

    progress_text = tk.StringVar(value="Ready")
    ttk.Label(main, textvariable=progress_text).grid(row=6, column=0, sticky="w", pady=(12, 4))
    progress = ttk.Progressbar(main, mode="determinate")
    progress.grid(row=7, column=0, sticky="ew", pady=(0, 8))

    log_frame = ttk.LabelFrame(main, text="Log", padding=4)
    log_frame.grid(row=8, column=0, sticky="nsew", pady=(4, 0))
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    main.rowconfigure(8, weight=1)
    log_scroll = ttk.Scrollbar(log_frame, orient="vertical")
    log_scroll.grid(row=0, column=1, sticky="ns")
    log_box = tk.Text(log_frame, height=8, wrap="word", font=("Tahoma", 11), yscrollcommand=log_scroll.set, relief="flat", borderwidth=0)
    log_box.grid(row=0, column=0, sticky="nsew")
    log_scroll.configure(command=log_box.yview)

    button_row = ttk.Frame(main)
    button_row.grid(row=9, column=0, sticky="e", pady=(10, 0))
    start_button = ttk.Button(button_row, text="▶  Start Rotation", width=20)
    start_button.pack(side="left", padx=8)
    stop_button = ttk.Button(button_row, text="■  Stop", width=12)
    stop_button.pack(side="left", padx=(0, 8))

    def open_output_folder() -> None:
        path = last_output_dir[0] or computed_output_path()
        if path and Path(path).exists():
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        else:
            messagebox.showinfo("Output Folder", f"Folder not found:\n{path}")

    open_folder_btn = ttk.Button(button_row, text="Open Output Folder", command=open_output_folder)
    open_folder_btn.pack(side="left", padx=(0, 8))
    close_button = ttk.Button(button_row, text="Close", command=root.destroy)
    close_button.pack(side="left")

    ttk.Separator(main, orient="horizontal").grid(row=10, column=0, sticky="ew", pady=(4, 4))
    footer_frame = ttk.Frame(main)
    footer_frame.grid(row=11, column=0, sticky="ew", pady=(0, 4))
    footer_frame.columnconfigure(0, weight=1)
    ttk.Label(
        footer_frame,
        text="Copyright 2026 © running.in.th  |  ishootrun.in.th  |  sportaction.photos  |  eventrunning.photos",
        font=("Tahoma", 12),
        foreground="#5c5c5c",
    ).grid(row=0, column=0, sticky="w")
    ttk.Label(
        footer_frame,
        text="v1.0.0",
        font=("Tahoma", 11),
        foreground="#5c5c5c",
    ).grid(row=0, column=1, sticky="e")

    last_output_dir: list[str] = [""]

    events: queue.Queue[tuple] = queue.Queue()
    worker_thread: threading.Thread | None = None
    stop_event = threading.Event()

    def append_log(message: str) -> None:
        log_box.insert("end", message + "\n")
        log_box.see("end")

    def set_controls(enabled: bool) -> None:
        nonlocal controls_enabled
        controls_enabled = enabled
        state = "normal" if enabled else "disabled"
        for widget in (
            input_entry,
            browse_input_btn,
            right_radio,
            left_radio,
            flip_radio,
            resize_radio,
            enhance_check,
            start_button,
            open_folder_btn,
            close_button,
        ):
            widget.configure(state=state)
        stop_button.configure(state="disabled" if enabled else "normal")

    def pump_events() -> None:
        nonlocal worker_thread
        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                break

            kind = event[0]
            if kind == "log":
                append_log(event[1])
            elif kind == "progress":
                done, total = event[1], event[2]
                progress["maximum"] = max(total, 1)
                progress["value"] = done
                progress_text.set(f"Progress: {done}/{total}")
            elif kind == "done":
                code = event[1]
                elapsed = event[2] if len(event) > 2 else 0.0
                mins, secs = divmod(int(elapsed), 60)
                elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                set_controls(True)
                if code == 0:
                    progress_text.set(f"Done ({elapsed_str})")
                    messagebox.showinfo("Completed", f"Video rotation completed.\nTotal time: {elapsed_str}")
                elif code == 130:
                    progress_text.set(f"Stopped ({elapsed_str})")
                elif code == 2:
                    progress_text.set(f"Completed with errors ({elapsed_str})")
                    messagebox.showwarning("Completed with errors", f"Some videos failed to rotate.\nTotal time: {elapsed_str}")
                else:
                    progress_text.set("Failed")
                    messagebox.showerror("Failed", "Rotation could not be started.")
                worker_thread = None

        if worker_thread is not None and worker_thread.is_alive():
            root.after(120, pump_events)

    def start_rotation() -> None:
        nonlocal worker_thread
        if worker_thread is not None and worker_thread.is_alive():
            return

        input_dir = input_var.get().strip().strip('"')
        if not input_dir:
            messagebox.showerror("Missing input", "Please select an input folder.")
            return

        output_dir = computed_output_path()
        last_output_dir[0] = output_dir
        codec, preset, crf = get_quality_settings()

        run_args = argparse.Namespace(
            input=Path(input_dir),
            output=Path(output_dir),
            direction=direction_var.get(),
            workers=2,
            recursive=False,
            overwrite=False,
            codec=codec,
            preset=preset,
            crf=crf,
            ffmpeg=args.ffmpeg,
            enhance_color=enhance_color_var.get(),
        )

        log_box.delete("1.0", "end")
        progress["value"] = 0
        progress["maximum"] = 1
        progress_text.set("Starting...")
        stop_event.clear()
        set_controls(False)

        _start_time = time.perf_counter()

        def worker() -> None:
            exit_code = process_videos(
                run_args,
                log=lambda msg: events.put(("log", msg)),
                progress=lambda done, total: events.put(("progress", done, total)),
                stop_event=stop_event,
            )
            events.put(("done", exit_code, time.perf_counter() - _start_time))

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        root.after(120, pump_events)

    def stop_rotation() -> None:
        if worker_thread is None or not worker_thread.is_alive():
            return
        stop_event.set()
        progress_text.set("Stopping...")
        append_log("[INFO] Stop requested by user.")

    def _check_ffmpeg_on_start() -> None:
        if resolve_ffmpeg(args.ffmpeg) is not None:
            return

        if sys.platform != "win32":
            install_hint = "brew install ffmpeg" if sys.platform == "darwin" else "sudo apt install ffmpeg"
            append_log("[ERROR] ffmpeg not found in system PATH")
            append_log(f"[INFO] Install command: {install_hint}")
            progress_text.set("ffmpeg not found")
            messagebox.showwarning(
                "ffmpeg not found",
                "ffmpeg was not found in your system.\n\n"
                f"Try installing with:\n{install_hint}",
            )
            return

        answer = messagebox.askyesno(
            "ไม่พบ ffmpeg",
            "ไม่พบ ffmpeg ในระบบ\n\n"
            "ต้องการติดตั้ง ffmpeg อัตโนมัติผ่าน winget หรือไม่?\n"
            "(ใช้เวลาประมาณ 1-2 นาที)\n\n"
            "หากกด No สามารถดาวน์โหลดเองได้ที่:\n"
            "https://www.gyan.dev/ffmpeg/builds/",
            icon="warning",
        )
        if not answer:
            return

        set_controls(False)
        append_log("[INFO] กำลังติดตั้ง ffmpeg ผ่าน winget...")
        progress_text.set("Installing ffmpeg...")

        _install_done: list[bool] = [False]
        _install_ok: list[bool] = [False]
        _install_log: queue.Queue[str] = queue.Queue()

        def _install_worker() -> None:
            try:
                proc = subprocess.run(
                    [
                        "winget", "install",
                        "--id", "Gyan.FFmpeg",
                        "-e",
                        "--accept-source-agreements",
                        "--accept-package-agreements",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=_NO_WINDOW,
                )
                if proc.returncode == 0:
                    _install_log.put("[OK] ติดตั้ง ffmpeg สำเร็จแล้ว!")
                    _install_log.put("[INFO] กรุณาปิดแล้วเปิดโปรแกรมใหม่เพื่อใช้งาน")
                    _install_ok[0] = True
                else:
                    out = (proc.stdout or proc.stderr or "Unknown error").strip()
                    _install_log.put(f"[ERROR] ติดตั้งไม่สำเร็จ: {out}")
            except FileNotFoundError:
                _install_log.put("[ERROR] ไม่พบ winget ในระบบ")
                _install_log.put("[INFO] ดาวน์โหลด ffmpeg เอง: https://www.gyan.dev/ffmpeg/builds/")
            finally:
                _install_done[0] = True

        threading.Thread(target=_install_worker, daemon=True).start()

        def _poll_install() -> None:
            while True:
                try:
                    msg = _install_log.get_nowait()
                    append_log(msg)
                except queue.Empty:
                    break
            if not _install_done[0]:
                root.after(300, _poll_install)
                return
            set_controls(True)
            if _install_ok[0]:
                progress_text.set("ffmpeg installed — Please restart")
                messagebox.showinfo(
                    "ติดตั้งสำเร็จ",
                    "ติดตั้ง ffmpeg สำเร็จแล้ว\nกรุณาปิดและเปิดโปรแกรมใหม่เพื่อใช้งาน",
                )
            else:
                progress_text.set("ffmpeg not found")

        root.after(300, _poll_install)

    start_button.configure(command=start_rotation)
    stop_button.configure(command=stop_rotation, state="disabled")
    get_quality_settings()
    refresh_output_preview()
    root.after(400, _check_ffmpeg_on_start)
    root.mainloop()
    return 0


def main() -> int:
    args = parse_args()
    use_gui = args.gui or (not args.cli and args.input is None)
    if use_gui:
        return run_gui(args)

    try:
        args = prompt_for_missing(args)
        return process_videos(args, log=print, stop_event=threading.Event())
    except KeyboardInterrupt:
        print("[INFO] Stop requested by user.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
