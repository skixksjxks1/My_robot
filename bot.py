import os
import json
import asyncio
import aiosqlite
import aiohttp
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

# ================== تنظیمات ==================
BOT_TOKEN = "8669573949:AAFWKdWp8njdHNuBLlzg__dBb9Z-N9YsiCg"
ADMIN_ID = 8669573949

# اسپانسرها
SPONSOR_CHANNEL = "@V2ray_company"
SPONSOR_CHANNEL_LINK = "https://t.me/V2ray_company"
SPONSOR_BOT = "@FaraDownloaderBot"
SUPPORT_GROUP = "https://t.me/+JArqswroP-QyMTJk"

# فایل سورس زئوس
ZEUS_SOURCE_FILE = "zeus_source.js"

# حالت‌های مکالمه
WAITING_TOKEN = 1

# ================== دیتابیس ==================
async def init_db():
    async with aiosqlite.connect("ezpanel.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                cf_token TEXT,
                cf_account_id TEXT,
                cf_email TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                worker_name TEXT,
                panel_url TEXT,
                subdomain TEXT,
                created_at TEXT
            )
        """)
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect("ezpanel.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0], "username": row[1], "cf_token": row[2],
                    "cf_account_id": row[3], "cf_email": row[4]
                }
    return None

async def save_cf_token(user_id, username, token, account_id, email):
    async with aiosqlite.connect("ezpanel.db") as db:
        await db.execute("""
            INSERT OR REPLACE INTO users (user_id, username, cf_token, cf_account_id, cf_email, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, token, account_id, email, datetime.now().isoformat()))
        await db.commit()

