"""
Telegram Bot - Tự động lưu link vào Google Sheets
Lệnh: /link <url> [mô tả tuỳ chọn]
Cấu hình qua biến môi trường (Railway-ready)
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

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config từ biến môi trường ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN      = os.environ["TELEGRAM_BOT_TOKEN"]
SPREADSHEET_ID          = os.environ["SPREADSHEET_ID"]
WORKSHEET_NAME          = os.environ.get("WORKSHEET_NAME", "Links")
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]  # Toàn bộ JSON dạng string

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
        logger.info(f"Đã tạo worksheet mới: {WORKSHEET_NAME}")
    return sheet

def get_next_stt(sheet) -> int:
    records = sheet.get_all_values()
    data_rows = [r for r in records[1:] if any(r)]
    return len(data_rows) + 1

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Xin chào! Mình là bot lưu link.\n\n"
        "📌 Cách dùng:\n"
        "  /link <url>\n"
        "  /link <url> <mô tả>\n\n"
        "📋 Ví dụ:\n"
        "  /link https://example.com\n"
        "  /link https://example.com Tài liệu quan trọng\n\n"
        "  /help – xem hướng dẫn\n"
        "  /recent – xem 5 link mới nhất"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Hướng dẫn sử dụng*\n\n"
        "*Lệnh chính:*\n"
        "`/link <url>` – Lưu link\n"
        "`/link <url> <mô tả>` – Lưu link kèm ghi chú\n\n"
        "*Lệnh phụ:*\n"
        "`/recent` – Xem 5 link vừa lưu\n"
        "`/count` – Đếm tổng số link đã lưu\n"
        "`/start` – Giới thiệu bot\n\n"
        "💡 Link được lưu vào Google Sheets tự động.",
        parse_mode="Markdown",
    )

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = message.from_user
    chat = message.chat
    args = context.args

    if not args:
        await message.reply_text(
            "❌ Thiếu URL!\n\nCách dùng: `/link <url> [mô tả]`",
            parse_mode="Markdown",
        )
        return

    raw_url = args[0]
    if not URL_REGEX.match(raw_url):
        await message.reply_text(
            "❌ URL không hợp lệ!\n\nURL phải bắt đầu bằng `http://`, `https://` hoặc `www.`",
            parse_mode="Markdown",
        )
        return

    url = raw_url if raw_url.startswith("http") else f"https://{raw_url}"
    description = " ".join(args[1:]) if len(args) > 1 else ""

    sender_name = user.full_name or user.username or str(user.id)
    if user.username:
        sender_name = f"{user.full_name} (@{user.username})"

    chat_name = "Chat riêng" if chat.type == "private" else (chat.title or str(chat.id))
    timestamp = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S") + " (UTC)"

    try:
        sheet = get_sheet()
        stt = get_next_stt(sheet)
        sheet.append_row(
            [stt, url, description, sender_name, chat_name, timestamp],
            value_input_option="USER_ENTERED",
        )
        logger.info(f"Đã lưu link #{stt}: {url}")
        desc_line = f"\n📝 *Mô tả:* {description}" if description else ""
        await message.reply_text(
            f"✅ *Đã lưu link #{stt}!*\n🔗 {url}{desc_line}\n👤 *Người gửi:* {sender_name}\n🕐 {timestamp}",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Lỗi khi lưu vào Google Sheets: {e}")
        await message.reply_text(f"❌ Có lỗi khi lưu link!\nChi tiết: `{e}`", parse_mode="Markdown")

async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        data_rows = [r for r in all_rows[1:] if any(r)]
        if not data_rows:
            await update.message.reply_text("📭 Chưa có link nào được lưu.")
            return
        last_5 = data_rows[-5:][::-1]
        lines = ["📋 *5 link mới nhất:*\n"]
        for row in last_5:
            stt   = row[0] if len(row) > 0 else "?"
            url   = row[1] if len(row) > 1 else ""
            desc  = row[2] if len(row) > 2 else ""
            sender= row[3] if len(row) > 3 else ""
            time_ = row[5] if len(row) > 5 else ""
            desc_part = f" — _{desc}_" if desc else ""
            lines.append(f"*#{stt}*{desc_part}\n🔗 {url}\n👤 {sender} | {time_}\n")
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: `{e}`", parse_mode="Markdown")

async def count_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        total = len([r for r in all_rows[1:] if any(r)])
        await update.message.reply_text(f"📊 Tổng cộng đã lưu *{total} link*.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: `{e}`", parse_mode="Markdown")

# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
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
