"""
Telegram Bot - Tự động lưu link vào Google Sheets
Đọc config từ config.py (dùng cho FPS.ms)
"""

import logging
import re
import os
import json
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Đọc config: ưu tiên env vars (Railway/Render), fallback sang config.py ────
try:
    TELEGRAM_BOT_TOKEN      = os.environ["TELEGRAM_BOT_TOKEN"]
    SPREADSHEET_ID          = os.environ["SPREADSHEET_ID"]
    WORKSHEET_NAME          = os.environ.get("WORKSHEET_NAME", "Links")
    GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]
    logger.info("Dùng config từ environment variables")
except KeyError:
    import config as cfg
    TELEGRAM_BOT_TOKEN      = cfg.TELEGRAM_BOT_TOKEN
    SPREADSHEET_ID          = cfg.SPREADSHEET_ID
    WORKSHEET_NAME          = getattr(cfg, "WORKSHEET_NAME", "Links")
    GOOGLE_CREDENTIALS_JSON = cfg.GOOGLE_CREDENTIALS_JSON
    logger.info("Dùng config từ config.py")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
URL_REGEX = re.compile(r"(https?://[^\s]+|www\.[^\s]+)", re.IGNORECASE)

# ── Google Sheets ─────────────────────────────────────────────────────────────
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    try:
        sheet = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=10)
        sheet.append_row(
            ["STT", "URL", "Mô tả", "Người gửi", "Nhóm/Chat", "Thời gian"],
            value_input_option="USER_ENTERED",
        )
    return sheet

def get_next_stt(sheet) -> int:
    records = sheet.get_all_values()
    return len([r for r in records[1:] if any(r)]) + 1

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Mình là bot lưu link.\n\n"
        "📌 Cách dùng:\n"
        "  /link <url>\n"
        "  /link <url> <mô tả>\n\n"
        "  /recent – xem 5 link mới nhất\n"
        "  /count – đếm tổng số link\n"
        "  /help – hướng dẫn"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Hướng dẫn sử dụng*\n\n"
        "`/link <url>` – Lưu link\n"
        "`/link <url> <mô tả>` – Lưu link kèm ghi chú\n"
        "`/recent` – Xem 5 link vừa lưu\n"
        "`/count` – Đếm tổng số link\n",
        parse_mode="Markdown",
    )

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user, chat = message.from_user, message.chat
    args = context.args
    if not args:
        await message.reply_text("❌ Thiếu URL!\n\nVí dụ: `/link https://example.com`", parse_mode="Markdown")
        return
    raw_url = args[0]
    if not URL_REGEX.match(raw_url):
        await message.reply_text("❌ URL không hợp lệ!", parse_mode="Markdown")
        return
    url = raw_url if raw_url.startswith("http") else f"https://{raw_url}"
    description = " ".join(args[1:]) if len(args) > 1 else ""
    sender_name = f"{user.full_name} (@{user.username})" if user.username else (user.full_name or str(user.id))
    chat_name = "Chat riêng" if chat.type == "private" else (chat.title or str(chat.id))
    timestamp = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S") + " (UTC)"
    try:
        sheet = get_sheet()
        stt = get_next_stt(sheet)
        sheet.append_row([stt, url, description, sender_name, chat_name, timestamp], value_input_option="USER_ENTERED")
        desc_line = f"\n📝 *Mô tả:* {description}" if description else ""
        await message.reply_text(
            f"✅ *Đã lưu link #{stt}!*\n🔗 {url}{desc_line}\n👤 {sender_name}\n🕐 {timestamp}",
            parse_mode="Markdown", disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Lỗi Sheets: {e}")
        await message.reply_text(f"❌ Lỗi: `{e}`", parse_mode="Markdown")

async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        data_rows = [r for r in sheet.get_all_values()[1:] if any(r)]
        if not data_rows:
            await update.message.reply_text("📭 Chưa có link nào.")
            return
        lines = ["📋 *5 link mới nhất:*\n"]
        for row in data_rows[-5:][::-1]:
            stt, url = row[0] if row else "?", row[1] if len(row)>1 else ""
            desc, sender, time_ = row[2] if len(row)>2 else "", row[3] if len(row)>3 else "", row[5] if len(row)>5 else ""
            lines.append(f"*#{stt}*{f' — _{desc}_' if desc else ''}\n🔗 {url}\n👤 {sender} | {time_}\n")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: `{e}`", parse_mode="Markdown")

async def count_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        total = len([r for r in sheet.get_all_values()[1:] if any(r)])
        await update.message.reply_text(f"📊 Tổng cộng đã lưu *{total} link*.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: `{e}`", parse_mode="Markdown")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CommandHandler("count", count_command))
    logger.info("🤖 Bot đang chạy...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
