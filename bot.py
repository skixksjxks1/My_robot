#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EzPanelMaker Bot - ربات ساخت پنل کانفیگ زئوس
@EzPanelMakerBot
"""

import os
import json
import logging
import asyncio
import random
import string
import aiohttp
import aiosqlite
from datetime import datetime
from typing import Optional, Dict, Any, List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ================== CONFIG ==================
BOT_TOKEN = "cfut_BvUtaxczzJuZ7oJ9lte27kzxfT0NjfW7jB7hRUcXf2885768"
CHANNEL_USERNAME = "V2ray_company"  # کانال اجباری برای عضویت
CHANNEL_LINK = "https://t.me/V2ray_company"
SPONSOR_DOWNLOADER = "https://t.me/FaraDownloaderBot"
SPONSOR_V2RAY = "https://t.me/V2ray_company"

DB_PATH = "ezpanel.db"
GITHUB_ZEUS_URL = "https://raw.githubusercontent.com/IR-NETLIFY/zeus/refs/heads/main/zeus.js"

# Cloudflare API
CF_API = "https://api.cloudflare.com/client/v4"

# States
WAITING_TOKEN = 1

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== DATABASE ==================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                cf_token TEXT,
                account_id TEXT,
                account_name TEXT,
                email TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                worker_name TEXT,
                panel_url TEXT,
                db_name TEXT,
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()


async def get_user(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def save_token(user_id: int, token: str, account_id: str, account_name: str, email: str = ""):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, cf_token, account_id, account_name, email, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                cf_token = excluded.cf_token,
                account_id = excluded.account_id,
                account_name = excluded.account_name,
                email = excluded.email,
                updated_at = excluded.updated_at
        """, (user_id, token, account_id, account_name, email, now, now))
        await db.commit()


async def save_panel(user_id: int, worker_name: str, panel_url: str, db_name: str = ""):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO panels (user_id, worker_name, panel_url, db_name, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, worker_name, panel_url, db_name, now))
        await db.commit()


async def get_user_panels(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM panels WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ================== CLOUDFLARE HELPERS ==================
async def cf_request(method: str, endpoint: str, token: str, json_data: dict = None, form_data=None):
    headers = {"Authorization": f"Bearer {token}"}
    if json_data is not None:
        headers["Content-Type"] = "application/json"
    url = f"{CF_API}{endpoint}"
    async with aiohttp.ClientSession() as session:
        if form_data is not None:
            async with session.request(method, url, headers={"Authorization": f"Bearer {token}"}, data=form_data) as resp:
                try:
                    data = await resp.json()
                except:
                    text = await resp.text()
                    return {"success": False, "errors": [{"message": text}]}
                return data
        else:
            async with session.request(method, url, headers=headers, json=json_data) as resp:
                try:
                    data = await resp.json()
                except:
                    text = await resp.text()
                    return {"success": False, "errors": [{"message": text}]}
                return data


async def get_cf_account(token: str) -> Dict:
    data = await cf_request("GET", "/accounts", token)
    if not data.get("success") or not data.get("result"):
        raise Exception("توکن نامعتبر است یا دسترسی کافی ندارد. فقط از دکمه «دریافت توکن اختصاصی» استفاده کنید.")
    acc = data["result"][0]
    return {
        "id": acc["id"],
        "name": acc.get("name", "Unknown"),
    }


async def get_cf_user_email(token: str) -> str:
    data = await cf_request("GET", "/user", token)
    if data.get("success") and data.get("result"):
        return data["result"].get("email", "")
    return ""


async def get_or_create_subdomain(token: str, account_id: str) -> str:
    data = await cf_request("GET", f"/accounts/{account_id}/workers/subdomain", token)
    if data.get("success") and data.get("result") and data["result"].get("subdomain"):
        return data["result"]["subdomain"]
    # create new
    new_sub = "zeus-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    create = await cf_request("PUT", f"/accounts/{account_id}/workers/subdomain", token, {"subdomain": new_sub})
    if not create.get("success"):
        err = create.get("errors", [{}])[0].get("message", "خطای نامشخص")
        raise Exception(f"خطا در ایجاد ساب‌دامین: {err}")
    return new_sub


async def create_d1(token: str, account_id: str, db_name: str) -> str:
    data = await cf_request("POST", f"/accounts/{account_id}/d1/database", token, {"name": db_name})
    if not data.get("success"):
        err = data.get("errors", [{}])[0].get("message", "خطای نامشخص")
        raise Exception(f"خطا در ایجاد دیتابیس: {err}")
    return data["result"]["uuid"]


async def deploy_worker(token: str, account_id: str, worker_name: str, db_uuid: str, zeus_code: str) -> bool:
    metadata = {
        "main_module": "zeus.js",
        "compatibility_date": "2024-02-08",
        "bindings": [
            {"type": "d1", "name": "DB", "id": db_uuid},
            {"type": "secret_text", "name": "CF_API_TOKEN", "text": token},
            {"type": "secret_text", "name": "CF_ACCOUNT_ID", "text": account_id},
        ],
    }

    form = aiohttp.FormData()
    form.add_field(
        "metadata",
        json.dumps(metadata),
        content_type="application/json",
    )
    form.add_field(
        "zeus.js",
        zeus_code,
        filename="zeus.js",
        content_type="application/javascript+module",
    )

    url = f"{CF_API}/accounts/{account_id}/workers/scripts/{worker_name}"
    headers = {"Authorization": f"Bearer {token}"}

    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, data=form) as resp:
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                raise Exception(f"خطا در دیپلوی: {text[:300]}")
            if not data.get("success"):
                err = data.get("errors", [{}])[0].get("message", "خطای نامشخص")
                raise Exception(f"خطا در دیپلوی ورکر: {err}")
            return True


