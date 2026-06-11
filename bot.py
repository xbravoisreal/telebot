"""
Telegram Bot - Tự động lưu link vào Google Sheets
- Tự fetch tiêu đề trang web
- Tạo sub_id từ tiêu đề (slug không dấu + số random)
"""

import logging
import re
import os
import json
import random
import unicodedata
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters as tg_filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
try:
    TELEGRAM_BOT_TOKEN      = os.environ["TELEGRAM_BOT_TOKEN"]
    SPREADSHEET_ID          = os.environ["SPREADSHEET_ID"]
    WORKSHEET_NAME          = os.environ.get("WORKSHEET_NAME", "Links")
    GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]
except KeyError:
    import config as cfg
    TELEGRAM_BOT_TOKEN      = cfg.TELEGRAM_BOT_TOKEN
    SPREADSHEET_ID          = cfg.SPREADSHEET_ID
    WORKSHEET_NAME          = getattr(cfg, "WORKSHEET_NAME", "Links")
    GOOGLE_CREDENTIALS_JSON = cfg.GOOGLE_CREDENTIALS_JSON

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
URL_REGEX = re.compile(r"(https?://[^\s]+|www\.[^\s]+)", re.IGNORECASE)

def detect_type(url):
    url_lower = url.lower()
    if any(x in url_lower for x in ["shopee.vn", "shp.ee", "shopee.com"]):
        return "Shopee"
    if any(x in url_lower for x in ["tiktok.com", "vm.tiktok", "vt.tiktok"]):
        return "Tiktok"
    if any(x in url_lower for x in ["xiaohongshu.com", "xhslink.com", "red.com"]):
        return "Xiaohongshu"
    return "Khac"

# ── Title parser ──────────────────────────────────────────────────────────────
class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def fetch_title(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "identity",
    }
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=10) as resp:
            raw = resp.read(65536)
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")

        # Thử <title>
        parser = TitleParser()
        parser.feed(html)
        title = parser.title.strip()

        # Thử og:title nếu title rỗng
        if not title or title.lower().startswith("shopee"):
            m = re.search(r'property="og:title"\s+content="([^"]+)"', html)
            if not m:
                m = re.search(r'content="([^"]+)"\s+property="og:title"', html)
            if m:
                title = m.group(1).strip()

        # Cắt "| Shopee" cuối
        title = re.split(r"\s*\|\s*[Ss]hopee", title)[0].strip()
        title = re.split(r"\s*-\s*[Ss]hopee", title)[0].strip()
        logger.info("Title: %r", title)
        return title
    except Exception as e:
        logger.warning("fetch_title loi: %s", e)
        return ""


def to_sub_id(title):
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]", "", ascii_str).lower()
    slug = slug[:20]
    rand = random.randint(100, 999)
    return "%s%d" % (slug, rand)


# ── Google Sheets ─────────────────────────────────────────────────────────────
def get_sheet(retries=3):
    for attempt in range(retries):
        try:
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            try:
                sheet = spreadsheet.worksheet(WORKSHEET_NAME)
            except gspread.WorksheetNotFound:
                sheet = spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=10)
                sheet.append_row(
                    ["STT", "Sub_id", "Link", "Loai", "Nguoi gui", "Nhom/Chat", "Thoi gian"],
                    value_input_option="USER_ENTERED",
                )
            return sheet
        except Exception as e:
            if attempt < retries - 1:
                import time; time.sleep(2)
            else:
                raise e

def get_next_stt(sheet):
    records = sheet.get_all_values()
    return len([r for r in records[1:] if any(r)]) + 1


# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update, context):
    await update.message.reply_text(
        "Bot luu link\n\n"
        "/link <url> - Luu link, tu tao sub_id\n"
        "/recent - 5 link moi nhat\n"
        "/count - Tong so link\n"
        "/help - Huong dan"
    )

async def help_command(update, context):
    await update.message.reply_text(
        "/link <url> - Luu link\n"
        "/recent - 5 link moi nhat\n"
        "/count - Tong so link"
    )

