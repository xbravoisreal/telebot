# 🤖 Telegram Link Bot → Google Sheets

Bot tự động lưu link vào Google Sheets khi thành viên nhóm gõ lệnh `/link`.

---

## 📋 Các lệnh

| Lệnh | Mô tả |
|------|-------|
| `/link <url>` | Lưu link vào Sheets |
| `/link <url> <mô tả>` | Lưu link kèm ghi chú |
| `/recent` | Xem 5 link mới nhất |
| `/count` | Đếm tổng số link đã lưu |
| `/help` | Xem hướng dẫn |

---

## ⚙️ Cài đặt (5 bước)

### Bước 1 – Tạo Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gõ `/newbot` → đặt tên → đặt username (kết thúc bằng `bot`)
3. Copy **Token** nhận được → dán vào `config.py`

### Bước 2 – Tạo Google Service Account

1. Vào [Google Cloud Console](https://console.cloud.google.com/)
2. Tạo project mới (hoặc dùng project có sẵn)
3. Vào **APIs & Services → Enable APIs**:
   - Bật **Google Sheets API**
   - Bật **Google Drive API**
4. Vào **APIs & Services → Credentials → Create Credentials → Service Account**
5. Đặt tên → nhấn **Done**
6. Click vào Service Account vừa tạo → tab **Keys → Add Key → JSON**
7. Download file JSON → đổi tên thành `credentials.json` → đặt cùng thư mục với `bot.py`

### Bước 3 – Tạo Google Spreadsheet

1. Vào [Google Sheets](https://sheets.google.com/) → tạo spreadsheet mới
2. Copy **ID** từ URL:
   ```
   https://docs.google.com/spreadsheets/d/[SPREADSHEET_ID]/edit
   ```
3. **Share** spreadsheet với email của Service Account (xem trong file `credentials.json`, trường `client_email`) với quyền **Editor**

### Bước 4 – Cấu hình

Mở `config.py` và điền:

```python
TELEGRAM_BOT_TOKEN = "1234567890:ABCdef..."   # Token từ BotFather
SPREADSHEET_ID     = "1BxiMVs0XRA5nFMd..."    # ID của Spreadsheet
WORKSHEET_NAME     = "Links"                   # Tên sheet (tuỳ chọn)
GOOGLE_CREDENTIALS_FILE = "credentials.json"  # Giữ nguyên nếu cùng thư mục
```

### Bước 5 – Chạy bot

```bash
# Cài dependencies
pip install -r requirements.txt

# Chạy bot
python bot.py
```

---

## 📊 Cấu trúc Google Sheet

Bot tự tạo các cột sau:

| STT | URL | Mô tả | Người gửi | Nhóm/Chat | Thời gian |
|-----|-----|-------|-----------|-----------|-----------|
| 1 | https://... | Ghi chú | Nguyễn A (@user) | Tên nhóm | 27/05/2025 10:30:00 |

---

## ☁️ Deploy lên server (tuỳ chọn)

### Dùng Railway (miễn phí)

1. Đăng ký [railway.app](https://railway.app)
2. New Project → Deploy from GitHub repo
3. Thêm các biến môi trường trong Settings → Variables

### Dùng VPS / systemd

```bash
# Tạo service
sudo nano /etc/systemd/system/telegram-link-bot.service
```

```ini
[Unit]
Description=Telegram Link Bot
After=network.target

[Service]
WorkingDirectory=/path/to/bot
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable telegram-link-bot
sudo systemctl start telegram-link-bot
```

---

## 🔒 Thêm bot vào nhóm

1. Mở nhóm Telegram → **Add member** → tìm username bot
2. Cấp quyền **Admin** (để bot đọc được tin nhắn trong nhóm)
3. Test: gõ `/link https://example.com Test link`

---

## ❓ Troubleshooting

| Lỗi | Cách xử lý |
|-----|-----------|
| `PERMISSION_DENIED` | Chưa share Spreadsheet cho Service Account |
| `Invalid token` | Kiểm tra lại `TELEGRAM_BOT_TOKEN` trong `config.py` |
| `SpreadsheetNotFound` | Kiểm tra lại `SPREADSHEET_ID` |
| Bot không phản hồi trong nhóm | Cấp quyền Admin cho bot trong nhóm |
