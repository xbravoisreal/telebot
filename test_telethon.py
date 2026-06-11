"""
Chay script nay de test Telethon co hoat dong khong.
python test_telethon.py
"""
import asyncio
from telethon import TelegramClient, events

try:
    import config as cfg
    API_ID   = cfg.TELEGRAM_API_ID
    API_HASH = cfg.TELEGRAM_API_HASH
except:
    API_ID   = int(input("API_ID: "))
    API_HASH = input("API_HASH: ")

async def main():
    client = TelegramClient("linkbot", API_ID, API_HASH)
    await client.start()
    
    me = await client.get_me()
    print("Dang nhap thanh cong:", me.first_name, "@" + (me.username or ""))
    
    # List cac dialog (nhom/kenh dang tham gia)
    print("\nCac nhom/kenh dang tham gia:")
    async for dialog in client.iter_dialogs():
        print(" -", dialog.name, "| id:", dialog.id)
    
    # Lang nghe tin nhan moi
    print("\nDang lang nghe tin nhan... (Ctrl+C de thoat)")
    
    @client.on(events.NewMessage)
    async def handler(event):
        print("Nhan tin nhan:", event.message.text[:100] if event.message.text else "(media)")
    
    await client.run_until_disconnected()

asyncio.run(main())