# main.py - نسخه با ورود از طریق تلگرام
import os
import asyncio
import logging
import sqlite3
from datetime import datetime
from telethon import TelegramClient, events
from rubpy import Client as RubikaClient, filters
from rubpy.types import Update
from fastapi import FastAPI, Request
import uvicorn
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== متغیرهای محیطی =====
TELEGRAM_API_ID = 32157685
TELEGRAM_API_HASH = "be03ec981ba723f56886d9e373f9d28b"
TELEGRAM_BOT_TOKEN = "8817661980:AAGdeNs84F_Ji2Uw1pvyeyBrAnyDGAiPXWM"
RUBIKA_BOT_TOKEN = "CCCCGI0ZVGMOEHIJSMWGLCTIVYRREWOLVRXBLQCGWIDKRHXRLNIAWNCOUDIWHBVN"

# ===== دیتابیس =====
class Database:
    def __init__(self, db_path='bridge.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    rubika_auth_key TEXT,
                    rubika_phone TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pending_logins (
                    user_id TEXT,
                    phone TEXT,
                    code_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value) 
                VALUES ('rubika_bot_active', 'true')
            ''')
            conn.commit()
    
    def get_setting(self, key, default=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row[0] if row else default
    
    def set_setting(self, key, value):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
            conn.commit()
    
    def save_auth_key(self, user_id, auth_key, phone):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, rubika_auth_key, rubika_phone)
                VALUES (?, ?, ?)
            ''', (user_id, auth_key, phone))
            conn.commit()
    
    def get_auth_key(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT rubika_auth_key FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    
    def save_pending_login(self, user_id, phone, code_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO pending_logins (user_id, phone, code_id)
                VALUES (?, ?, ?)
            ''', (user_id, phone, code_id))
            conn.commit()
    
    def get_pending_login(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT phone, code_id FROM pending_logins WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return {'phone': row[0], 'code_id': row[1]} if row else None
    
    def clear_pending_login(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM pending_logins WHERE user_id = ?', (user_id,))
            conn.commit()

db = Database()

# ===== کلاینت‌ها =====
telegram_client = TelegramClient('telegram_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)
rubika_client = RubikaClient(name='rubpy_session')

# ===== FastAPI =====
app = FastAPI()

# ===== وضعیت ربات =====
def is_rubika_active():
    return db.get_setting('rubika_bot_active', 'true') == 'true'

# ===== هندلر تلگرام (برای ورود) =====
@telegram_client.on(events.NewMessage)
async def telegram_handler(event):
    try:
        msg = event.message
        if msg.out:
            return
            
        user_id = str(event.sender_id)
        text = msg.text.strip() if msg.text else ""
        
        # ===== دستور /login =====
        if text == '/login':
            await event.reply(
                "📱 **ورود به روبیکا**\n\n"
                "لطفاً شماره تلفن خود را وارد کنید:\n"
                "مثال: `09121234567`\n\n"
                "⚠️ برای لغو: /cancel"
            )
            return
        
        # ===== دریافت شماره تلفن =====
        if text and text.isdigit() and len(text) >= 10:
            # بررسی اینکه کاربر در مرحله ورود است
            pending = db.get_pending_login(user_id)
            if not pending:
                # اگر شماره وارد شد و در مرحله ورود نیستیم
                await event.reply(
                    "✅ شماره تلفن ذخیره شد!\n"
                    "در حال ارسال کد تایید..."
                )
                
                # ارسال کد تایید به روبیکا
                try:
                    result = await rubika_client.send_code(phone=text)
                    if result and hasattr(result, 'code_id'):
                        db.save_pending_login(user_id, text, result.code_id)
                        await event.reply(
                            f"✅ کد تایید به شماره {text} ارسال شد.\n\n"
                            "لطفاً کد ۵ رقمی را وارد کنید:\n"
                            "مثال: `12345`"
                        )
                    else:
                        await event.reply("❌ خطا در ارسال کد تایید. دوباره تلاش کنید.")
                except Exception as e:
                    await event.reply(f"❌ خطا: {str(e)}")
                return
        
        # ===== دریافت کد تایید =====
        if text and text.isdigit() and len(text) == 5:
            pending = db.get_pending_login(user_id)
            if pending:
                try:
                    # تایید کد
                    result = await rubika_client.verify_code(
                        phone=pending['phone'],
                        code=text,
                        code_id=pending['code_id']
                    )
                    
                    if result and hasattr(result, 'auth_key'):
                        # ذخیره auth_key در دیتابیس
                        db.save_auth_key(user_id, result.auth_key, pending['phone'])
                        db.clear_pending_login(user_id)
                        
                        await event.reply(
                            "✅ **ورود موفقیت‌آمیز!**\n\n"
                            "ربات روبیکا متصل شد.\n"
                            "حالا می‌توانید پیام‌ها را رد و بدل کنید."
                        )
                        
                        # تنظیم auth_key در کلاینت روبیکا
                        rubika_client.auth_key = result.auth_key
                    else:
                        await event.reply("❌ کد اشتباه است. دوباره تلاش کنید.")
                except Exception as e:
                    await event.reply(f"❌ خطا در تایید کد: {str(e)}")
                return
        
        # ===== دستور /cancel =====
        if text == '/cancel':
            db.clear_pending_login(user_id)
            await event.reply("❌ عملیات لغو شد.")
            return
        
        # ===== پردازش پیام‌های عادی =====
        if not is_rubika_active():
            return
        
        # بررسی اینکه آیا کاربر لاگین کرده
        auth_key = db.get_auth_key(user_id)
        if not auth_key:
            await event.reply(
                "⚠️ **شما وارد روبیکا نشده‌اید!**\n"
                "برای ورود از دستور `/login` استفاده کنید."
            )
            return
        
        # ارسال پیام به روبیکا
        chat = await event.get_chat()
        chat_title = chat.title if hasattr(chat, 'title') else chat.first_name or 'Unknown'
        
        rubika_text = f"📱 **پیام از تلگرام**\n"
        rubika_text += f"📌 {chat_title}\n"
        rubika_text += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        rubika_text += f"━━━━━━━━━━━━━━━━━━━\n"
        rubika_text += msg.text if msg.text else "[رسانه]"
        
        # ارسال با auth_key ذخیره شده
        rubika_client.auth_key = auth_key
        await rubika_client.send_message(
            chat_id=os.environ.get('RUBIKA_TARGET_CHAT', 'me'),
            text=rubika_text
        )
        
    except Exception as e:
        logger.error(f"❌ خطا در هندلر تلگرام: {e}")
        await event.reply(f"❌ خطا: {str(e)}")

# ===== هندلر روبیکا =====
@rubika_client.on_message_updates(filters.text | filters.media)
async def rubika_handler(update: Update):
    try:
        if not is_rubika_active():
            return
        
        message = update.message
        text = message.text if message.text else "[رسانه]"
        chat_id = message.chat_id
        
        # دستورات روبیکا
        if text == '/start':
            await message.reply(
                "🤖 ربات پل ارتباطی فعال است!\n\n"
                "📌 وضعیت ربات را از تلگرام مدیریت کنید."
            )
            return
        
        # ارسال به تلگرام
        telegram_text = f"📨 **پیام از روبیکا**\n"
        telegram_text += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        telegram_text += f"━━━━━━━━━━━━━━━━━━━\n"
        telegram_text += text
        
        await telegram_client.send_message(
            os.environ.get('TELEGRAM_TARGET_CHAT', 'me'),
            telegram_text
        )
        
    except Exception as e:
        logger.error(f"❌ خطا در هندلر روبیکا: {e}")

# ===== تابع اصلی =====
async def main():
    try:
        # اتصال به تلگرام
        await telegram_client.start(bot_token=TELEGRAM_BOT_TOKEN)
        logger.info("✅ تلگرام متصل شد")
        
        # اتصال به روبیکا (بدون لاگین اولیه)
        await rubika_client.start()
        logger.info("✅ روبیکا آماده است")
        
        # اجرای سرور
        config = uvicorn.Config(
            app, 
            host="0.0.0.0", 
            port=int(os.environ.get("PORT", 10000))
        )
        server = uvicorn.Server(config)
        
        await asyncio.gather(
            telegram_client.run_until_disconnected(),
            server.serve()
        )
        
    except Exception as e:
        logger.error(f"❌ خطا در راه‌اندازی: {e}")

if __name__ == '__main__':
    asyncio.run(main())
