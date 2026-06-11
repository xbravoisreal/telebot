"""
Telegram Bot - Tự động lưu link vào Google Sheets
- Tự fetch tiêu đề trang web
- Tạo sub_id từ tiêu đề (slug không dấu + số random)
"""

import logging
import re
import os
import json
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters as tg_filters
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
        "/link <url> - Luu link\n"
        "/custom - Cap nhat link tu CSV\n"
        "/caption <sub_id> <list> - Tao caption\n"
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


# ── Shop Lists cố định (Option B) ────────────────────────────────────────────
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


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CommandHandler("count", count_command))
    app.add_handler(CommandHandler("custom", custom_command))
    app.add_handler(CommandHandler("caption", caption_command))
    # File anh + caption /post_fb -> post_fb_command
    # File + caption /custom -> custom_command
    app.add_handler(MessageHandler(
        tg_filters.Document.ALL & tg_filters.Caption(r"^/custom"),
        custom_command
    ))
    logger.info("Bot dang chay...")


    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