async def link_command(update, context):
    message = update.message
    user, chat = message.from_user, message.chat
    args = context.args

    if not args:
        await message.reply_text("Thieu URL!\n\nVi du: /link https://vn.shp.ee/abc")
        return

    raw_url = args[0]
    if not URL_REGEX.match(raw_url):
        await message.reply_text("URL khong hop le!")
        return

    url = raw_url if raw_url.startswith("http") else "https://" + raw_url

    if user.username:
        sender_name = "%s (@%s)" % (user.full_name, user.username)
    else:
        sender_name = user.full_name or str(user.id)

    chat_name = "Chat rieng" if chat.type == "private" else (chat.title or str(chat.id))
    tz_vn = timezone(timedelta(hours=7))
    timestamp = datetime.now(tz_vn).strftime("%d/%m/%Y %H:%M:%S") + " (GMT+7)"
    loai = detect_type(url)

    try:
        sheet = get_sheet()
        stt = get_next_stt(sheet)
        sheet.append_row(
            [stt, "", url, loai, sender_name, chat_name, timestamp],
            value_input_option="USER_ENTERED",
        )
        logger.info("Luu #%d: %s", stt, url)
        await message.reply_text(
            "Da luu link #%d! [%s]\n%s\nNguoi gui: %s\n%s" % (
                stt, loai, url, sender_name, timestamp
            ),
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error("Loi Sheets: %s", e)
        await message.reply_text("Loi: %s" % e)


async def recent_command(update, context):
    try:
        sheet = get_sheet()
        data_rows = [r for r in sheet.get_all_values()[1:] if any(r)]
        if not data_rows:
            await update.message.reply_text("Chua co link nao.")
            return
        lines = ["5 link moi nhat:\n"]
        for row in data_rows[-5:][::-1]:
            stt    = row[0] if len(row) > 0 else "?"
            sub_id = row[1] if len(row) > 1 else ""
            url    = row[2] if len(row) > 2 else ""
            loai   = row[3] if len(row) > 3 else ""
            time_  = row[6] if len(row) > 6 else ""
            lines.append("#%s [%s] %s\n%s\n%s\n" % (stt, sub_id, loai, url, time_))
        await update.message.reply_text(
            "\n".join(lines), disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text("Loi: %s" % e)


async def count_command(update, context):
    try:
        sheet = get_sheet()
        total = len([r for r in sheet.get_all_values()[1:] if any(r)])
        await update.message.reply_text("Tong cong da luu %d link." % total)
    except Exception as e:
        await update.message.reply_text("Loi: %s" % e)


# ── /custom: đọc CSV và cập nhật tab newpost ─────────────────────────────────
import io
import csv as csv_module

def get_newpost_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    try:
        sheet = spreadsheet.worksheet("newpost")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="newpost", rows=1000, cols=10)
        sheet.append_row(["Subid", "Link", "Hook", "Hashtag"], value_input_option="USER_ENTERED")
    return sheet

async def custom_command(update, context):
    message = update.message

    # Kiểm tra có file đính kèm không
    if not message.document:
        await message.reply_text(
            "Dinh kem file .csv vao lenh /custom\n\n"
            "Vi du: gui file CSV kem tin nhan /custom"
        )
        return

    doc = message.document
    if not doc.file_name.endswith(".csv"):
        await message.reply_text("Chi ho tro file .csv!")
        return

    processing = await message.reply_text("Dang xu ly file CSV...")

    try:
        # Download file
        tg_file = await context.bot.get_file(doc.file_id)
        file_bytes = await tg_file.download_as_bytearray()
        text = file_bytes.decode("utf-8-sig", errors="replace")

        # Parse CSV
        reader = csv_module.DictReader(io.StringIO(text))
        rows = list(reader)

        if not rows:
            await processing.edit_text("File CSV rong!")
            return

        # Lay sheet newpost
        sheet = get_newpost_sheet()
        all_rows = sheet.get_all_values()

        # Build map: subid -> row_index (1-based, bo header)
        subid_map = {}
        for i, row in enumerate(all_rows[1:], start=2):
            if row and row[0].strip():
                subid_map[row[0].strip()] = i

        updated = 0
        added = 0
        skipped = 0

        for csv_row in rows:
            # Doc cot
            sub_id = (csv_row.get("Sub_id1") or "").strip()
            converted_link = (csv_row.get("Lien ket chuyen doi") or 
                            csv_row.get("Liên kết chuyển đổi") or "").strip()

            if not sub_id or not converted_link:
                skipped += 1
                continue

            if sub_id in subid_map:
                # Cap nhat dong hien co
                row_idx = subid_map[sub_id]
                sheet.update_cell(row_idx, 2, converted_link)
                updated += 1
            else:
                # Them dong moi
                sheet.append_row([sub_id, converted_link], value_input_option="USER_ENTERED")
                added += 1

        await processing.edit_text(
            "Hoan tat cap nhat newpost!\n"
            "Cap nhat: %d dong\n"
            "Them moi: %d dong\n"
            "Bo qua: %d dong" % (updated, added, skipped)
        )

    except Exception as e:
        logger.error("Loi /custom: %s", e)
        await processing.edit_text("Loi: %s" % e)


# ── /hook: viết hook caption bằng Gemini API → lưu vào cột Hook ─────────────
CLAUDE_SYSTEM_PROMPT = """Bạn là chuyên gia viết caption thời trang affiliate Shopee/Facebook tiếng Việt phong cách GenZ.

NHIỆM VỤ: Nhìn ảnh outfit → viết ĐÚNG 2 CÂU hook tiếng Việt.

PHONG CÁCH VIẾT:
- Tự nhiên, gần gũi như đang nói chuyện với bạn bè
- Có thể hài hước, relatable hoặc ngưỡng mộ tùy outfit
- KHÔNG dùng ngôn ngữ quảng cáo cứng nhắc ("sản phẩm chất lượng cao", "giá tốt nhất")
- KHÔNG dùng lỗi đánh máy cố ý

CẤU TRÚC BẮT BUỘC:
- Câu 1: hook gợi cảm xúc hoặc tình huống hài hước/relatable
- Câu 2: câu kết ngắn + từ GenZ ("nha", "vậy nè", "á", "chứ", "luôn á")
- PHẢI đủ 2 câu, không được viết 1 câu
- Dùng 3-5 emoji GenZ cuối câu: 🌸 ✨ 🤍 🩵 🎀 🪷 🌼 🤎 🩰 ☕ 🌊 🕶️ 💫 🫶

PHÂN LOẠI OUTFIT → GIỌNG:
- Đầm/váy hoa nhí, cardigan nhẹ → tiểu thư, dreamy, nhẹ nhàng
- Set đi cafe, phố → chill, hài hước nhẹ
- Đầm đi biển, resort → dreamy, gợi travel
- Đầm dạ tiệc/sang → tự tin, chanh sả
- Casual/streetwear → relatable, gần gũi
- Tutu/cute/kawaii → dễ thương, tiểu thư

VÍ DỤ CHUẨN:
✅ "Tiểu thư vườn hoa xuất hiện 🌸 Set này mà diện đi cafe cuối tuần thì ai cũng ngoái nhìn nha ✨🤍"
✅ "Outfit đi biển mà nhìn như đi dự tiệc hoàng gia vậy nè 🩵 Ai nói đi biển không cần mặc đẹp thì sai rồi nha ✨🌊"
✅ "Aesthetic nâu đất này đang sống rent-free trong đầu mình 🤎 Chanh sả không cần cố mà vẫn đỉnh vậy á ✨"
✅ "Tiểu thư check-in khách sạn thì phải diện thế này mới đúng vibe chứ 🩵🩰 Cute xỉu không chịu được luôn á 🎀"
✅ "Đi cafe cuối tuần mà diện cái này thì anh barista rót nhầm ly là đúng rồi nha 🪷☕ Thôi cứ mặc đẹp đã tính sau 🫶"
✅ "Nắng vàng gặp set vàng - tự nhiên thấy cả ngày đẹp hơn hẳn 🌼 Mặc đi chơi mà cứ ngỡ đi runway nha 🕶️✨"

CHỈ trả về DUY NHẤT 2 câu hook. Không giải thích gì thêm, không 'Link mua', không hashtag."""

async def _process_single_hook(context, file_id, mime_hint, sub_id):
    """Xu ly 1 anh: goi Claude API, luu vao sheet, tra ve hook."""
    import base64
    import urllib.request as urlreq
    import json as jsonlib

    try:
        claude_key = os.environ["ANTHROPIC_API_KEY"]
    except KeyError:
        import config as cfg
        claude_key = cfg.ANTHROPIC_API_KEY

    tg_file = await context.bot.get_file(file_id)
    img_bytes = await tg_file.download_as_bytearray()
    img_b64 = base64.b64encode(bytes(img_bytes)).decode("utf-8")

    # Detect mime
    if bytes(img_bytes[:8]) == b'\x89PNG\r\n\x1a\n':
        mime = "image/png"
    elif bytes(img_bytes[:3]) == b'\xff\xd8\xff':
        mime = "image/jpeg"
    elif bytes(img_bytes[:4]) == b'RIFF' and bytes(img_bytes[8:12]) == b'WEBP':
        mime = "image/webp"
    else:
        mime = mime_hint or "image/jpeg"

    payload = jsonlib.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 200,
        "system": CLAUDE_SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
                {"type": "text", "text": "Viet hook caption cho outfit trong anh nay."}
            ]
        }]
    }).encode("utf-8")

    req = urlreq.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": claude_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )

    try:
        with urlreq.urlopen(req, timeout=30) as resp:
            result = jsonlib.loads(resp.read())
            hook = result["content"][0]["text"].strip()
    except urllib.error.HTTPError as http_err:
        err_body = http_err.read().decode("utf-8", errors="replace")
        raise Exception("HTTP %d: %s" % (http_err.code, err_body))

    # Luu vao sheet newpost col C
    sheet = get_newpost_sheet()
    all_rows = sheet.get_all_values()
    row_idx = None
    for i, row in enumerate(all_rows[1:], start=2):
        if row and row[0].strip() == sub_id:
            row_idx = i
            break
    if row_idx:
        sheet.update_cell(row_idx, 3, hook)
        return hook, True
    return hook, False


