# Video Rotate Batch

โปรแกรมสำหรับหมุนวิดีโอทั้งโฟลเดอร์ พร้อมประมวลผลหลายไฟล์แบบขนานเพื่อให้ทำงานเร็วขึ้น

## ความสามารถ

- เลือกโฟลเดอร์ต้นทางของวิดีโอ
- เลือกทิศทางหมุน (`right`, `left`, `180`)
- รองรับหมุนไฟล์จำนวนมากพร้อมกันด้วย worker หลายตัว
- รองรับสแกนโฟลเดอร์ย่อย (`--recursive`)

## สิ่งที่ต้องมี

1. ติดตั้ง Python 3.10+ (บน Windows แนะนำใช้คำสั่ง `py`)
2. ติดตั้ง `ffmpeg` (หรือใช้สคริปต์ `setup_windows.bat` ให้ติดตั้งอัตโนมัติ)

ตรวจสอบ:

```bash
py --version
ffmpeg -version
```

## ตั้งค่าให้พร้อมใช้งาน (Windows)

ดับเบิลคลิก `setup_windows.bat` 1 ครั้ง

หรือรันใน PowerShell:

```bash
.\setup_windows.bat
```

เสร็จแล้วให้ใช้งานด้วย `run_rotate.bat`

## วิธีใช้งานแบบถามตอบ

```bash
py video_rotator.py
```

คำสั่งนี้จะเปิดหน้า UI ให้เลือกได้เลย:
- Browse โฟลเดอร์วิดีโอ
- เลือกโฟลเดอร์ปลายทาง
- เลือกทิศทางหมุน
- กด Start Rotation

ถ้าต้องการใช้โหมด Terminal เดิม:

```bash
py video_rotator.py --cli
```

## วิธีใช้งานแบบคำสั่งเดียว

```bash
py video_rotator.py --input "D:\videos" --direction right --workers 6 --recursive
```

ตัวอย่างกำหนด output เอง:

```bash
py video_rotator.py --input "D:\videos" --output "D:\videos_rotated" --direction left --workers 8
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
- `--ffmpeg` path ไปยัง `ffmpeg.exe` (กรณีไม่ได้อยู่ใน PATH)

## หมายเหตุด้านความเร็ว

- เพิ่ม `--workers` จะเร็วขึ้นเมื่อมีหลายไฟล์ แต่หากมากเกินไปอาจทำให้เครื่องช้าหรือคอขวด
- ถ้ามีการ์ดจอที่รองรับ อาจลอง `--codec h264_nvenc` เพื่อเร่งด้วย GPU
