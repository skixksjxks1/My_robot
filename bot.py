#!/usr/bin/env python3
"""
EzPanelMaker | ایزی پنل ماکر
Telegram bot for automatic deployment of Zeus Panel on Cloudflare Workers + D1
"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import aiohttp
import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest

load_dotenv()

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("8669573949:AAGLHICtiGrNXJ-4SeRCwZbt3hKGgNcz5kQ")
REQUIRED_CHANNEL = os.getenv("https://t.me/V2ray_company ", "").lstrip("@")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("7277847715", "").split(",") if x.strip().isdigit()]
ZEUS_SOURCE_URL = os.getenv(
    "ZEUS_SOURCE_URL",
    "https://raw.githubusercontent.com/panel-zeus/Z-E-U-S/main/Source.js"
)
DB_PATH = os.getenv("DB_PATH", "ezpanel.db")

if not BOT_TOKEN:ي
    raise RuntimeError("BOT_TOKEN is required")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("EzPanelMaker")

# ==================== STATES ====================
class Form(StatesGroup):
    waiting_cf_token = State()

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cf_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                email TEXT,
                token TEXT NOT NULL,
                worker_name TEXT,
                panel_url TEXT,
                d1_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, account_id)
            )
        """)
        await db.commit()

async def save_user(user_id: int, username: str = None, full_name: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name)
        )
        await db.execute(
            "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
            (username, full_name, user_id)
        )
        await db.commit()

