"""
Chay script nay 1 LAN DUY NHAT tren may local de tao session file.
Sau do upload file 'linkbot.session' len FPS.ms cung thu muc voi bot.py
"""
from telethon.sync import TelegramClient

# Dien vao day
API_ID   = 32165145          # <- thay bang App api_id (so)
API_HASH = "a289b4fc3f4fc862b68d8920f462d434"         # <- thay bang App api_hash (chuoi)

print("=== Tao Telethon Session ===")
print("Ban se can nhap:")
print("  1. So dien thoai Telegram (+84...)")
print("  2. Ma OTP duoc gui vao app Telegram")
print()

with TelegramClient("linkbot", API_ID, API_HASH) as client:
    me = client.get_me()
    print("Dang nhap thanh cong!")
    print("Ten:", me.first_name)
    print("Username:", me.username)
    print()
    print("File session da duoc tao: linkbot.session")
    print("Upload file nay len FPS.ms cung thu muc voi bot.py")