async def enable_subdomain_route(token: str, account_id: str, worker_name: str):
    data = await cf_request(
        "POST",
        f"/accounts/{account_id}/workers/scripts/{worker_name}/subdomain",
        token,
        {"enabled": True},
    )
    if not data.get("success") and data.get("errors"):
        # sometimes already enabled
        pass


async def list_workers(token: str, account_id: str) -> List[str]:
    data = await cf_request("GET", f"/accounts/{account_id}/workers/scripts", token)
    if not data.get("success"):
        return []
    return [s["id"] for s in data.get("result", []) if s.get("id", "").startswith("zeus-panel-")]


async def update_worker(token: str, account_id: str, worker_name: str, zeus_code: str) -> bool:
    # Get existing bindings
    bind_data = await cf_request("GET", f"/accounts/{account_id}/workers/scripts/{worker_name}/bindings", token)
    if not bind_data.get("success"):
        raise Exception("نتوانست بایندینگ‌ها را دریافت کند")

    new_bindings = []
    for b in bind_data.get("result", []):
        if b.get("type") == "d1":
            new_bindings.append({
                "type": "d1",
                "name": b.get("name", "DB"),
                "id": b.get("database_id") or b.get("id"),
            })
        elif b.get("name") == "CF_API_TOKEN":
            new_bindings.append({"type": "secret_text", "name": "CF_API_TOKEN", "text": token})
        elif b.get("name") == "CF_ACCOUNT_ID":
            new_bindings.append({"type": "secret_text", "name": "CF_ACCOUNT_ID", "text": account_id})
        elif b.get("type") == "secret_text":
            new_bindings.append({"type": "secret_text", "name": b["name"], "text": b.get("text", "")})

    names = {b["name"] for b in new_bindings}
    if "CF_API_TOKEN" not in names:
        new_bindings.append({"type": "secret_text", "name": "CF_API_TOKEN", "text": token})
    if "CF_ACCOUNT_ID" not in names:
        new_bindings.append({"type": "secret_text", "name": "CF_ACCOUNT_ID", "text": account_id})

    metadata = {
        "main_module": "zeus.js",
        "compatibility_date": "2024-02-08",
        "bindings": new_bindings,
    }

    form = aiohttp.FormData()
    form.add_field("metadata", json.dumps(metadata), content_type="application/json")
    form.add_field(
        "zeus.js",
        zeus_code,
        filename="zeus.js",
        content_type="application/javascript+module",
    )

    url = f"{CF_API}/accounts/{account_id}/workers/scripts/{worker_name}"
    headers = {"Authorization": f"Bearer {token}"}

    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, data=form) as resp:
            data = await resp.json()
            if not data.get("success"):
                err = data.get("errors", [{}])[0].get("message", "خطای نامشخص")
                raise Exception(f"خطا در آپدیت: {err}")
            return True


async def fetch_zeus_code() -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_ZEUS_URL + f"?t={int(datetime.utcnow().timestamp())}") as resp:
            if resp.status != 200:
                raise Exception("خطا در دریافت سورس پنل از گیت‌هاب")
            return await resp.text()