async def hook_command(update, context):
    message = update.message
    files = []  # list of (file_id, mime_hint, sub_id)

    if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        doc = message.document
        filename = doc.file_name or ""
        sub_id = re.sub(r"\.[^.]+$", "", filename).strip()
        if not sub_id and context.args:
            sub_id = context.args[0].strip()
        if not sub_id:
            await message.reply_text(
                "Khong doc duoc sub_id!\n\n"
                "Doi ten file = sub_id (vi du: aocoyem3.jpg) hoac them /hook <sub_id>"
            )
            return
        files.append((doc.file_id, doc.mime_type, sub_id))

    elif message.photo:
        if not context.args:
            await message.reply_text(
                "Voi anh thuong can ghi sub_id: /hook <sub_id>\n\n"
                "Hoac gui anh DANG FILE de tu doc ten file."
            )
            return
        files.append((message.photo[-1].file_id, "image/jpeg", context.args[0].strip()))

    else:
        await message.reply_text(
            "Cach dung:\n"
            "1. Gui NHIEU FILE anh (ten file = sub_id) + caption /hook\n"
            "2. Gui 1 anh thuong + caption /hook <sub_id>\n\n"
            "Vi du ten file: aocoyem3.jpg, setvaycadigan1.png"
        )
        return

    total = len(files)
    processing = await message.reply_text("Dang xu ly %d anh... 0/%d" % (total, total))

    results = []
    for idx, (file_id, mime_hint, sub_id) in enumerate(files, 1):
        try:
            await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
            hook, saved = await _process_single_hook(context, file_id, mime_hint, sub_id)
            status = "Da luu vao sheet" if saved else "sub_id khong tim thay trong sheet"
            results.append("✅ [%s] %s\n%s" % (sub_id, status, hook))
        except Exception as e:
            results.append("❌ [%s] Loi: %s" % (sub_id, str(e)[:200]))
        # Cap nhat tien trinh
        await processing.edit_text("Dang xu ly %d anh... %d/%d" % (total, idx, total))

    await processing.edit_text(
        "Xong! %d/%d anh:\n\n%s" % (total, total, "\n\n".join(results))
    )


