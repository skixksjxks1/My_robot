import os
import json
import uuid
import requests
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()
bot = TeleBot(os.getenv("TELEGRAM_TOKEN"))
user_tokens = {}          # email -> {"account_id", "api_token", "worker_name"}
user_current_step = {}    # {user_id: "get_email" یا "get_token" یا "get_panel_name"}
user_panel_links = {}     # {user_id: "https://worker.dev/panel"}

# ==================== دکمه‌های کلیکی ====================
def get_main_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("➕ ساخت پنل جدید", callback_data="build_panel"), 
           InlineKeyboardButton("🔄 مدیریت و آپدیت پنل‌ها", callback_data="manage_panels"))
    return kb

def get_registration_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📌 ورود به حساب کلودفلر (لینک مستقیم)", url="https://dash.cloudflare.com/login"))
    return kb

def get_token_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📎 دریافت توکن اختصاصی برای زئوس", url="https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys=%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22workers_kv_storage%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22d1%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%2C%7B%22key%22%3A%22workers_subdomain%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22account_analytics%22%2C%22type%22%3A%22read%22%7D%5D&accountId=*&zoneId=all&name=Zeus-Deployer-Token"))
    kb.add(InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu"))
    return kb

def get_panel_keyboard(user_id):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🚀 ورود به پنل اختصاصی", url=user_panel_links[user_id]))
    kb.add(InlineKeyboardButton("📌 دریافت سورس پنل زئوس (اختیاری)", url="https://t.me/sup_EzPanelMarker"))
    return kb

def get_support_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("💬 پشتیبانی (رنگ قرمز)", url="https://t.me/sup_EzPanelMarker"))
    return kb

# ==================== هندلرها ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    if call.data == "main_menu":
        bot.edit_message_text("👋 **منوی اصلی پنل کانفینگ**\n\nلطفاً یکی از گزینه‌ها را انتخاب کنید:", 
                              call.message.chat.id, call.message.message_id, 
                              reply_markup=get_main_keyboard(), parse_mode="Markdown")
    elif call.data == "build_panel":
        if user_id not in user_tokens or not user_tokens[user_id].get("account_id"):
            bot.answer_callback_query(call.id, "⚠️ هیچ اکانت کلودفلری یافت نشد!\nلطفاً ابتدا از منوی اصلی روی «➕ ثبت اکانت کلودفلر» کلیک کنید.", show_alert=True)
            return
        user_current_step[user_id] = "build_panel"
        account = user_tokens[user_id]
        msg = f"""🚀 **تایید استقرار پنل**\n\nبرای ساخت پنل جدید روی اکانت زیر کلیک کنید:\n\n**ایمیل اکانت:** {account["email"]}\n\n**Account ID:** {account["account_id"]}"""
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ ساخت پنل زئوس (حذف خودکار)", callback_data="confirm_build"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    elif call.data == "confirm_build":
        account = user_tokens[user_id]
        msg_id = call.message.message_id
        user_id_chat = call.message.chat.id
        try:
            bot.edit_message_text("🚀 **پنل در حال ساخت...** (صبر کنید ۱۰-۲۰ ثانیه)", user_id_chat, msg_id)
            worker_name = f"zeus-panel-{uuid.uuid4().hex[:12]}"
            script_content = f'''export default {{
  async fetch(request, env, ctx) {{
    return new Response("Zeus Panel | V2ray Company", {{ status: 200 }});
  }}
}}'''
            headers = {"Authorization": f"Bearer {account['api_token']}"}
            # ایجاد Worker
            create_resp = requests.post(
                f"https://api.cloudflare.com/client/v4/accounts/{account['account_id']}/workers/scripts",
                headers=headers,
                json={"name": worker_name}
            )
            create_resp.raise_for_status()
            # آپلود اسکریپت + تنظیمات کامل
            metadata = json.dumps({
                "main_module": f"{worker_name}.mjs",
                "compatibility_date": "2025-01-01",
                "bindings": [{"type": "plain_text", "name": "ACCOUNT_ID", "text": account["account_id"]}]
            })
            files = {"worker.mjs": (f"{worker_name}.mjs", script_content, "application/javascript+module")}
            upload_resp = requests.put(
                f"https://api.cloudflare.com/client/v4/accounts/{account['account_id']}/workers/scripts/{worker_name}/content",
                headers=headers,
                data={"metadata": metadata},
                files=files
            )
            upload_resp.raise_for_status()
            # فعال‌سازی دائم
            routes_resp = requests.post(
                f"https://api.cloudflare.com/client/v4/accounts/{account['account_id']}/workers/routes",
                headers=headers,
                json={"pattern": "worker.dev/*", "script": worker_name}
            )
            routes_resp.raise_for_status()
            # لینک نهایی
            panel_link = f"https://{worker_name}.worker.dev/panel"
            user_panel_links[user_id] = panel_link
            bot.edit_message_text(f"""✅ **پنل با موفقیت ساخته شد!**\n\n**نام اکانت:** {account["email"]}\n**آدرس پنل:** {panel_link}\n\nلینک همیشه فعال است (حتی اگر اکانت/پنل حذف شود).""", 
                                  user_id_chat, msg_id, reply_markup=get_panel_keyboard(user_id), parse_mode="Markdown")
        except Exception as e:
            bot.edit_message_text(f"❌ خطا در ساخت پنل:\n{e}", user_id_chat, msg_id)

    # بقیه callbackها (manage_panels و غیره) در ادامه کد کامل هستن

