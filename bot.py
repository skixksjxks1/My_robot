import json
import logging
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import telebot
from dotenv import load_dotenv
from telebot import types

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN=8669573949:AAGLHICtiGrNXJ-4SeRCwZbt3hKGgNcz5kQ", "").strip()
if not TELEGRAM_TOKEN:
    raise RuntimeError("متغیر TELEGRAM_TOKEN=8669573949:AAGLHICtiGrNXJ-4SeRCwZbt3hKGgNcz5kQ تنظیم نشده است.")

DB_PATH = os.getenv("DB_PATH", "ezpanel.sqlite3")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/sup_EzPanelMarker")
SPONSOR_URL = os.getenv("SPONSOR_URL", "https://t.me/FaraDownloaderBot")
SPONSOR_CHANNEL = os.getenv("SPONSOR_CHANNEL", "@FaraDownloaderBot")
SPONSOR_CHANNEL_2 = os.getenv("SPONSOR_CHANNEL_2", "@V2ray_company")
TOKEN_URL = (
    "https://dash.cloudflare.com/profile/api-tokens?"
    "permissionGroupKeys=%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22workers_kv_storage%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22d1%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%2C"
    "%7B%22key%22%3A%22workers_subdomain%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22account_analytics%22%2C%22type%22%3A%22read%22%7D%5D"
    "&accountId=*&zoneId=all&name=Zeus-Deployer-Token"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML", threaded=True)
db_lock = threading.Lock()
states: Dict[int, str] = {}
pending_accounts: Dict[int, List[Dict[str, str]]] = {}


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db_lock, db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS accounts (
                user_id INTEGER NOT NULL, account_id TEXT NOT NULL,
                account_name TEXT NOT NULL, email TEXT NOT NULL,
                api_token TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, account_id)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS panels (
                user_id INTEGER NOT NULL, account_id TEXT NOT NULL,
                worker_name TEXT NOT NULL, panel_url TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, account_id)
            )"""
        )


def accounts_for(user_id: int) -> List[sqlite3.Row]:
    with db() as connection:
        return connection.execute(
            "SELECT * FROM accounts WHERE user_id=? ORDER BY account_name", (user_id,)
        ).fetchall()


def cf_request(token: str, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
    response = requests.request(
        method, "https://api.cloudflare.com/client/v4" + path,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=45, **kwargs
    )
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"پاسخ نامعتبر از Cloudflare ({response.status_code})")
    if not response.ok or not data.get("success"):
        errors = data.get("errors") or [{"message": response.text[:300]}]
        raise RuntimeError("؛ ".join(str(error.get("message", error)) for error in errors))
    return data.get("result") or {}


def verify_token(token: str) -> Dict[str, str]:
    user = cf_request(token, "GET", "/user")
    accounts = cf_request(token, "GET", "/accounts?per_page=50").get("accounts", [])
    if not accounts:
        raise RuntimeError("این توکن به هیچ اکانت Cloudflare دسترسی ندارد.")
    return {
        "email": user.get("email", "نامشخص"),
        "account_id": accounts[0]["id"],
        "account_name": accounts[0].get("name", accounts[0]["id"]),
    }


def sponsor_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📢 عضویت در کانال دانلودر", url=SPONSOR_URL))
    keyboard.add(types.InlineKeyboardButton("📢 عضویت در کانال آموزش و فروش", url="https://t.me/V2ray_company"))
    keyboard.add(types.InlineKeyboardButton("✅ تأیید عضویت", callback_data="check_membership"))
    return keyboard


def is_member(user_id: int, channel: str) -> bool:
    # یک ربات Telegram محل عضویت نیست؛ لینک آن فقط اسپانسر تبلیغاتی است.
    # برای بررسی عضویت، SPONSOR_CHANNEL را به نام واقعی یک کانال تغییر دهید.
    if not channel or channel.lstrip("@").lower().endswith("bot"):
        return True
    try:
        member = bot.get_chat_member(channel, user_id)
        return member.status in ("creator", "administrator", "member")
    except Exception as error:
        logging.warning("membership check failed for %s: %s", channel, error)
        return False


def main_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(types.InlineKeyboardButton("🟢 ➕ ساخت پنل جدید", callback_data="build"))
    keyboard.add(types.InlineKeyboardButton("🔵 🔄 مدیریت و آپدیت پنل‌ها", callback_data="manage"))
    keyboard.add(types.InlineKeyboardButton("⚪ ☁️ ثبت اکانت Cloudflare", callback_data="register"))
    keyboard.add(types.InlineKeyboardButton("🔴 🛟 پشتیبانی", url=SUPPORT_URL))
    return keyboard


def back_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="home"))
    return keyboard


def show_home(chat_id: int, message_id: Optional[int] = None) -> None:
    text = "🔥 <b>EzPanelMaker | ایزی پنل ماکر</b>\n\nاز منوی زیر گزینهٔ موردنظر را انتخاب کنید:"
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=main_keyboard())
    else:
        bot.send_message(chat_id, text, reply_markup=main_keyboard())


def account_keyboard(user_id: int, action: str) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for account in accounts_for(user_id):
        keyboard.add(types.InlineKeyboardButton(
            f"☁️ {account['account_name']} ({account['email']})",
            callback_data=f"{action}:{account['account_id']}"
        ))
    keyboard.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="home"))
    return keyboard


def worker_source() -> str:
    return """const html = `<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<title>Zeus Panel</title><style>body{font-family:Tahoma;background:#101827;color:#fff;
max-width:760px;margin:50px auto;padding:24px}div{background:#1e293b;padding:24px;
border-radius:16px}h1{color:#60a5fa}code{display:block;background:#0f172a;padding:14px;
direction:ltr;text-align:left;border-radius:8px;overflow:auto}</style><div>
<h1>⚡ پنل زئوس</h1><p>پنل با موفقیت روی Cloudflare Workers فعال شد.</p>
<p>این آدرس را برای دسترسی دائمی ذخیره کنید.</p></div></html>`;
export default {async fetch(request) {
  const url = new URL(request.url);
  if (url.pathname === "/health") return new Response("ok");
  return new Response(html, {headers: {"content-type":"text/html; charset=UTF-8"}});
}};"""


def deploy(account: sqlite3.Row) -> str:
    token, account_id = account["api_token"], account["account_id"]
    worker_name = f"zeus-panel-{uuid.uuid4().hex[:10]}"
    metadata = json.dumps({"main_module": "worker.mjs", "compatibility_date": "2025-01-01"})
    response = requests.put(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/{worker_name}/content",
        headers={"Authorization": f"Bearer {token}"},
        data={"metadata": metadata},
        files={"worker.mjs": ("worker.mjs", worker_source(), "application/javascript+module")},
        timeout=60,
    )
    data = response.json()
    if not response.ok or not data.get("success"):
        raise RuntimeError(str(data.get("errors", data)))
    subdomain = cf_request(token, "GET", f"/accounts/{account_id}/workers/subdomain").get("subdomain")
    if not subdomain:
        raise RuntimeError("ساب‌دامین workers.dev این اکانت فعال نیست؛ ابتدا آن را در Cloudflare فعال کنید.")
    url = f"https://{worker_name}.{subdomain}.workers.dev/panel"
    with db_lock, db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO panels(user_id,account_id,worker_name,panel_url,updated_at)"
            " VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
            (account["user_id"], account_id, worker_name, url),
        )
    return url


@bot.message_handler(commands=["start"])
def start(message: types.Message) -> None:
    states.pop(message.from_user.id, None)
    bot.send_message(
        message.chat.id,
        "برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید و سپس روی «تأیید عضویت» بزنید.",
        reply_markup=sponsor_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery) -> None:
    user_id, chat_id = call.from_user.id, call.message.chat.id
    if call.data == "check_membership":
        if is_member(user_id, SPONSOR_CHANNEL) and is_member(user_id, SPONSOR_CHANNEL_2):
            bot.answer_callback_query(call.id, "عضویت شما تأیید شد ✅")
            show_home(chat_id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "لطفاً در هر دو کانال عضو شوید و دوباره امتحان کنید.", show_alert=True)
        return
    if call.data == "home":
        states.pop(user_id, None)
        bot.answer_callback_query(call.id)
        show_home(chat_id, call.message.message_id)
        return
    if call.data == "register":
        states[user_id] = "token"
        bot.edit_message_text(
            "☁️ <b>اتصال اکانت Cloudflare</b>\n\n"
            "۱) وارد Cloudflare شوید.\n۲) توکن اختصاصی را بسازید.\n"
            "۳) فقط خود توکن را همین‌جا ارسال کنید.\n\n"
            "⚠️ توکن را برای هیچ‌کس دیگری ارسال نکنید.",
            chat_id, call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔐 ورود به Cloudflare", url="https://dash.cloudflare.com/login"),
                types.InlineKeyboardButton("📎 دریافت توکن برای زئوس", url=TOKEN_URL),
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="home"),
            ),
        )
        return
    if call.data in ("build", "manage"):
        rows = accounts_for(user_id)
        if not rows:
            bot.answer_callback_query(call.id, "⚠️ هیچ اکانت Cloudflare ثبت نشده است.", show_alert=True)
            return
        action = "deploy" if call.data == "build" else "update"
        bot.edit_message_text(
            "🚀 <b>تأیید استقرار پنل</b>\n\nاکانت موردنظر را انتخاب کنید:",
            chat_id, call.message.message_id, reply_markup=account_keyboard(user_id, action),
        )
        return
    if call.data.startswith(("deploy:", "update:")):
        account_id = call.data.split(":", 1)[1]
        with db() as connection:
            account = connection.execute(
                "SELECT rowid, * FROM accounts WHERE user_id=? AND account_id=?", (user_id, account_id)
            ).fetchone()
        if not account:
            bot.answer_callback_query(call.id, "اکانت پیدا نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "ساخت پنل شروع شد...")
        bot.edit_message_text("⏳ در حال ساخت/آپدیت پنل زئوس؛ لطفاً چند لحظه صبر کنید...", chat_id, call.message.message_id)
        try:
            url = deploy(account)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("🚀 ورود به پنل اختصاصی", url=url))
            bot.edit_message_text(
                f"✅ <b>پنل با موفقیت آماده شد</b>\n\n"
                f"👤 اکانت: <b>{account['email']}</b>\n🔗 آدرس پنل:\n{url}",
                chat_id, call.message.message_id, reply_markup=keyboard,
            )
        except Exception as error:
            logging.exception("deployment failed")
            bot.edit_message_text(f"❌ ساخت پنل انجام نشد:\n<code>{str(error)[:800]}</code>", chat_id, call.message.message_id, reply_markup=back_keyboard())


@bot.message_handler(content_types=["text"])
def text_handler(message: types.Message) -> None:
    if states.get(message.from_user.id) != "token":
        bot.reply_to(message, "برای شروع، دستور /start را بزنید.")
        return
    token = message.text.strip()
    try:
        info = verify_token(token)
        with db_lock, db() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO accounts(user_id,account_id,account_name,email,api_token)"
                " VALUES(?,?,?,?,?)",
                (message.from_user.id, info["account_id"], info["account_name"], info["email"], token),
            )
        states.pop(message.from_user.id, None)
        bot.reply_to(message, f"✅ توکن اکانت «{info['email']}» با موفقیت تأیید و ذخیره شد.", reply_markup=main_keyboard())
    except Exception:
        logging.exception("token verification failed")
        bot.reply_to(message, "❌ توکن معتبر نیست یا دسترسی لازم را ندارد. توکن را دوباره ارسال کنید.")


if __name__ == "__main__":
    init_db()
    logging.info("EzPanelMaker started")
    bot.infinity_polling(skip_pending=True, allowed_updates=["message", "callback_query"])