async def post_fb_command(update, context):
    message = update.message

    args = context.args
    if len(args) < 2:
        await message.reply_text(
            "Cach dung: gui anh kem caption /post-fb <sub_id> <gio:phut>\n\n"
            "Vi du: /post-fb setvaycadigan1 18:30"
        )
        return

    sub_id = args[0].strip()
    time_str = args[1].strip()

    # Parse gio:phut
    try:
        hh, mm = time_str.split(":")
        hh, mm = int(hh), int(mm)
        assert 0 <= hh <= 23 and 0 <= mm <= 59
    except:
        await message.reply_text("Gio khong hop le! Dung dinh dang HH:MM, vi du: 18:30")
        return

    # Tinh thoi gian hen gio (GMT+7)
    tz_vn = timezone(timedelta(hours=7))
    now_vn = datetime.now(tz_vn)
    post_time = now_vn.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if post_time <= now_vn:
        post_time += timedelta(days=1)  # Neu gio da qua -> sang hom sau

    delay_seconds = (post_time - now_vn).total_seconds()

    # Lay thong tin tu sheet newpost
    try:
        sheet = get_newpost_sheet()
        all_rows = sheet.get_all_values()
        row_data = None
        for row in all_rows[1:]:
            if row and row[0].strip() == sub_id:
                row_data = row
                break
        if not row_data:
            await message.reply_text("Khong tim thay sub_id [%s] trong sheet newpost!" % sub_id)
            return

        link  = row_data[1].strip() if len(row_data) > 1 else ""
        hook  = row_data[2].strip() if len(row_data) > 2 else ""

        if not link:
            await message.reply_text("Sub_id [%s] chua co Link trong sheet!" % sub_id)
            return
        if not hook:
            await message.reply_text("Sub_id [%s] chua co Hook! Chay /hook truoc nha." % sub_id)
            return
    except Exception as e:
        await message.reply_text("Loi doc sheet: %s" % e)
        return

    # Lay shop ngau nhien
    shops = get_random_shops(5)
    caption = build_caption(hook, link, shops)

    # Lay anh neu co
    img_bytes = None
    if message.photo:
        photo = message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        img_bytes = bytes(await tg_file.download_as_bytearray())
    elif message.document and message.document.mime_type.startswith("image/"):
        tg_file = await context.bot.get_file(message.document.file_id)
        img_bytes = bytes(await tg_file.download_as_bytearray())

    # Lay FB config
    try:
        fb_page_id    = os.environ.get("FB_PAGE_ID") or getattr(__import__("config"), "FB_PAGE_ID")
        fb_page_token = os.environ.get("FB_PAGE_TOKEN") or getattr(__import__("config"), "FB_PAGE_TOKEN")
    except:
        await message.reply_text("Chua cau hinh FB_PAGE_ID va FB_PAGE_TOKEN trong config.py!")
        return

    # Xac nhan truoc khi dat lich
    confirm_text = (
        "Xac nhan dat lich dang bai?\n\n"
        "Sub_id: %s\n"
        "Gio dang: %s (GMT+7)\n"
        "Co anh: %s\n\n"
        "--- Preview caption ---\n%s\n\n"
        "Goi /confirm-fb %s de xac nhan."
    ) % (sub_id, post_time.strftime("%d/%m/%Y %H:%M"), "Co" if img_bytes else "Khong", caption, sub_id)

    # Luu job tam thoi
    job_key = sub_id
    _scheduled_jobs[job_key] = {
        "sub_id": sub_id,
        "caption": caption,
        "img_bytes": img_bytes,
        "post_time": post_time,
        "delay_seconds": delay_seconds,
        "chat_id": message.chat_id,
        "fb_page_id": fb_page_id,
        "fb_page_token": fb_page_token,
    }

    await message.reply_text(confirm_text)


