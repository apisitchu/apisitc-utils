# Video Rotate Batch

โปรแกรมสำหรับหมุนวิดีโอทั้งโฟลเดอร์ พร้อมประมวลผลหลายไฟล์แบบขนานเพื่อให้ทำงานเร็วขึ้น

## ความสามารถ

- เลือกโฟลเดอร์ต้นทางของวิดีโอ
- เลือกทิศทางหมุน (`right`, `left`, `180`)
- รองรับหมุนไฟล์จำนวนมากพร้อมกันด้วย worker หลายตัว
- รองรับสแกนโฟลเดอร์ย่อย (`--recursive`)

## สิ่งที่ต้องมี

1. ติดตั้ง Python 3.10+
2. ติดตั้ง `ffmpeg`

ตัวอย่างคำสั่ง:

- Windows: `winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements`
- macOS: `brew install ffmpeg`

ตรวจสอบ:

```bash
python3 --version
ffmpeg -version
```

## ตั้งค่าให้พร้อมใช้งาน (Windows)

ดับเบิลคลิก `setup_windows.bat` 1 ครั้ง

หรือรันใน PowerShell:

```bash
.\setup_windows.bat
```

เสร็จแล้วให้ใช้งานด้วย `run_rotate.bat`

## ตั้งค่าให้พร้อมใช้งาน (macOS)

รันครั้งแรก:

```bash
chmod +x setup_mac.sh run_rotate.sh
./setup_mac.sh
```

เสร็จแล้วให้ใช้งานด้วย:

```bash
./run_rotate.sh
```

## วิธีใช้งานแบบถามตอบ

Windows:

```bash
py video_rotator.py
```

macOS / Linux:

```bash
python3 video_rotator.py
```

คำสั่งนี้จะเปิดหน้า UI ให้เลือกได้เลย:
- Browse โฟลเดอร์วิดีโอ
- เลือกโฟลเดอร์ปลายทาง
- เลือกทิศทางหมุน
- กด Start Rotation

ถ้าต้องการใช้โหมด Terminal เดิม:

```bash
python3 video_rotator.py --cli
```

## วิธีใช้งานแบบคำสั่งเดียว

```bash
python3 video_rotator.py --input "/path/to/videos" --direction right --workers 6 --recursive
```

ตัวอย่างกำหนด output เอง:

```bash
python3 video_rotator.py --input "/path/to/videos" --output "/path/to/videos_rotated" --direction left --workers 8
```

## ตัวเลือกที่สำคัญ

- `--input` โฟลเดอร์ต้นทาง
- `--output` โฟลเดอร์ปลายทาง (ถ้าไม่กำหนดจะใช้ `<input>\rotated_<direction>`)
- `--direction` ทิศทางหมุน: `right` / `left` / `180`
- `--workers` จำนวนงานขนาน (แนะนำปรับตาม CPU/GPU)
- `--recursive` ค้นหาไฟล์ในโฟลเดอร์ย่อย
- `--overwrite` เขียนทับไฟล์ปลายทาง
- `--codec` codec วิดีโอ (ค่าเริ่มต้น `libx264`)
- `--preset` preset ความเร็วการเข้ารหัส (ค่าเริ่มต้น `veryfast`)
- `--crf` คุณภาพวิดีโอ (ค่าเริ่มต้น `23`)
- `--ffmpeg` path ไปยัง `ffmpeg` (กรณีไม่ได้อยู่ใน PATH)

## หมายเหตุด้านความเร็ว

- เพิ่ม `--workers` จะเร็วขึ้นเมื่อมีหลายไฟล์ แต่หากมากเกินไปอาจทำให้เครื่องช้าหรือคอขวด
- ถ้ามีการ์ดจอที่รองรับ อาจลอง `--codec h264_nvenc` เพื่อเร่งด้วย GPU

---

## การ Build เป็นไฟล์ .exe (สำหรับแจกจ่าย)

### สิ่งที่ต้องเตรียม

| ไฟล์ | รายละเอียด |
|------|------------|
| `video_rotator.py` | source code หลัก |
| `logo.png` | ไฟล์โลโก้ (วางไว้ในโฟลเดอร์เดียวกัน) |
| `favicon.ico` | ไฟล์ไอคอน (วางไว้ในโฟลเดอร์เดียวกัน) |
| Python 3.10+ | ติดตั้งแล้วใช้งานได้ผ่านคำสั่ง `py` |

### ขั้นตอนการ Build

**1. Build ปกติ (ไม่ sign)**

```bat
build.bat
```

ผลลัพธ์: `dist\VideoRotate-RUNNING.IN.TH-v1.0.0.exe`

---

**2. Build พร้อม Code Signing (แสดง Publisher: running.in.th)**

ทำครั้งแรกครั้งเดียว — สร้าง signing certificate:

```
คลิกขวา create_cert.ps1 → Run with PowerShell
```

ตั้ง password แล้วจะได้ไฟล์ `signing_cert.pfx`

จากนั้น build ตามปกติ:

```bat
build.bat
```

ระหว่าง build จะถามรหัส pfx → กรอก password ที่ตั้งไว้ → exe จะถูก sign อัตโนมัติ

> **หมายเหตุ:** self-signed certificate จะแสดงชื่อ Publisher เป็น `running.in.th`
> แต่ Windows SmartScreen ยังขึ้น blue warning อยู่ (ผู้ใช้กด "More info" → "Run anyway")
> หากต้องการไม่มี warning เลย ต้องซื้อ commercial cert จาก DigiCert / Sectigo

---

### เปลี่ยน Version

แก้ค่า `VERSION` ใน `build.bat` บรรทัดบนสุด:

```bat
set "VERSION=1.0.1"
```

ชื่อไฟล์ exe จะเปลี่ยนตามอัตโนมัติ เช่น `VideoRotate-RUNNING.IN.TH-v1.0.1.exe`

---

### โครงสร้างไฟล์ใน build folder

```
VIDEO ROTATE/
├── video_rotator.py      ← source หลัก
├── logo.png              ← โลโก้ (ต้องมี)
├── favicon.ico           ← ไอคอน (ต้องมี)
├── build.bat             ← สคริปต์ build
├── create_cert.ps1       ← สร้าง signing certificate (ทำครั้งแรกครั้งเดียว)
├── signing_cert.pfx      ← certificate file (สร้างโดย create_cert.ps1)
└── dist/
    └── VideoRotate-RUNNING.IN.TH-v1.0.0.exe  ← ไฟล์สำหรับแจกจ่าย
```