@bot.message_handler(commands=['start'])
def start(msg):
    if msg.from_user.id not in user_tokens:
        user_tokens[msg.from_user.id] = {}
        user_current_step[msg.from_user.id] = "get_email"
    bot.send_message(msg.chat.id, """**🔥 EzPanelMaker | پنل کانفینگ زئوس**\n\nسلام! آماده‌ام پنل کانفینگ شما رو با یک کلیک بسازم.\n\n**اولین قدم:**\nلطفاً **ایمیل اکانت کلودفلر** خود را وارد کنید:""", reply_markup=get_support_keyboard())

@bot.message_handler(content_types=['text'])
def text_handler(msg):
    user_id = msg.from_user.id
    text = msg.text.strip()
    if user_id not in user_current_step:
        bot.reply_to(msg, "لطفاً ابتدا از منوی /start استفاده کنید.")
        return

    step = user_current_step[user_id]
    if step == "get_email":
        user_tokens[user_id]["email"] = text
        user_current_step[user_id] = "get_token"
        bot.reply_to(msg, """☁️ **اتصال اکانت جدید کلودفلر به زئوس**\n\n⚠️ مراحل را به ترتیب انجام دهید:\n\n1️⃣ روی دکمه «ورود به کلودفلر» کلیک کنید و وارد شوید.\n\n2️⃣ به انتهای صفحه بروید و روی «Continue to summary» سپس «Create Token» بزنید.\n\n3️⃣ توکن تولید شده را دقیقاً اینجا کپی کنید.""", reply_markup=get_registration_keyboard())

    elif step == "get_token":
        user_tokens[user_id]["api_token"] = text
        # گرفتن Account ID
        try:
            r = requests.get("https://api.cloudflare.com/client/v4/user/tokens/verify", 
                             headers={"Authorization": f"Bearer {text}"})
            data = r.json()
            account_id = data["result"]["id"]
            user_tokens[user_id]["account_id"] = account_id
            user_current_step[user_id] = "build_panel"
            bot.reply_to(msg, """✅ **توکن با موفقیت تایید شد!**\n\n**Account ID:** {}\n\n**آماده استفاده**""".format(account_id))
        except:
            bot.reply_to(msg, "❌ توکن نامعتبر بود. دوباره کپی کنید.")

bot.infinity_polling()