async def confirm_fb_command(update, context):
    message = update.message
    args = context.args
    if not args:
        await message.reply_text("Dung: /confirm-fb <sub_id>")
        return

    sub_id = args[0].strip()
    job = _scheduled_jobs.get(sub_id)
    if not job:
        await message.reply_text("Khong tim thay job cho [%s]. Chay /post-fb lai nha!" % sub_id)
        return

    # Dat lich dung APScheduler
    from apscheduler.triggers.date import DateTrigger

    scheduler = context.bot_data.get("scheduler")
    if not scheduler:
        await message.reply_text("Scheduler chua khoi dong! Restart bot nha.")
        return

    async def do_post():
        try:
            post_id = post_to_facebook(
                job["fb_page_id"],
                job["fb_page_token"],
                job["caption"],
                job["img_bytes"]
            )
            await context.bot.send_message(
                chat_id=job["chat_id"],
                text="Da dang bai [%s] len Facebook! Post ID: %s" % (sub_id, post_id)
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=job["chat_id"],
                text="Loi dang bai [%s]: %s" % (sub_id, e)
            )
        finally:
            _scheduled_jobs.pop(sub_id, None)

    scheduler.add_job(
        do_post,
        trigger=DateTrigger(run_date=job["post_time"]),
        id=sub_id,
        replace_existing=True
    )

    tz_vn = timezone(timedelta(hours=7))
    now_vn = datetime.now(tz_vn)
    delta = job["post_time"] - now_vn
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    mins = rem // 60

    await message.reply_text(
        "Da dat lich! Bai [%s] se duoc dang luc %s (GMT+7) - con %dh%dm nua." % (
            sub_id,
            job["post_time"].strftime("%d/%m/%Y %H:%M"),
            hours, mins
        )
    )
    del _scheduled_jobs[sub_id]


async def listjobs_command(update, context):
    scheduler = context.bot_data.get("scheduler")
    if not scheduler:
        await update.message.reply_text("Scheduler chua chay.")
        return
    jobs = scheduler.get_jobs()
    if not jobs:
        await update.message.reply_text("Khong co bai nao dang duoc dat lich.")
        return
    tz_vn = timezone(timedelta(hours=7))
    lines = ["Danh sach bai da dat lich:\n"]
    for job in jobs:
        run_time = job.next_run_time.astimezone(tz_vn).strftime("%d/%m %H:%M")
        lines.append("- [%s] luc %s" % (job.id, run_time))
    await update.message.reply_text("\n".join(lines))


async def canceljob_command(update, context):
    args = context.args
    if not args:
        await update.message.reply_text("Dung: /cancel-fb <sub_id>")
        return
    sub_id = args[0].strip()
    scheduler = context.bot_data.get("scheduler")
    try:
        scheduler.remove_job(sub_id)
        await update.message.reply_text("Da huy dat lich bai [%s]." % sub_id)
    except:
        await update.message.reply_text("Khong tim thay job [%s]." % sub_id)


