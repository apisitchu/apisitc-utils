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
}


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
        choices=["right", "left", "180"],
        help="Rotation direction: right, left, or 180.",
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
        mapping = {"1": "right", "2": "left", "3": "180"}
        while True:
            choice = input("Direction [1/2/3]: ").strip()
            if choice in mapping:
                args.direction = mapping[choice]
                break
            print("Invalid choice. Please enter 1, 2, or 3.")

    if args.output is None:
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


def build_output_path(src: Path, input_dir: Path, output_dir: Path) -> Path:
    relative_path = src.relative_to(input_dir)
    output_path = output_dir / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def resolve_ffmpeg(ffmpeg_arg: Path | None) -> str | None:
    if ffmpeg_arg is not None:
        path = ffmpeg_arg.expanduser().resolve()
        return str(path) if path.exists() else None

    found = shutil.which("ffmpeg")
    if found:
        return found

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
    rotate_filter: str,
    overwrite: bool,
    codec: str,
    preset: str,
    crf: str,
) -> JobResult:
    start = time.perf_counter()
    overwrite_flag = "-y" if overwrite else "-n"
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        overwrite_flag,
        "-i",
        str(src),
        "-vf",
        rotate_filter,
        "-c:v",
        codec,
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-c:a",
        "copy",
        str(dst),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return JobResult(
            source=src,
            output=dst,
            ok=False,
            elapsed=time.perf_counter() - start,
            error="ffmpeg not found. Please install ffmpeg and add it to PATH.",
        )

    if completed.returncode == 0:
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
        error=(completed.stderr or completed.stdout or "Unknown ffmpeg error").strip(),
    )