async def get_user_accounts(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM cf_accounts WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_account_by_id(acc_id: int, user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM cf_accounts WHERE id = ? AND user_id = ?",
            (acc_id, user_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def save_cf_account(user_id: int, account_id: str, email: str, token: str,
                          worker_name: str = None, panel_url: str = None, d1_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO cf_accounts (user_id, account_id, email, token, worker_name, panel_url, d1_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, account_id) DO UPDATE SET
                email = excluded.email,
                token = excluded.token,
                worker_name = COALESCE(excluded.worker_name, worker_name),
                panel_url = COALESCE(excluded.panel_url, panel_url),
                d1_id = COALESCE(excluded.d1_id, d1_id),
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, account_id, email, token, worker_name, panel_url, d1_id))
        await db.commit()

async def update_panel_info(user_id: int, account_id: str, worker_name: str, panel_url: str, d1_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE cf_accounts SET worker_name = ?, panel_url = ?, d1_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND account_id = ?
        """, (worker_name, panel_url, d1_id, user_id, account_id))
        await db.commit()

# ==================== CLOUDFLARE CLIENT ====================
class CloudflareClient:
    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, token: str):
        self.token = token.strip()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, path: str, **kwargs) -> Dict:
        url = f"{self.BASE}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=self.headers, **kwargs) as resp:
                data = await resp.json()
                if not data.get("success", False) and resp.status >= 400:
                    errors = data.get("errors", [])
                    msg = errors[0].get("message", str(data)) if errors else str(data)
                    raise Exception(f"CF API Error ({resp.status}): {msg}")
                return data

    async def verify_token(self) -> Dict:
        return await self._request("GET", "/user/tokens/verify")

    async def get_user(self) -> Dict:
        data = await self._request("GET", "/user")
        return data.get("result", {})

    async def get_accounts(self) -> List[Dict]:
        data = await self._request("GET", "/accounts")
        return data.get("result", [])

    async def create_d1(self, account_id: str, name: str) -> Dict:
        payload = {"name": name, "primary_location_hint": "wnam"}
        data = await self._request("POST", f"/accounts/{account_id}/d1/database", json=payload)
        return data.get("result", {})

    async def list_d1(self, account_id: str) -> List[Dict]:
        data = await self._request("GET", f"/accounts/{account_id}/d1/database")
        return data.get("result", [])

    async def get_workers_subdomain(self, account_id: str) -> Optional[str]:
        try:
            data = await self._request("GET", f"/accounts/{account_id}/workers/subdomain")
            return data.get("result", {}).get("subdomain")
        except Exception:
            return None

    async def enable_workers_subdomain(self, account_id: str, subdomain: str = None) -> str:
        existing = await self.get_workers_subdomain(account_id)
        if existing:
            return existing
        import random, string
        sub = subdomain or ("zeus" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)))
        try:
            data = await self._request("PUT", f"/accounts/{account_id}/workers/subdomain", json={"subdomain": sub})
            return data.get("result", {}).get("subdomain", sub)
        except Exception:
            return existing or sub

    async def deploy_worker(self, account_id: str, script_name: str, script_content: str,
                            d1_id: str, compatibility_date: str = "2024-11-01") -> Dict:
        metadata = {
            "main_module": "index.js",
            "compatibility_date": compatibility_date,
            "bindings": [{"type": "d1", "name": "DB", "id": d1_id}]
        }

        form = aiohttp.FormData()
        form.add_field("metadata", json.dumps(metadata), content_type="application/json")
        form.add_field("index.js", script_content, filename="index.js", content_type="application/javascript+module")

        url = f"{self.BASE}/accounts/{account_id}/workers/scripts/{script_name}"
        headers = {"Authorization": f"Bearer {self.token}"}

        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, data=form) as resp:
                data = await resp.json()
                if not data.get("success", False):
                    errors = data.get("errors", [])
                    msg = errors[0].get("message", str(data)) if errors else str(data)
                    raise Exception(f"Deploy failed ({resp.status}): {msg}")
                return data.get("result", {})

    async def enable_workers_dev(self, account_id: str, script_name: str) -> bool:
        try:
            await self._request(
                "POST",
                f"/accounts/{account_id}/workers/scripts/{script_name}/subdomain",
                json={"enabled": True}
            )
            return True
        except Exception as e:
            logger.warning(f"enable_workers_dev warning: {e}")
            return False

# ==================== HELPERS ====================
async def download_zeus_source() -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(ZEUS_SOURCE_URL, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to download Zeus source: HTTP {resp.status}")
            return await resp.text()

async def check_channel_membership(bot: Bot, user_id: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(chat_id=f"@{REQUIRED_CHANNEL}", user_id=user_id)
        return member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception as e:
        logger.warning(f"Membership check failed: {e}")
        return False

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 ساخت پنل جدید", callback_data="new_panel")],
        [InlineKeyboardButton(text="⚙️ مدیریت و آپدیت پنل‌ها", callback_data="manage_panels")],
        [InlineKeyboardButton(text="➕ ثبت اکانت کلودفلر", callback_data="add_cf_account")],
    ])

def sponsor_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 ربات دانلودر اینستاگرام رایگان", url="https://t.me/FaraDownloaderBot")],
        [InlineKeyboardButton(text="🔐 آموزش و فروش V2ray_company | VPN", url="https://t.me/V2ray_company")],
        [InlineKeyboardButton(text="✅ پشتیبانی", callback_data="support")],          # رنگ قرمز
    ])

def cf_token_kb() -> InlineKeyboardMarkup:
    token_url = (
        "https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys="
        "%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C"
        "%7B%22key%22%3A%22workers_kv_storage%22%2C%22type%22%3A%22edit%22%7D%2C"
        "%7B%22key%22%3A%22d1%22%2C%22type%22%3A%22edit%22%7D%2C"
        "%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%2C"
        "%7B%22key%22%3A%22workers_subdomain%22%2C%22type%22%3A%22edit%22%7D%2C"
        "%7B%22key%22%3A%22account_analytics%22%2C%22type%22%3A%22read%22%7D%2C"
        "%7B%22key%22%3A%22user_details%22%2C%22type%22%3A%22read%22%7D%5D"
        "&accountId=*&zoneId=all&name=Zeus-Deployer-Token"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 ورود به حساب کلودفلر", url="https://dash.cloudflare.com/login")],
        [InlineKeyboardButton(text="🎫 دریافت توکن کلودفلر برای زئوس", url=token_url)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")],
    ])

def accounts_kb(accounts: List[Dict], prefix: str = "deploy") -> InlineKeyboardMarkup:
    buttons = []
    for acc in accounts:
        email = acc.get("email") or acc.get("account_id")[:8]
        label = f"☁️ {email}"
        if acc.get("panel_url"):
            label += " ✅"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"{prefix}:{acc['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== ROUTERS ====================
router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await save_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    if REQUIRED_CHANNEL:
        is_member = await check_channel_membership(bot, message.from_user.id)
        if not is_member:
            text = (
                "⚠️ <b>عضویت اجباری در کانال</b>\n\n"
                "برای استفاده از ربات <b>حتماً</b> باید در کانال زیر عضو شوید.\n"
                "بعد از عضویت روی دکمه «بررسی عضویت» بزنید.\n\n"
                "بدون عضویت امکان استفاده از ربات وجود ندارد."
            )
            await message.answer(text, reply_markup=sponsor_kb(), parse_mode=ParseMode.HTML)
            return

    text = (
        f"سلام <b>{message.from_user.first_name}</b> 👋\n\n"
        "به ربات <b>EzPanelMaker | ایزی پنل ماکر</b> خوش آمدید.\n\n"
        "با این ربات می‌تونید پنل <b>Zeus</b> رو به صورت خودکار روی اکانت کلودفلر خودتون دیپلوی کنید.\n\n"
        "از منوی زیر گزینه مورد نظر را انتخاب کنید:"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "check_join")
async def cb_check_join(callback: CallbackQuery, bot: Bot):
    is_member = await check_channel_membership(bot, callback.from_user.id)
    if is_member:
        await callback.message.edit_text(
            f"✅ عضویت شما تایید شد!\n\nسلام <b>{callback.from_user.first_name}</b>\n"
            "از منوی زیر گزینه مورد نظر را انتخاب کنید:",
            reply_markup=main_menu_kb(),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("❌ هنوز در کانال عضو نشده‌اید! لطفاً ابتدا عضو شوید.", show_alert=True)

@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "منوی اصلی:\nاز گزینه‌های زیر انتخاب کنید:",
        reply_markup=main_menu_kb()
    )

@router.callback_query(F.data == "add_cf_account")
async def cb_add_cf(callback: CallbackQuery, state: FSMContext):
    text = (
        "☁️ <b>اتصال اکانت جدید کلودفلر به زئوس</b> ☁️\n\n"
        "⚠️ <b>توجه بسیار مهم:</b>\n"
        "برای جلوگیری از بروز خطا، لطفاً مراحل زیر را به ترتیب انجام دهید. "
        "اگر در مرورگر خود لاگین نیستید، حتماً از گام اول شروع کنید.\n\n"
        "🔹 <b>گام اول:</b>\n"
        "روی دکمه «ورود به کلودفلر» کلیک کنید و وارد حساب کاربری خود شوید.\n"
        "(پس از ورود موفق، حتماً دوباره به همینجا در تلگرام برگردید)\n\n"
        "🔹 <b>گام دوم:</b>\n"
        "حالا روی دکمه «دریافت توکن اختصاصی» کلیک کنید.\n"
        "در صفحه‌ای که باز می‌شود، به انتهای صفحه بروید و ابتدا دکمه آبی‌رنگ "
        "<b>Continue to summary</b> و سپس <b>Create Token</b> را بزنید.\n\n"
        "🔹 <b>گام سوم:</b>\n"
        "توکن تولید شده را کپی کرده و دقیقاً در همین چت ارسال کنید.\n\n"
        "👇 منتظر دریافت توکن شما هستم... (برای لغو عملیات، دکمه بازگشت را بزنید)"
    )
    await state.set_state(Form.waiting_cf_token)
    await callback.message.edit_text(text, reply_markup=cf_token_kb(), parse_mode=ParseMode.HTML)

@router.message(Form.waiting_cf_token)
async def process_cf_token(message: Message, state: FSMContext):
    token = message.text.strip()
    if not re.match(r"^[A-Za-z0-9_-]{40,}$", token):
        await message.answer("❌ توکن نامعتبر به نظر می‌رسد. لطفاً توکن کامل را ارسال کنید یا روی بازگشت بزنید.")
        return

    wait_msg = await message.answer("⏳ در حال بررسی توکن...")

    try:
        cf = CloudflareClient(token)

        accounts = await cf.get_accounts()
        if not accounts:
            await wait_msg.edit_text("❌ هیچ اکانتی در این توکن یافت نشد.")
            return

        account = accounts[0]
        account_id = account["id"]
        email = account.get("name") or account_id[:12]

        try:
            user_info = await cf.get_user()
            if user_info.get("email"):
                email = user_info["email"]
        except Exception:
            pass

        await save_cf_account(
            user_id=message.from_user.id,
            account_id=account_id,
            email=email,
            token=token
        )
        await state.clear()

        await wait_msg.edit_text(
            f"✅ توکن اکانت «{email}» با موفقیت تایید و ذخیره شد!\n\n"
            f"شناسه اکانت: <code>{account_id}</code>\n\n"
            "حالا می‌توانید از منوی اصلی گزینه «ساخت پنل جدید» را انتخاب کنید.",
            reply_markup=main_menu_kb(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("Token verification failed")
        error_text = str(e)
        if "403" in error_text or "Unauthorized" in error_text:
            error_text = "دسترسی غیرمجاز (403)\n\nلطفاً توکن را دوباره با دسترسی کامل بسازید."
        await wait_msg.edit_text(f"❌ خطا در بررسی توکن:\n<code>{error_text[:350]}</code>", parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "new_panel")
async def cb_new_panel(callback: CallbackQuery):
    accounts = await get_user_accounts(callback.from_user.id)
    if not accounts:
        await callback.message.edit_text(
            "⚠️ هیچ اکانت کلودفلری یافت نشد!\n\nلطفاً ابتدا از منوی اصلی روی «➕ ثبت اکانت کلودفلر» کلیک کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ ثبت اکانت کلودفلر", callback_data="add_cf_account")],
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")]
            ])
        )
        return

    await callback.message.edit_text(
        "🚀 <b>تایید استقرار پنل</b>\n\nبرای ساخت پنل جدید روی اکانت زیر کلیک کنید:",
        reply_markup=accounts_kb(accounts, prefix="deploy"),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("deploy:"))
async def cb_deploy(callback: CallbackQuery):
    acc_id = int(callback.data.split(":")[1])
    account = await get_account_by_id(acc_id, callback.from_user.id)
    if not account:
        await callback.answer("اکانت یافت نشد", show_alert=True)
        return

    await callback.message.edit_text("⏳ <b>درحال ساخت پنل زئوس...</b>\nلطفاً چند لحظه صبر کنید.", parse_mode=ParseMode.HTML)

    try:
        cf = CloudflareClient(account["token"])
        account_id = account["account_id"]
        email = account.get("email") or "user"

        await callback.message.edit_text("📥 دانلود سورس پنل زئوس...")
        source = await download_zeus_source()

        await callback.message.edit_text("🗄️ ساخت دیتابیس D1...")
        d1_name = f"zeus-db-{callback.from_user.id}-{int(datetime.now().timestamp()) % 100000}"
        existing_d1s = await cf.list_d1(account_id)
        d1_id = None
        for d in existing_d1s:
            if d.get("name", "").startswith("zeus-db"):
                d1_id = d["uuid"]
                break
        if not d1_id:
            d1 = await cf.create_d1(account_id, d1_name)
            d1_id = d1.get("uuid")

        worker_name = f"zeus-{callback.from_user.id}-{int(datetime.now().timestamp()) % 10000}"
        worker_name = re.sub(r"[^a-z0-9-]", "", worker_name.lower())[:50]

        await callback.message.edit_text("🚀 آپلود و فعال‌سازی ورکر...")
        await cf.deploy_worker(account_id, worker_name, source, d1_id)
        await cf.enable_workers_dev(account_id, worker_name)

        subdomain = await cf.get_workers_subdomain(account_id)
        if not subdomain:
            subdomain = await cf.enable_workers_subdomain(account_id)

        panel_url = f"https://{worker_name}.{subdomain}.workers.dev/panel"

        await update_panel_info(
            callback.from_user.id, account_id,
            worker_name, panel_url, d1_id
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 ورود به پنل اختصاصی", url=panel_url)],
            [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="back_main")]
        ])

        await callback.message.edit_text(
            f"✅ <b>پنل زئوس با موفقیت ساخته شد!</b>\n\n"
            f"👤 اکانت: <code>{email}</code>\n"
            f"🔗 آدرس پنل:\n<code>{panel_url}</code>\n\n"
            f"⚠️ پس از ورود اولین بار، یک پسورد ادمین برای پنل تنظیم کنید و آن را یادداشت کنید.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("Deploy failed")
        await callback.message.edit_text(
            f"❌ خطا در ساخت پنل:\n<code>{str(e)[:400]}</code>\n\nاگر خطا مربوط به دسترسی است، مطمئن شوید توکن تمام پرمیشن‌های لازم را دارد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")]
            ]),
            parse_mode=ParseMode.HTML
        )

@router.callback_query(F.data == "manage_panels")
async def cb_manage(callback: CallbackQuery):
    accounts = await get_user_accounts(callback.from_user.id)
    if not accounts:
        await callback.message.edit_text(
            "⚠️ هیچ اکانت کلودفلری یافت نشد!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")]
            ])
        )
        return

    deployed = [a for a in accounts if a.get("panel_url")]
    if not deployed:
        await callback.message.edit_text(
            "⚠️ هنوز هیچ پنلی ساخته نشده است.\nابتدا از گزینه «ساخت پنل جدید» استفاده کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 ساخت پنل جدید", callback_data="new_panel")],
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")]
            ])
        )
        return

    await callback.message.edit_text(
        "⚙️ <b>مدیریت و آپدیت پنل‌ها</b>\n\nروی پنل مورد نظر کلیک کنید تا آپدیت شود:",
        reply_markup=accounts_kb(deployed, prefix="update"),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("update:"))
async def cb_update(callback: CallbackQuery):
    acc_id = int(callback.data.split(":")[1])
    account = await get_account_by_id(acc_id, callback.from_user.id)
    if not account or not account.get("worker_name"):
        await callback.answer("پنل یافت نشد", show_alert=True)
        return

    await callback.message.edit_text("⏳ در حال آپدیت پنل زئوس...")

    try:
        cf = CloudflareClient(account["token"])
        source = await download_zeus_source()
        d1_id = account.get("d1_id")
        if not d1_id:
            d1s = await cf.list_d1(account["account_id"])
            for d in d1s:
                if d.get("name", "").startswith("zeus"):
                    d1_id = d["uuid"]
                    break
            if not d1_id:
                raise Exception("D1 مربوط به این پنل پیدا نشد")

        await cf.deploy_worker(
            account["account_id"],
            account["worker_name"],
            source,
            d1_id
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 ورود به پنل", url=account["panel_url"])],
            [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="back_main")]
        ])
        await callback.message.edit_text(
            f"✅ پنل با موفقیت آپدیت شد!\n\n🔗 <code>{account['panel_url']}</code>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("Update failed")
        await callback.message.edit_text(
            f"❌ خطا در آپدیت:\n<code>{str(e)[:300]}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")]
            ]),
            parse_mode=ParseMode.HTML
        )

@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    try:
        await callback.bot.send_message(
            chat_id="https://t.me/+JArqswroP-QyMTJk",
            text="💬 کاربر از دکمه پشتیبانی استفاده کرد."
        )
        await callback.answer("✅ شما به گروه پشتیبانی منتقل شدید!", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ خطا: {str(e)}", show_alert=True)

# ==================== MAIN ====================
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("EzPanelMaker Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