# — Shop Lists cố định (Option B) ——————————————————————————————
SHOP_LISTS = {
    "list1": {
        "title": "VÀI BRAND ĐỒ SIÊU XINH MÀ MÌNH MÊ 🎀",
        "shops": [
            ("🌺 Tiin", "https://s.shopee.vn/AUr26IFUZf", "Trendy từng ngày, từ công sở đến cuối tuần-mặc lên là có điểm nhấn liền ✨"),
            ("🌺 Veos", "https://s.shopee.vn/9Kf4i9JvwS", "Sơ mi điệu đà, item nữ tính dịu dàng-mặc lên thấy nhẹ nhàng và tinh tế ngay 🎀"),
            ("🌺 Seo", "https://s.shopee.vn/9UyUuSJIbV", "Dễ phối, trẻ trung, hiện đại-style đơn giản mà vẫn đủ cuốn 🤍"),
            ("🌺 Zamy", "https://s.shopee.vn/8KmgV84GJc", "Váy áo bay bổng, form tôn dáng-chuẩn vibe nàng thơ không cần cố 🌸"),
        ]
    },
    "list2": {
        "title": "NHỮNG BRAND ĐỒ HÈ SIÊU XINH MÀ NÀNG KHÔNG NÊN BỎ QUA 🎀",
        "shops": [
            ("🌺 La.na Design", "https://s.shopee.vn/9pbLJ4I1vb", "Chất liệu chọn lọc, dáng nữ tính dịu dàng-mặc lên là tinh tế liền 🪷"),
            ("🌺 Khoai Boutique", "https://s.shopee.vn/8fPNuvMTIO", "Mẫu mới liên tục, set nào cũng nhẹ nhàng trendy-nhìn phát là muốn chốt ngay 💫"),
            ("🌺 KIDO", "https://s.shopee.vn/8pio7ELpxR", "Từ cafe hẹn hò đến đi biển du lịch-item nào cũng xinh và dễ mặc 🌴"),
            ("🌺 PT CLOSET", "https://s.shopee.vn/902EJXLCcU", "Bánh bèo hay cá tính đều có-shop 5⭐️ xứng đáng thử một lần 🌈"),
            ("🌺 JULYY", "https://s.shopee.vn/809h7hP0eK", "Dễ phối từ sáng đến tối, đi chơi đi làm hay ở nhà-nàng nào cũng cần một shop như này 🍬"),
        ]
    },
    "list3": {
        "title": "VÀI BRAND ĐỒ BIỂN & RESORT KHOE DÁNG CHO MẤY NÀNG NÈ 🌊🔥",
        "shops": [
            ("🌺 Maikaa Studio", "https://s.shopee.vn/8AT7K0ONJN", "Form tôn dáng, nữ tính-mặc đi biển hay dạo phố đều xinh như nhau 🌊"),
            ("🌺 HAN'S STORE", "https://s.shopee.vn/8KmXWJNjyQ", "Đường may chắc, cắt xẻ tinh tế-bikini này khoe dáng là hút mắt ngay 💎"),
            ("🌺 Dune Swimwear Label", "https://s.shopee.vn/8V5xicN6dT", "Họa tiết dịu nhẹ, sang chảnh-chuẩn vibe nghỉ dưỡng resort 🐚"),
            ("🌺 Beach Club", "https://s.shopee.vn/7Ku0KTRY0G", "Set đồ biển đa dạng, dễ mix-mùa hè này không lo hết ý tưởng ☀️"),
            ("🌺 TWENTI", "https://s.shopee.vn/7VDQWmQufJ", "Micro short + bikini họa tiết nổi-combo trendy cho nàng cá tính 🫧"),
            ("🌺 Dins Swimwear", "https://s.shopee.vn/7fWqj5QHKM", "Nâng dáng tự nhiên, chất liệu cao cấp-mặc lên là tự tin không cần chỉnh ảnh 🔥"),
            ("🌺 Selflove Club", "https://s.shopee.vn/7pqGvOPdzP", "Bikini 2 mặt đổi style cực nhanh, chất vải xịn-thoải mái từ sáng đến tối 🌺"),
            ("🌺 SeaArea", "https://s.shopee.vn/6feJXFU5MC", "Họa tiết mermaid nhiệt đới độc lạ-ra biển là nổi bật không cần cố 🧜‍♀️"),
        ]
    },
    "list4": {
        "title": 'LƯU NGAY LIST BRAND ĐỒ ĐI BIỂN "VẠN NGƯỜI MÊ" ✨',
        "shops": [
            ("🌺 Cutenew Official Store", "https://s.shopee.vn/6pxjjYTS1F", "Màu sắc kẹo ngọt, thiết kế vừa cute vừa gợi cảm-bikini và đồ biển ở đây giúp nàng bừng sáng mọi khung hình dưới nắng hè 🍭"),
            ("🌺 Maikaa Studio", "https://s.shopee.vn/70H9vrSogI", "Váy lụa, maxi cut-out, chiffon nhẹ thoáng-Maikaa Studio chuyên outfit đi biển vừa tôn dáng vừa mềm mại chuẩn vibe nàng thơ 🌸"),
            ("🌺 Pet by Chang", "https://s.shopee.vn/7Aaa8ASBLL", "Đầm maxi họa tiết rực, cắt xẻ táo bạo, vải bay bổng trước gió-chốt đơn một bộ là đủ ảnh triệu like cả chuyến 📸"),
            ("🌺 MINH KHUE STUDIO", "https://s.shopee.vn/60Ock1Wci8", "Váy maxi, đầm hai dây, set bay bổng-MINH KHUE STUDIO mang vibe nữ tính quyến rũ chuẩn cho những bộ ảnh hè đẹp nhất của nàng 🌺"),
            ("🌺 YNN STUDIO", "https://s.shopee.vn/6Ai2wKVzNB", "Maxi và đầm hở lưng vải tơ voan xòe nhẹ, bảng màu sang trọng-tôn dáng cực chuẩn cho ảnh resort hay dạo bước bên biển 🪷"),
            ("🌺 BeachClub", "https://s.shopee.vn/6L1T8dVM2E", "Bikini, váy maxi, crop top, jumpsuit-BeachClub chuẩn bị sẵn mọi outfit vacation ready cho nàng, khoét lưng hay trễ vai đều có đủ 🏖️"),
        ]
    },
    "list5": {
        "title": "NHỮNG BRAND STYLE TỐI GIẢN MÀ ĐẬM CHẤT RIÊNG ✨",
        "shops": [
            ("🌺 TWENTI", "https://s.shopee.vn/5q5icUm4v5", "Form rộng casual street, mix đâu cũng ổn mà nhìn vẫn ra chất 🖤"),
            ("🌺 WEIRD PUSS", "https://s.shopee.vn/60P8onlRa8", "Croptop mesh form ôm vibe Y2K Âu Mỹ-mặc vào là outfit có độ cháy liền 🔥"),
            ("🌺 ÉMILIE", "https://s.shopee.vn/6AiZ16koFB", "Vải nhẹ form rủ, càng nhìn càng thấy xinh-mặc vào vibe mềm mại ngay 🌸"),
            ("🌺 LSOUL", "https://s.shopee.vn/6L1zDPkAuE", "Corset váy statement tôn dáng chuẩn sexy chic-hyper-feminine hiện đại cực đỉnh 💗"),
            ("🌺 CRISPUS", "https://s.shopee.vn/6VLPPijXZH", "Hôm nay bánh bèo mai cool ngầu, vải mềm hay street đều có-mix đủ mood không bao giờ chán 🌟"),
        ]
    },
    "list6": {
        "title": "TOP THƯƠNG HIỆU VÁY ĐẦM NHẸ NHÀNG SANG TRỌNG 🌿",
        "shops": [
            ("🌺 Meicy Studio", "https://s.shopee.vn/60P8uHbh5e", "Đường kim mũi chỉ tỉ mỉ, tôn da tôn dáng-cầm trên tay mới biết đỉnh ntn 🌿"),
            ("🌺 Tiệm nhà mây", "https://s.shopee.vn/6AiZ6ab3kh", "Đẹp như hàng tiền triệu mà giá không phải, vải nhẹ xinh xỉu-mở ra là mê ngay 🌙"),
            ("🌺 MMUSE STORE", "https://s.shopee.vn/5fmIVfcxlc", "Váy body giá nửa brand mà form lên dáng y chang ảnh mẫu-ưng không chỗ chê 💎"),
            ("🌺 XIPI Official Store", "https://s.shopee.vn/5q5ihycKQf", "Nhẹ nhàng sang xịn như công chúa, nhiều mẫu nữ tính-mặc lên là muốn giữ hết 👑"),
            ("🌺 Ciri Clothes", "https://s.shopee.vn/5L9S73eERa", "Đồ hè set nào cũng xinh yêu, lên kệ là các nàng mê-ghé lựa là không về tay không 🌸"),
        ]
    },
}