def process_videos(args: argparse.Namespace, log: LogFn, progress: ProgressFn | None = None) -> int:
    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    workers = max(1, args.workers)

    if not input_dir.exists() or not input_dir.is_dir():
        log(f"[ERROR] Input folder does not exist: {input_dir}")
        return 1

    ffmpeg_bin = resolve_ffmpeg(args.ffmpeg)
    if ffmpeg_bin is None:
        log("[ERROR] ffmpeg not found.")
        log("Install with winget: winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements")
        log("Or run with --ffmpeg \"C:\\path\\to\\ffmpeg.exe\"")
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

    log("=== Video Rotate Batch ===")
    log(f"Input folder : {input_dir}")
    log(f"Output folder: {output_dir}")
    log(f"Direction    : {args.direction}")
    log(f"Videos found : {total}")
    log(f"Workers      : {workers}")
    log(f"ffmpeg       : {ffmpeg_bin}")
    log("==========================")

    jobs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for src in videos:
            dst = build_output_path(src, input_dir, output_dir)
            future = executor.submit(
                run_ffmpeg,
                src,
                dst,
                ffmpeg_bin,
                rotate_filter,
                args.overwrite,
                args.codec,
                args.preset,
                args.crf,
            )
            jobs.append(future)

        done = 0
        ok_count = 0
        fail_count = 0

        for future in concurrent.futures.as_completed(jobs):
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
    root.title("Video Rotate Batch")
    root.geometry("820x560")
    root.minsize(740, 520)

    style = ttk.Style()
    for theme in ("vista", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break

    main = ttk.Frame(root, padding=18)
    main.pack(fill="both", expand=True)
    main.columnconfigure(0, weight=1)

    title = ttk.Label(main, text="Rotate Videos", font=("Segoe UI", 15, "bold"))
    title.grid(row=0, column=0, sticky="w")
    subtitle = ttk.Label(
        main,
        text="เลือกโฟลเดอร์วิดีโอ เลือกทิศทาง แล้วกดเริ่มได้เลย",
    )
    subtitle.grid(row=1, column=0, sticky="w", pady=(2, 14))

    input_var = tk.StringVar(value=str(args.input) if args.input else "")
    direction_var = tk.StringVar(value=args.direction or "right")
    quality_var = tk.StringVar(value="balanced")
    recursive_var = tk.BooleanVar(value=bool(args.recursive))
    output_var = tk.StringVar(value=str(args.output) if args.output else "")
    use_custom_output_var = tk.BooleanVar(value=bool(args.output))
    workers_var = tk.IntVar(value=max(1, args.workers))
    overwrite_var = tk.BooleanVar(value=bool(args.overwrite))
    show_advanced_var = tk.BooleanVar(value=False)

    def computed_output_path() -> str:
        src = input_var.get().strip()
        if not src:
            return ""
        return str(Path(src) / f"rotated_{direction_var.get()}")

    def browse_input() -> None:
        selected = filedialog.askdirectory(title="Select video folder")
        if selected:
            input_var.set(selected)
            refresh_output_preview()

    def browse_output() -> None:
        selected = filedialog.askdirectory(title="Select output folder")
        if selected:
            output_var.set(selected)

    top_card = ttk.Frame(main, padding=14)
    top_card.grid(row=2, column=0, sticky="ew")
    top_card.columnconfigure(1, weight=1)

    ttk.Label(top_card, text="โฟลเดอร์วิดีโอ").grid(row=0, column=0, sticky="w")
    input_entry = ttk.Entry(top_card, textvariable=input_var)
    input_entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(4, 0))
    browse_input_btn = ttk.Button(top_card, text="Browse", command=browse_input)
    browse_input_btn.grid(row=1, column=2, sticky="ew", pady=(4, 0))

    direction_card = ttk.Frame(main, padding=(14, 10))
    direction_card.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    ttk.Label(direction_card, text="ทิศทางการหมุน").pack(anchor="w")

    direction_buttons = ttk.Frame(direction_card)
    direction_buttons.pack(anchor="w", pady=(6, 0))
    right_radio = ttk.Radiobutton(direction_buttons, text="หมุนขวา 90°", value="right", variable=direction_var)
    left_radio = ttk.Radiobutton(direction_buttons, text="หมุนซ้าย 90°", value="left", variable=direction_var)
    flip_radio = ttk.Radiobutton(direction_buttons, text="หมุน 180°", value="180", variable=direction_var)
    right_radio.pack(side="left", padx=(0, 14))
    left_radio.pack(side="left", padx=(0, 14))
    flip_radio.pack(side="left")

    quality_card = ttk.Frame(main, padding=(14, 10))
    quality_card.grid(row=4, column=0, sticky="ew", pady=(10, 0))
    ttk.Label(quality_card, text="คุณภาพวิดีโอ").pack(anchor="w")
    quality_box = ttk.Combobox(
        quality_card,
        textvariable=quality_var,
        values=("high", "balanced", "small"),
        state="readonly",
        width=18,
    )
    quality_box.pack(anchor="w", pady=(6, 0))
    quality_hint_var = tk.StringVar(
        value="Balanced: คุณภาพดีและไฟล์ไม่ใหญ่เกินไป"
    )
    ttk.Label(quality_card, textvariable=quality_hint_var).pack(anchor="w", pady=(4, 0))

    quick_options = ttk.Frame(main)
    quick_options.grid(row=5, column=0, sticky="w", pady=(10, 0))
    recursive_check = ttk.Checkbutton(quick_options, text="รวมโฟลเดอร์ย่อย", variable=recursive_var)
    recursive_check.pack(side="left")

    output_preview_var = tk.StringVar(value=f"Output: {computed_output_path()}")
    output_preview = ttk.Label(main, textvariable=output_preview_var, foreground="#2f6f44")
    output_preview.grid(row=6, column=0, sticky="w", pady=(10, 0))

    advanced_toggle = ttk.Checkbutton(
        main,
        text="ตั้งค่าขั้นสูง",
        variable=show_advanced_var,
        command=lambda: advanced_frame.grid() if show_advanced_var.get() else advanced_frame.grid_remove(),
    )
    advanced_toggle.grid(row=7, column=0, sticky="w", pady=(10, 0))

    advanced_frame = ttk.Frame(main, padding=(12, 10))
    advanced_frame.grid(row=8, column=0, sticky="ew", pady=(6, 0))
    advanced_frame.columnconfigure(1, weight=1)
    advanced_frame.grid_remove()

    custom_output_check = ttk.Checkbutton(
        advanced_frame,
        text="เลือกโฟลเดอร์ปลายทางเอง",
        variable=use_custom_output_var,
        command=lambda: None,
    )
    custom_output_check.grid(row=0, column=0, columnspan=3, sticky="w")

    ttk.Entry(advanced_frame, textvariable=output_var).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0), padx=(0, 8))
    browse_output_btn = ttk.Button(advanced_frame, text="Browse", command=browse_output)
    browse_output_btn.grid(row=1, column=2, sticky="ew", pady=(6, 0))

    ttk.Label(advanced_frame, text="Workers").grid(row=2, column=0, sticky="w", pady=(8, 0))
    workers_spin = ttk.Spinbox(
        advanced_frame,
        from_=1,
        to=max(64, (os.cpu_count() or 8) * 2),
        textvariable=workers_var,
        width=8,
    )
    workers_spin.grid(row=2, column=1, sticky="w", pady=(8, 0))
    overwrite_check = ttk.Checkbutton(advanced_frame, text="เขียนทับไฟล์เดิม", variable=overwrite_var)
    overwrite_check.grid(row=2, column=2, sticky="e", pady=(8, 0))

    controls_enabled = True

    def get_quality_settings() -> tuple[str, str, str]:
        profile = quality_var.get()
        if profile == "high":
            quality_hint_var.set("High: คุณภาพสูงกว่าเดิม ไฟล์ใหญ่ขึ้น")
            return ("libx264", "slow", "18")
        if profile == "small":
            quality_hint_var.set("Small: ไฟล์เล็กลง เร็วขึ้น แต่คุณภาพลดลง")
            return ("libx264", "veryfast", "27")
        quality_hint_var.set("Balanced: คุณภาพดีและไฟล์ไม่ใหญ่เกินไป")
        return ("libx264", "veryfast", "23")

    def update_advanced_state() -> None:
        output_state = "normal" if (controls_enabled and use_custom_output_var.get()) else "disabled"
        for widget in (browse_output_btn,):
            widget.configure(state=output_state)
        for child in advanced_frame.winfo_children():
            if isinstance(child, ttk.Entry):
                child.configure(state=output_state)

    update_advanced_state()
    custom_output_check.configure(
        command=lambda: (update_advanced_state(), refresh_output_preview())
    )

    def on_direction_change(*_args: object) -> None:
        refresh_output_preview()

    def refresh_output_preview() -> None:
        auto_path = computed_output_path()
        if not use_custom_output_var.get():
            output_preview_var.set(f"Output: {auto_path}")
        else:
            custom = output_var.get().strip()
            output_preview_var.set(f"Output: {custom or auto_path}")

    direction_var.trace_add("write", on_direction_change)
    input_var.trace_add("write", lambda *_: refresh_output_preview())
    output_var.trace_add("write", lambda *_: refresh_output_preview())
    quality_var.trace_add("write", lambda *_: get_quality_settings())

    progress_text = tk.StringVar(value="Ready")
    ttk.Label(main, textvariable=progress_text).grid(row=9, column=0, sticky="w", pady=(12, 4))
    progress = ttk.Progressbar(main, mode="determinate")
    progress.grid(row=10, column=0, sticky="ew", pady=(0, 8))

    log_box = tk.Text(main, height=10, wrap="word")
    log_box.grid(row=11, column=0, sticky="nsew")
    main.rowconfigure(11, weight=1)

    button_row = ttk.Frame(main)
    button_row.grid(row=12, column=0, sticky="e", pady=(10, 0))
    start_button = ttk.Button(button_row, text="Start Rotation", width=18)
    start_button.pack(side="left", padx=8)
    close_button = ttk.Button(button_row, text="Close", command=root.destroy)
    close_button.pack(side="left")

    events: queue.Queue[tuple] = queue.Queue()
    worker_thread: threading.Thread | None = None

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
            quality_box,
            recursive_check,
            advanced_toggle,
            custom_output_check,
            workers_spin,
            overwrite_check,
            browse_output_btn,
            start_button,
            close_button,
        ):
            widget.configure(state=state)
        update_advanced_state()

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
                set_controls(True)
                if code == 0:
                    progress_text.set("Done")
                    messagebox.showinfo("Completed", "Video rotation completed.")
                elif code == 2:
                    progress_text.set("Completed with errors")
                    messagebox.showwarning("Completed with errors", "Some videos failed to rotate.")
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
        output_dir = output_var.get().strip().strip('"')
        if not input_dir:
            messagebox.showerror("Missing input", "Please select an input folder.")
            return

        if not use_custom_output_var.get() or not output_dir:
            output_dir = computed_output_path()
            output_var.set(output_dir)

        codec, preset, crf = get_quality_settings()

        run_args = argparse.Namespace(
            input=Path(input_dir),
            output=Path(output_dir),
            direction=direction_var.get(),
            workers=max(1, int(workers_var.get())),
            recursive=bool(recursive_var.get()),
            overwrite=bool(overwrite_var.get()),
            codec=codec,
            preset=preset,
            crf=crf,
            ffmpeg=args.ffmpeg,
        )

        log_box.delete("1.0", "end")
        progress["value"] = 0
        progress["maximum"] = 1
        progress_text.set("Starting...")
        set_controls(False)

        def worker() -> None:
            exit_code = process_videos(
                run_args,
                log=lambda msg: events.put(("log", msg)),
                progress=lambda done, total: events.put(("progress", done, total)),
            )
            events.put(("done", exit_code))

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        root.after(120, pump_events)

    start_button.configure(command=start_rotation)
    get_quality_settings()
    refresh_output_preview()
    root.mainloop()
    return 0


def main() -> int:
    args = parse_args()
    use_gui = args.gui or (not args.cli and args.input is None)
    if use_gui:
        return run_gui(args)

    args = prompt_for_missing(args)
    return process_videos(args, log=print)


if __name__ == "__main__":
    sys.exit(main())