# ================== KEYBOARDS ==================
def sponsor_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 ربات دانلودر اینستاگرام رایگان", url=SPONSOR_DOWNLOADER)],
        [InlineKeyboardButton("📚 آموزش و فروش V2ray | VPN", url=SPONSOR_V2RAY)],
        [InlineKeyboardButton("✅ عضویت در کانال (الزامی)", url=CHANNEL_LINK)],
        [InlineKeyboardButton("🔄 بررسی عضویت و ادامه", callback_data="check_join")],
    ])


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ساخت پنل جدید", callback_data="new_panel")],
        [InlineKeyboardButton("🔧 مدیریت و آپدیت پنل‌ها", callback_data="manage_panels")],
        [InlineKeyboardButton("➕ ثبت اکانت کلودفلر", callback_data="register_cf")],
    ])


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")],
    ])


def cf_register_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 ورود به حساب کلودفلر", url="https://dash.cloudflare.com/login")],
        [InlineKeyboardButton(
            "🎫 دریافت توکن اختصاصی برای زئوس",
            url="https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys=%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22workers_kv_storage%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22d1%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%2C%7B%22key%22%3A%22workers_subdomain%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22account_analytics%22%2C%22type%22%3A%22read%22%7D%5D&accountId=*&zoneId=all&name=Zeus-Deployer-Token"
        )],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ])


# ================== CHECK JOIN ==================
async def is_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=f"@{CHANNEL_USERNAME}", user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramError as e:
        logger.warning(f"Cannot check membership: {e}")
        # If bot is not admin in channel, we cannot check. For production, bot MUST be admin.
        return False