def build_shop_list_caption(list_key):
    """Tao phan caption shop list tu SHOP_LISTS."""
    data = SHOP_LISTS.get(list_key)
    if not data:
        return None, "List \"%s\" khong ton tai! Dung list1/list2/list3/list4/list5/list6" % list_key
    lines = []
    lines.append("-----------")
    lines.append(data["title"])
    lines.append("-----------")
    for name, link, hook in data["shops"]:
        lines.append("%s: %s" % (name, link))
        lines.append(hook)
        lines.append("-----------")
    return "\n".join(lines), None


async def caption_command(update, context):
    """Lenh /caption <sub_id> <list1|list2|list3|list4|list5>"""
    message = update.message
    args = context.args

    if len(args) < 2:
        await message.reply_text(
            "Cach dung: /caption <sub_id> <list>\n\n"
            "Vi du: /caption setvaycadigan1 list1\n\n"
            "List co san: list1, list2, list3, list4, list5"
        )
        return

    sub_id   = args[0].strip()
    list_key = args[1].strip().lower()

    # Lay hook + link tu sheet newpost
    try:
        sheet = get_newpost_sheet()
        all_rows = sheet.get_all_values()
        row_data = None
        for row in all_rows[1:]:
            if row and row[0].strip() == sub_id:
                row_data = row
                break
        if not row_data:
            await message.reply_text("Khong tim thay sub_id [%s] trong sheet newpost!" % sub_id)
            return
        link = row_data[1].strip() if len(row_data) > 1 else ""
        hook = row_data[2].strip() if len(row_data) > 2 else ""
        if not link:
            await message.reply_text("[%s] chua co Link trong sheet!" % sub_id)
            return
        if not hook:
            await message.reply_text("[%s] chua co Hook! Chay /hook truoc nha." % sub_id)
            return
    except Exception as e:
        await message.reply_text("Loi doc sheet: %s" % e)
        return

    # Lay shop list
    shop_caption, err = build_shop_list_caption(list_key)
    if err:
        await message.reply_text(err)
        return

    # Ghep caption
    caption = "\n".join([
        "🌸 Link mua: %s" % link,
        hook,
        shop_caption,
    ])

    await message.reply_text(caption, disable_web_page_preview=True)


# ── Telethon: đọc webpage preview từ Telegram ────────────────────────────────
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage, WebPage, WebPageEmpty

_telethon_client = None