async def get_user_panels(user_id):
    async with aiosqlite.connect("ezpanel.db") as db:
        async with db.execute("SELECT * FROM panels WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [{"id": r[0], "worker_name": r[2], "panel_url": r[3], "subdomain": r[4]} for r in rows]

async def save_panel(user_id, worker_name, panel_url, subdomain):
    async with aiosqlite.connect("ezpanel.db") as db:
        await db.execute("""
            INSERT INTO panels (user_id, worker_name, panel_url, subdomain, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, worker_name, panel_url, subdomain, datetime.now().isoformat()))
        await db.commit()

# ================== چک عضویت ==================
async def check_membership(user_id, bot):
    try:
        member = await bot.get_chat_member(SPONSOR_CHANNEL, user_id)
        if member.status in ["left", "kicked"]:
            return False
        return True
    except Exception:
        return False

# ================== کیبوردها ==================
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🟢 ساخت پنل جدید", callback_data="create_panel")],
        [InlineKeyboardButton("🔵 مدیریت و آپدیت پنل‌ها", callback_data="manage_panels")],
        [InlineKeyboardButton("🔵 ثبت اکانت کلودفلر", callback_data="register_cf")],
        [InlineKeyboardButton("🟠 اکانت‌ها", callback_data="show_accounts")],
        [InlineKeyboardButton("🔴 پشتیبانی", url=SUPPORT_GROUP)]
    ]
    return InlineKeyboardMarkup(keyboard)

def sponsor_keyboard():
    keyboard = [
        [InlineKeyboardButton("📥 ربات دانلودر اینستاگرام رایگان", url="https://t.me/FaraDownloaderBot")],
        [InlineKeyboardButton("📚 آموزش و فروش V2ray_company | VPN", url="https://t.me/V2ray_company")],
        [InlineKeyboardButton("✅ تایید عضویت و ورود به ربات", callback_data="check_join")]
    ]
    return InlineKeyboardMarkup(keyboard)

def cf_register_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔐 ورود به حساب کلودفلر", url="https://dash.cloudflare.com/login")],
        [InlineKeyboardButton("🎫 دریافت توکن اختصاصی زئوس", url="https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys=%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22workers_kv_storage%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22d1%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%2C%7B%22key%22%3A%22workers_subdomain%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22account_analytics%22%2C%22type%22%3A%22read%22%7D%5D&accountId=*&zoneId=all&name=Zeus-Deployer-Token")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ================== Cloudflare API ==================
async def verify_cf_token(token: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.cloudflare.com/client/v4/user/tokens/verify", headers=headers) as resp:
            data = await resp.json()
            if not data.get("success"):
                return None, None, None

        async with session.get("https://api.cloudflare.com/client/v4/accounts", headers=headers) as resp:
            acc_data = await resp.json()
            if not acc_data.get("success") or not acc_data.get("result"):
                return None, None, None
            account = acc_data["result"][0]
            account_id = account["id"]
            email = account.get("name") or "Account"

        try:
            async with session.get("https://api.cloudflare.com/client/v4/user", headers=headers) as resp:
                user_data = await resp.json()
                if user_data.get("success"):
                    email = user_data["result"].get("email") or email
        except:
            pass

        return token, account_id, email

async def deploy_zeus_panel(token: str, account_id: str, worker_name: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        # ایجاد یا دریافت D1 Database
        d1_payload = {"name": f"zeus-db-{worker_name}", "primary_location_hint": "WNAM"}
        async with session.post(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database", headers=headers, json=d1_payload) as resp:
            d1_data = await resp.json()
            if not d1_data.get("success"):
                async with session.get(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database", headers=headers) as list_resp:
                    list_data = await list_resp.json()
                    db_id = None
                    for db in list_data.get("result", []):
                        if db["name"] == f"zeus-db-{worker_name}":
                            db_id = db["uuid"]
                            break
                    if not db_id:
                        raise Exception("خطا در ایجاد دیتابیس D1")
            else:
                db_id = d1_data["result"]["uuid"]

        # خواندن کد Worker
        with open(ZEUS_SOURCE_FILE, "r", encoding="utf-8") as f:
            zeus_code = f.read()

        # آپلود Worker
        metadata = {
            "main_module": "zeus.js",
            "compatibility_date": "2024-09-23",
            "compatibility_flags": ["nodejs_compat"],
            "bindings": [{"type": "d1", "name": "DB", "id": db_id}]
        }
        form = aiohttp.FormData()
        form.add_field("metadata", json.dumps(metadata), content_type="application/json")
        form.add_field("zeus.js", zeus_code, filename="zeus.js", content_type="application/javascript+module")

        async with session.put(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/{worker_name}", headers={"Authorization": f"Bearer {token}"}, data=form) as resp:
            deploy_data = await resp.json()
            if not deploy_data.get("success"):
                error_msg = deploy_data.get("errors", [{}])[0].get("message", "خطای ناشناخته")
                raise Exception(f"خطا در دیپلوی ورکر: {error_msg}")

        # فعال‌سازی subdomain routing
        try:
            async with session.post(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/{worker_name}/subdomain", headers=headers, json={"enabled": True}) as resp:
                pass
        except:
            pass

        # گرفتن subdomain
        async with session.get(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/subdomain", headers=headers) as resp:
            sub_data = await resp.json()
            subdomain = sub_data.get("result", {}).get("subdomain", "workers")

        panel_url = f"https://{worker_name}.{subdomain}.workers.dev/panel"
        return panel_url, subdomain

# ================== هندلرها ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_member = await check_membership(user.id, context.bot)

    if not is_member:
        text = (
            "⚠️ **عضویت اجباری در کانال و ربات اسپانسر**\n\n"
            "برای استفاده از ربات **حتماً** باید عضو کانال و ربات زیر باشید:\n\n"
            f"📥 ربات دانلودر اینستاگرام رایگان\n{SPONSOR_BOT}\n\n"
            f"📚 آموزش و فروش V2ray_company | VPN\n{SPONSOR_CHANNEL_LINK}\n\n"
            "بعد از عضویت روی دکمه «تایید عضویت» بزنید."
        )
        await update.message.reply_text(text, reply_markup=sponsor_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text(
        f"سلام {user.first_name} 👋\n\n"
        "به ربات **EzPanelMaker | ایزی پنل ماکر** خوش آمدید.\n"
        "با این ربات می‌توانید پنل زئوس را به صورت کاملاً اتوماتیک روی کلودفلر بسازید.",
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    is_member = await check_membership(user.id, context.bot)

    if is_member:
        await query.edit_message_text(
            f"✅ عضویت شما تایید شد!\n\nسلام {user.first_name} 👋\n"
            "به ربات **EzPanelMaker** خوش آمدید.",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.answer("❌ هنوز عضو کانال/ربات اسپانسر نشده‌اید!", show_alert=True)

async def register_cf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "☁️ **اتصال اکانت جدید کلودفلر به زئوس** ☁️\n\n"
        "⚠️ **توجه بسیار مهم:**\n"
        "برای جلوگیری از بروز خطا، لطفاً مراحل زیر را به ترتیب انجام دهید. "
        "اگر در مرورگر خود لاگین نیستید، حتماً از گام اول شروع کنید.\n\n"
        "🔹 **گام اول:**\n"
        "روی دکمه «ورید به کلودفلر» کلیک کنید و وارد حساب کاربری خود شوید.\n"
        "(پس از ورود موفق، حتماً دوباره به همینجا در تلگرام برگردید)\n\n"
        "🔹 **گام دوم:**\n"
        "حالا روی دکمه «دریافت توکن اختصاصی» کلیک کنید.\n"
        "در صفحه‌ای که باز می‌شود، به انتهای صفحه بروید و ابتدا دکمه آبی‌رنگ "
        "**Continue to summary** و سپس **Create Token** را بزنید.\n\n"
        "🔹 **گام سوم:**\n"
        "توکن تولید شده را کپی کرده و دقیقاً در همین چت ارسال کنید.\n\n"
        "👇 منتظر دریافت توکن شما هستم... (برای لغو عملیات، دکمه بازگشت را بزنید)"
    )
    await query.edit_message_text(text, reply_markup=cf_register_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return WAITING_TOKEN

async def receive_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    user = update.effective_user

    msg = await update.message.reply_text("⏳ در حال بررسی توکن...")

    verified_token, account_id, email = await verify_cf_token(token)
    if not verified_token:
        await msg.edit_text("❌ توکن نامعتبر است یا دسترسی کافی ندارد. لطفاً دوباره تلاش کنید.")
        return WAITING_TOKEN

    await save_cf_token(user.id, user.username or "", verified_token, account_id, email)
    await msg.edit_text(
        f"✅ توکن اکانت «{email}» با موفقیت تایید و ذخیره شد!",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

# ================== هندلر جدید: اکانت‌ها ==================
async def show_accounts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        async with aiosqlite.connect("ezpanel.db") as db:
            async with db.execute("SELECT user_id, cf_email FROM users") as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await query.edit_message_text(
                "❌ هیچ اکانتی در سیستم ثبت نشده است.",
                reply_markup=main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        keyboard = []
        for user_id, email in rows:
            count = 0
            async with aiosqlite.connect("ezpanel.db") as db:
                async with db.execute("SELECT COUNT(*) FROM panels WHERE user_id = ?", (user_id,)) as c:
                    count = (await c.fetchone())[0]

            keyboard.append([
                InlineKeyboardButton(f"☁️ {email} ({count} پنل)", callback_data=f"account_detail_{user_id}")
            ])

        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])

        await query.edit_message_text(
            "🧾 **لیست اکانت‌های ثبت‌شده**\n\n"
            "هر اکانت را انتخاب کنید تا تعداد پنل‌های آن را ببینید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        await query.edit_message_text(
            f"❌ خطا در بارگذاری اکانت‌ها: {str(e)}",
            reply_markup=main_menu_keyboard()
        )

async def show_account_panels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        data = query.data
        if not data.startswith("account_detail_"):
            return

        target_user_id = int(data.split("_")[-1])

        async with aiosqlite.connect("ezpanel.db") as db:
            async with db.execute("SELECT cf_email FROM users WHERE user_id = ?", (target_user_id,)) as cu:
                row = await cu.fetchone()
                if not row:
                    await query.edit_message_text("❌ اکانت یافت نشد.", reply_markup=main_menu_keyboard())
                    return
                email = row[0]

            async with db.execute("SELECT * FROM panels WHERE user_id = ?", (target_user_id,)) as cursor:
                panels = await cursor.fetchall()

        if not panels:
            text = f"✅ اکانت **{email}**\n\nهیچ پنلی ساخته نشده."
            kb = [[InlineKeyboardButton("🔙 لیست اکانت‌ها", callback_data="show_accounts")]]
        else:
            keyboard = []
            for p in panels:
                keyboard.append([
                    InlineKeyboardButton(f"🔗 {p[2]}", url=p[3])
                ])
            keyboard.append([InlineKeyboardButton("🔙 لیست اکانت‌ها", callback_data="show_accounts")])

            text = f"✅ اکانت **{email}**\n\nتعداد پنل‌ها: **{len(panels)}**\n\nلیست پنل‌های ساخته‌شده:"

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        await query.edit_message_text(
            f"❌ خطا: {str(e)}",
            reply_markup=main_menu_keyboard()
        )

# ================== هندلرهای قبلی ==================
async def create_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = await get_user(user.id)

    if not db_user or not db_user.get("cf_token"):
        await query.edit_message_text(
            "⚠️ هیچ اکانت کلودفلری یافت نشد!\n\n"
            "لطفاً ابتدا از منوی اصلی روی «☁️ ثبت اکانت کلودفلر» کلیک کنید.",
            reply_markup=main_menu_keyboard()
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"☁️ {db_user['cf_email']}", callback_data=f"deploy_{db_user['user_id']}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ]
    await query.edit_message_text(
        "🚀 **تایید استقرار پنل**\n\nبرای ساخت پنل جدید روی اکانت زیر کلیک کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def deploy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = await get_user(user.id)

    if not db_user:
        await query.edit_message_text("⚠️ اکانت یافت نشد.", reply_markup=main_menu_keyboard())
        return

    await query.edit_message_text("⏳ **در حال ساخت پنل زئوس...**\nلطفاً چند لحظه صبر کنید...")

    try:
        worker_name = f"zeus-{user.id}-{int(datetime.now().timestamp()) % 100000}"
        panel_url, subdomain = await deploy_zeus_panel(
            db_user["cf_token"],
            db_user["cf_account_id"],
            worker_name
        )
        
        await save_panel(user.id, worker_name, panel_url, subdomain)

        keyboard = [
            [InlineKeyboardButton("🔗 ورود به پنل اختصاصی", url=panel_url)],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_main")]
        ]
        await query.edit_message_text(
            f"✅ **پنل زئوس با موفقیت ساخته شد!**\n\n"
            f"👤 اکانت: `{db_user['cf_email']}`\n"
            f"🌐 آدرس پنل:\n`{panel_url}`\n\n"
            f"حالا می‌توانید وارد پنل شوید و کاربران را مدیریت کنید.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ خطا در ساخت پنل:\n`{str(e)}`",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )

async def manage_panels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    panels = await get_user_panels(user.id)

    if not panels:
        await query.edit_message_text(
            "⚠️ هیچ پنلی یافت نشد!\n\nابتدا یک پنل جدید بسازید.",
            reply_markup=main_menu_keyboard()
        )
        return

    keyboard = []
    for p in panels:
        keyboard.append([
            InlineKeyboardButton(f"🔄 آپدیت {p['worker_name']}", callback_data=f"update_{p['id']}"),
            InlineKeyboardButton(f"🔗 ورود به پنل", url=p['panel_url'])
        ])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])

    await query.edit_message_text(
        "🔵 **مدیریت پنل‌های شما**\n\nبرای آپدیت روی دکمه مربوطه بزنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "منوی اصلی:",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ================== اجرای ربات ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(register_cf_callback, pattern="^register_cf$")],
        states={WAITING_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token)]},
        fallbacks=[
            CallbackQueryHandler(back_main, pattern="^back_main$"),
            CommandHandler("cancel", cancel)
        ],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(create_panel_callback, pattern="^create_panel$"))
    app.add_handler(CallbackQueryHandler(deploy_callback, pattern="^deploy_"))
    app.add_handler(CallbackQueryHandler(manage_panels_callback, pattern="^manage_panels$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(show_accounts_callback, pattern="^show_accounts$"))
    app.add_handler(CallbackQueryHandler(show_account_panels, pattern="^account_detail_"))

    print("🤖 ربات EzPanelMaker شروع به کار کرد... (دکمه اکانت‌ها + رنگ‌های جدید)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init_db())
    main()