# ================== HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"سلام {user.first_name} عزیز 👋\n\n"
        "⚡ به ربات <b>EzPanelMaker | ایزی پنل ماکر</b> خوش آمدید!\n\n"
        "این ربات برای ساخت و مدیریت پنل کانفیگ <b>زئوس (Zeus Panel)</b> روی کلودفلر ساخته شده است.\n\n"
        "⚠️ <b>قبل از استفاده حتماً در کانال اسپانسر عضو شوید:</b>"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=sponsor_keyboard(),
        disable_web_page_preview=True,
    )


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await is_member(user_id, context):
        await query.edit_message_text(
            "❌ <b>شما هنوز عضو کانال نشده‌اید!</b>\n\n"
            "لطفاً روی دکمه «عضویت در کانال (الزامی)» کلیک کنید و بعد از عضویت، "
            "دکمه «بررسی عضویت و ادامه» را بزنید.\n\n"
            "این کار برای حمایت از سازنده و ادامه فعالیت ربات ضروری است.",
            parse_mode=ParseMode.HTML,
            reply_markup=sponsor_keyboard(),
        )
        return

    await query.edit_message_text(
        "✅ عضویت شما تایید شد!\n\n"
        "از گزینه‌های زیر جهت ساخت یا مدیریت پنل‌های خود استفاده کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await is_member(user_id, context):
        await query.edit_message_text(
            "❌ عضویت شما منقضی شده یا لغو شده است.\nلطفاً دوباره عضو کانال شوید.",
            reply_markup=sponsor_keyboard(),
        )
        return

    await query.edit_message_text(
        "از گزینه‌های زیر جهت ساخت یا مدیریت پنل‌های خود استفاده کنید:",
        reply_markup=main_menu_keyboard(),
    )


async def register_cf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await is_member(user_id, context):
        await query.edit_message_text("❌ ابتدا در کانال عضو شوید.", reply_markup=sponsor_keyboard())
        return

    text = (
        "☁️ <b>اتصال اکانت جدید کلودفلر به زئوس</b> ☁️\n\n"
        "⚠️ <b>توجه بسیار مهم:</b>\n"
        "برای جلوگیری از بروز خطا، لطفاً مراحل زیر را به ترتیب انجام دهید. "
        "اگر در مرورگر خود لاگین نیستید، حتماً از گام اول شروع کنید.\n\n"
        "🔹 <b>گام اول:</b>\n"
        "روی دکمه «ورود به حساب کلودفلر» کلیک کنید و وارد حساب کاربری خود شوید.\n"
        "(پس از ورود موفق، حتماً دوباره به همینجا در تلگرام برگردید)\n\n"
        "🔹 <b>گام دوم:</b>\n"
        "حالا روی دکمه «دریافت توکن اختصاصی» کلیک کنید.\n"
        "در صفحه‌ای که باز می‌شود، به انتهای صفحه بروید و ابتدا دکمه آبی‌رنگ "
        "<b>Continue to summary</b> و سپس <b>Create Token</b> را بزنید.\n\n"
        "🔹 <b>گام سوم:</b>\n"
        "توکن تولید شده را کپی کرده و دقیقاً در همین چت ارسال کنید.\n\n"
        "👇 منتظر دریافت توکن شما هستم... (برای لغو عملیات، دکمه بازگشت را بزنید)"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=cf_register_keyboard(),
        disable_web_page_preview=True,
    )
    context.user_data["state"] = WAITING_TOKEN


async def handle_token_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_TOKEN:
        return

    user_id = update.effective_user.id
    token = update.message.text.strip()

    if not token or len(token) < 30:
        await update.message.reply_text(
            "❌ توکن نامعتبر به نظر می‌رسد. لطفاً توکن کامل را ارسال کنید یا دکمه بازگشت را بزنید.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    wait_msg = await update.message.reply_text("⏳ در حال بررسی و تایید توکن...")

    try:
        acc = await get_cf_account(token)
        email = await get_cf_user_email(token)
        display_name = email or acc["name"] or "Account"

        await save_token(user_id, token, acc["id"], acc["name"], email)

        context.user_data.pop("state", None)

        await wait_msg.edit_text(
            f"✅ توکن اکانت «{display_name}» با موفقیت تایید و ذخیره شد!",
            reply_markup=main_menu_keyboard(),
        )
    except Exception as e:
        logger.exception("Token validation failed")
        await wait_msg.edit_text(
            f"❌ خطا در تایید توکن:\n<code>{str(e)}</code>\n\n"
            "لطفاً مطمئن شوید از دکمه «دریافت توکن اختصاصی برای زئوس» استفاده کرده‌اید.",
            parse_mode=ParseMode.HTML,
            reply_markup=cf_register_keyboard(),
        )


async def new_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await is_member(user_id, context):
        await query.edit_message_text("❌ ابتدا در کانال عضو شوید.", reply_markup=sponsor_keyboard())
        return

    user = await get_user(user_id)
    if not user or not user.get("cf_token"):
        await query.edit_message_text(
            "⚠️ هیچ اکانت کلودفلری یافت نشد!\n"
            "لطفاً ابتدا از منوی اصلی روی «➕ ثبت اکانت کلودفلر» کلیک کنید.",
            reply_markup=main_menu_keyboard(),
        )
        return

    display = user.get("email") or user.get("account_name") or "اکانت شما"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"☁️ {display}", callback_data=f"deploy:{user['account_id']}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ])

    await query.edit_message_text(
        "🚀 <b>تایید استقرار پنل</b>\n\n"
        "برای ساخت پنل جدید روی اکانت زیر کلیک کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def deploy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    user = await get_user(user_id)
    if not user or not user.get("cf_token"):
        await query.edit_message_text(
            "⚠️ هیچ اکانت کلودفلری یافت نشد!",
            reply_markup=main_menu_keyboard(),
        )
        return

    await query.edit_message_text(
        "⏳ <b>درحال ساخت پنل زئوس...</b>\n\n"
        "لطفاً چند لحظه صبر کنید. این عملیات ممکن است ۳۰ تا ۶۰ ثانیه طول بکشد.",
        parse_mode=ParseMode.HTML,
    )

    token = user["cf_token"]
    account_id = user["account_id"]
    display = user.get("email") or user.get("account_name") or "اکانت شما"

    try:
        # 1. subdomain
        dev_sub = await get_or_create_subdomain(token, account_id)

        # 2. unique names
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        worker_name = f"zeus-panel-{suffix}"
        db_name = f"zeus-db-{suffix}"

        # 3. create D1
        db_uuid = await create_d1(token, account_id, db_name)
        await asyncio.sleep(1.5)

        # 4. fetch code
        zeus_code = await fetch_zeus_code()

        # 5. deploy
        await deploy_worker(token, account_id, worker_name, db_uuid, zeus_code)

        # 6. enable route
        await enable_subdomain_route(token, account_id, worker_name)

        panel_url = f"https://{worker_name}.{dev_sub}.workers.dev/panel"

        # save
        await save_panel(user_id, worker_name, panel_url, db_name)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 ورود به پنل اختصاصی", url=panel_url)],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")],
        ])

        await query.edit_message_text(
            f"✅ <b>پنل زئوس با موفقیت ساخته شد!</b>\n\n"
            f"👤 اکانت: <code>{display}</code>\n"
            f"🔗 آدرس پنل:\n<code>{panel_url}</code>\n\n"
            f"از دکمه زیر برای ورود به پنل استفاده کنید.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception("Deploy failed")
        await query.edit_message_text(
            f"❌ <b>خطا در ساخت پنل:</b>\n<code>{str(e)}</code>\n\n"
            "اگر خطای مربوط به Terms of Service دیدید، ابتدا در داشبورد کلودفلر "
            "توافق‌نامه Workers را بپذیرید.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )


async def manage_panels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await is_member(user_id, context):
        await query.edit_message_text("❌ ابتدا در کانال عضو شوید.", reply_markup=sponsor_keyboard())
        return

    user = await get_user(user_id)
    if not user or not user.get("cf_token"):
        await query.edit_message_text(
            "⚠️ هیچ اکانت کلودفلری یافت نشد!",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Try live list + local
    try:
        workers = await list_workers(user["cf_token"], user["account_id"])
    except Exception:
        workers = []

    panels = await get_user_panels(user_id)

    if not workers and not panels:
        await query.edit_message_text(
            "⚠️ هیچ پنلی یافت نشد!\nابتدا یک پنل جدید بسازید.",
            reply_markup=main_menu_keyboard(),
        )
        return

    buttons = []
    # Prefer live workers
    seen = set()
    for w in workers:
        seen.add(w)
        buttons.append([InlineKeyboardButton(f"🔄 آپدیت پنل: {w}", callback_data=f"update:{w}")])

    for p in panels:
        wn = p["worker_name"]
        if wn not in seen:
            buttons.append([InlineKeyboardButton(f"🔄 آپدیت پنل: {wn}", callback_data=f"update:{wn}")])
            if p.get("panel_url"):
                buttons.append([InlineKeyboardButton(f"🔗 باز کردن: {wn}", url=p["panel_url"])])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    await query.edit_message_text(
        "🔧 <b>مدیریت و آپدیت پنل‌ها</b>\n\n"
        "روی دکمه آپدیت هر پنل کلیک کنید تا به آخرین نسخه زئوس به‌روزرسانی شود:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def update_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    worker_name = query.data.split(":", 1)[1]
    user = await get_user(user_id)
    if not user:
        await query.edit_message_text("⚠️ اکانت یافت نشد.", reply_markup=main_menu_keyboard())
        return

    await query.edit_message_text(
        f"⏳ در حال آپدیت پنل <code>{worker_name}</code>...\nلطفاً صبر کنید.",
        parse_mode=ParseMode.HTML,
    )

    try:
        zeus_code = await fetch_zeus_code()
        await update_worker(user["cf_token"], user["account_id"], worker_name, zeus_code)

        # try get url
        try:
            sub = await get_or_create_subdomain(user["cf_token"], user["account_id"])
            panel_url = f"https://{worker_name}.{sub}.workers.dev/panel"
        except:
            panel_url = None

        kb_buttons = []
        if panel_url:
            kb_buttons.append([InlineKeyboardButton("🔗 ورود به پنل", url=panel_url)])
        kb_buttons.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")])

        await query.edit_message_text(
            f"✅ پنل <code>{worker_name}</code> با موفقیت به آخرین نسخه آپدیت شد!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb_buttons),
        )
    except Exception as e:
        logger.exception("Update failed")
        await query.edit_message_text(
            f"❌ خطا در آپدیت:\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    if update.message:
        await update.message.reply_text("عملیات لغو شد.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)


# ================== MAIN ==================
def main():
    asyncio.get_event_loop().run_until_complete(init_db())

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(register_cf_callback, pattern="^register_cf$"))
    app.add_handler(CallbackQueryHandler(new_panel_callback, pattern="^new_panel$"))
    app.add_handler(CallbackQueryHandler(deploy_callback, pattern="^deploy:"))
    app.add_handler(CallbackQueryHandler(manage_panels_callback, pattern="^manage_panels$"))
    app.add_handler(CallbackQueryHandler(update_panel_callback, pattern="^update:"))

    # Token messages (only when waiting)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_token_message))

    app.add_error_handler(error_handler)

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