async def start_telethon(bot_app):
    """Khoi dong Telethon client song song voi bot."""
    global _telethon_client
    try:
        try:
            api_id   = int(os.environ.get("TELEGRAM_API_ID", "0"))
            api_hash = os.environ.get("TELEGRAM_API_HASH", "")
        except:
            import config as cfg
            api_id   = cfg.TELEGRAM_API_ID
            api_hash = cfg.TELEGRAM_API_HASH

        if not api_id or not api_hash:
            logger.warning("Telethon: Chua co API_ID/API_HASH, bo qua.")
            return

        _telethon_client = TelegramClient("linkbot", api_id, api_hash)
        await _telethon_client.start()
        me = await _telethon_client.get_me()
        logger.info("Telethon client started OK - logged in as: %s @%s", me.first_name, me.username)
        # Log tat ca dialogs
        async for dialog in _telethon_client.iter_dialogs():
            logger.info("Telethon dialog: %s (id=%s)", dialog.name, dialog.id)

        async def process_webpage(chat_id, msg_id, url):
            """Cho preview load xong roi doc title."""
            logger.info("Telethon process_webpage start: %s", url)
            for attempt in range(5):
                await asyncio.sleep(3)
                try:
                    msg = await _telethon_client.get_messages(chat_id, ids=msg_id)
                    if not msg or not msg.media:
                        continue
                    if not isinstance(msg.media, MessageMediaWebPage):
                        continue
                    webpage = msg.media.webpage
                    if not webpage or isinstance(webpage, WebPageEmpty):
                        continue
                    if not hasattr(webpage, "title") or not webpage.title:
                        continue

                    title = webpage.title.strip()
                    title = re.split(r"\s*[|\-]\s*[Ss]hopee", title)[0].strip()
                    if not title:
                        continue

                    logger.info("Telethon got title (attempt %d): %r", attempt+1, title)

                    # Cap nhat sheet Links
                    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
                    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
                    client_gs = gspread.authorize(creds)
                    spreadsheet = client_gs.open_by_key(SPREADSHEET_ID)
                    sheet = spreadsheet.worksheet("Links")
                    all_rows = sheet.get_all_values()
                    for i, row in enumerate(all_rows[1:], start=2):
                        if len(row) > 1 and row[1].strip() == url.strip():
                            sheet.update_cell(i, 5, title)
                            logger.info("Cap nhat title cho row %d: %s", i, title)
                            return
                    logger.info("Khong tim thay URL trong sheet: %s", url)
                    return
                except Exception as e:
                    logger.warning("Telethon attempt %d error: %s", attempt+1, e)
            logger.info("Telethon: Khong lay duoc title sau 5 lan thu")

        @_telethon_client.on(events.NewMessage)
        async def on_message(event):
            """Doc webpage title khi co link duoc gui."""
            msg = event.message
            if not msg or not msg.text:
                return

            text = msg.text.strip()
            if not text.startswith("/link"):
                return

            parts = text.split()
            if len(parts) < 2:
                return
            url = parts[1].strip()
            if not url.startswith("http"):
                return

            logger.info("Telethon: Nhan /link url=%s msg_id=%s", url, msg.id)
            await process_webpage(event.chat_id, msg.id, url)


        logger.info("Telethon dang lang nghe tin nhan...")
        await _telethon_client.run_until_disconnected()

    except Exception as e:
        logger.error("Telethon error: %s", e)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Khoi dong APScheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CommandHandler("count", count_command))
    app.add_handler(CommandHandler("custom", custom_command))
    app.add_handler(CommandHandler("hook", hook_command))
    app.add_handler(CommandHandler("caption", caption_command))
    app.add_handler(CommandHandler("post_fb", post_fb_command))
    app.add_handler(CommandHandler("confirm_fb", confirm_fb_command))
    app.add_handler(CommandHandler("listjobs", listjobs_command))
    app.add_handler(CommandHandler("cancel_fb", canceljob_command))
    # File anh + caption /hook -> hook_command
    app.add_handler(MessageHandler(
        (tg_filters.PHOTO | tg_filters.Document.IMAGE) & tg_filters.Caption(r"^/hook"),
        hook_command
    ))
    # File anh khong co caption bat dau bang "/" -> hook_command (tu doc ten file)
    app.add_handler(MessageHandler(
        tg_filters.Document.IMAGE & ~tg_filters.Caption(r"^/"),
        hook_command
    ))
    # File anh + caption /post_fb -> post_fb_command
    app.add_handler(MessageHandler(
        (tg_filters.PHOTO | tg_filters.Document.IMAGE) & tg_filters.Caption(r"^/post_fb"),
        post_fb_command
    ))
    # File + caption /custom -> custom_command
    app.add_handler(MessageHandler(
        tg_filters.Document.ALL & tg_filters.Caption(r"^/custom"),
        custom_command
    ))
    logger.info("Bot dang chay...")

    # Kiem tra co Telethon khong
    try:
        api_id   = int(os.environ.get("TELEGRAM_API_ID", "0"))
        api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    except:
        api_id, api_hash = 0, ""
    if not api_id or not api_hash:
        try:
            import config as cfg
            api_id   = getattr(cfg, "TELEGRAM_API_ID", 0)
            api_hash = getattr(cfg, "TELEGRAM_API_HASH", "")
        except:
            api_id, api_hash = 0, ""

    if api_id and api_hash:
        # Chay Telethon trong thread rieng, bot chay binh thuong
        import threading
        def run_telethon():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(start_telethon(app))
        t = threading.Thread(target=run_telethon, daemon=True)
        t.start()
    else:
        logger.info("Khong co Telethon API_ID/HASH, chay bot don gian.")

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
