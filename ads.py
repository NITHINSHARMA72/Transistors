import asyncio
import os
import aiohttp
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from supabase import create_client, Client

# === MASTER BOT CONFIGURATION ===
MASTER_BOT_TOKEN = os.environ.get("BOT_TOKEN", "8974578362:AAGkxilL38ACa8apUVDIkiNj8Cy9WDi2ifw")
MASTER_API_ID = int(os.environ.get("API_ID", "28575262"))
MASTER_API_HASH = os.environ.get("API_HASH", "c5a58ab3f52e1796e91f281b707a46d8")

# === SUPABASE CONFIGURATION ===
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hhelxewgwuqcloofyeyw.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhoZWx4ZXdnd3VxY2xvb2Z5ZXl3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NzIyNTUsImV4cCI6MjA5NTA0ODI1NX0.EL0wb1HKvT9lJLtMW7p-y0X3fwgC1LeFrts7ErHVD54")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Global bot instance variable
bot = None

# In-memory runtime maps
USER_DATA = {}          
ACTIVE_TASKS = {}       

# --- DATABASE HELPERS ---
def db_get_user(user_id: int):
    try:
        res = supabase.table("user_sessions").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print(f"DB Error (Get): {e}")
    return None

def db_save_user(user_id: int, data: dict):
    try:
        data["user_id"] = user_id
        supabase.table("user_sessions").upsert(data).execute()
    except Exception as e:
        print(f"DB Error (Save): {e}")

# --- DASHBOARD RENDERER ---
async def show_dashboard(event, edit=False):
    user_id = event.sender_id
    db_user = db_get_user(user_id)
    
    has_account = "✅ Connected" if db_user and db_user.get("session_string") else "❌ Not Connected"
    is_running = "🟢 Running" if user_id in ACTIVE_TASKS else "🔴 Stopped"
    
    groups_count = len(db_user.get("groups", [])) if db_user else 0
    has_msg = "✅ Saved" if db_user and db_user.get("ad_message") else "❌ Not Set"
    interval = db_user.get("interval", 5) if db_user else 5
    
    menu_text = (
        f"👻 **GHOST ADS BOT - SUPABASE CLOUD DASHBOARD** 👻\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Account Status:** {has_account}\n"
        f"📂 **Selected Groups:** {groups_count} Groups\n"
        f"📝 **Ad Message:** {has_msg}\n"
        f"⏱️ **Speed Interval:** Every {interval} Minutes\n"
        f"🚀 **Automation Status:** {is_running}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 **Niche diye gaye options me se select karein:**"
    )
    
    buttons = [
        [Button.inline("➕ Connect / Change Account", b"add_account")],
        [Button.inline("📂 Select Target Groups", b"select_groups")],
        [Button.inline("📝 Set / Edit Ad Message", b"set_message")],
        [Button.inline("⏱️ Set Speed (Interval)", b"set_speed")],
        [Button.inline("🚀 Run Ads", b"run_ads"), Button.inline("⏹️ Stop Ads", b"stop_ads")],
        [Button.inline("🔄 Refresh Dashboard", b"refresh_dashboard")]
    ]
    
    if edit:
        await event.edit(menu_text, buttons=buttons)
    else:
        await event.respond(menu_text, buttons=buttons)

def register_handlers(bot_client):
    @bot_client.on(events.NewMessage(pattern='/start'))
    async def start_command(event):
        user_id = event.sender_id
        if user_id not in USER_DATA:
            USER_DATA[user_id] = {"step": None}
        else:
            USER_DATA[user_id]["step"] = None
        await show_dashboard(event, edit=False)

    @bot_client.on(events.CallbackQuery(data=b"refresh_dashboard"))
    async def refresh_cb(event):
        await show_dashboard(event, edit=True)

    @bot_client.on(events.CallbackQuery(data=b"add_account"))
    async def add_account_callback(event):
        user_id = event.sender_id
        USER_DATA[user_id] = {"step": "waiting_account_api_id"}
        await event.edit(
            "🔑 **Step 1: API ID Enter Karein**\n\n"
            "Apni `my.telegram.org` wali API ID chat me bhejein (Sirf numbers):",
            buttons=[[Button.inline("🔙 Back", b"refresh_dashboard")]]
        )

    @bot_client.on(events.CallbackQuery(data=b"select_groups"))
    async def select_groups_callback(event):
        user_id = event.sender_id
        db_user = db_get_user(user_id)
        
        if not db_user or not db_user.get("session_string"):
            await event.answer("⚠️ Pehle apna Telegram account connect karein!", alert=True)
            return

        await event.edit("⏳ Aapke account ke groups fetch kiye ja rahe hain, kripya intezaar karein...")
        
        try:
            client = TelegramClient(StringSession(db_user["session_string"]), MASTER_API_ID, MASTER_API_HASH)
            await client.connect()
            
            dialogs = await client.get_dialogs()
            groups = []
            for dialog in dialogs:
                if dialog.is_group or dialog.is_channel:
                    groups.append({"id": dialog.id, "title": dialog.name})
            await client.disconnect()
            
            if not groups:
                await event.edit("❌ Aapke account me koi bhi groups ya channels nahi mile.", buttons=[[Button.inline("🔙 Back", b"refresh_dashboard")]])
                return
                
            USER_DATA[user_id]["fetched_groups"] = groups
            USER_DATA[user_id]["step"] = "choosing_groups"
            
            buttons = []
            saved_groups = db_user.get("groups", [])
            for g in groups[:15]:
                is_selected = g["id"] in saved_groups
                mark = "✅ " if is_selected else "➕ "
                buttons.append([Button.inline(f"{mark}{g['title'][:30]}", f"toggle_g_{g['id']}".encode())])
                
            buttons.append([Button.inline("✅ Done / Save Groups", b"save_groups_selection")])
            buttons.append([Button.inline("🔙 Back to Dashboard", b"refresh_dashboard")])
            
            await event.edit(
                "📂 **Group Selection Menu:**\n\n"
                "Jin groups me ads chalani hain unpar click karke select/deselect karein:",
                buttons=buttons
            )
        except Exception as e:
            await event.edit(f"❌ Error fetching groups: {e}", buttons=[[Button.inline("🔙 Back", b"refresh_dashboard")]])

    @bot_client.on(events.CallbackQuery(pattern=b"toggle_g_"))
    async def toggle_group_selection(event):
        user_id = event.sender_id
        group_id = int(event.data.decode().replace("toggle_g_", ""))
        
        db_user = db_get_user(user_id) or {}
        saved_groups = db_user.get("groups", [])
        
        if group_id in saved_groups:
            saved_groups.remove(group_id)
            await event.answer("Group deselected!")
        else:
            saved_groups.append(group_id)
            await event.answer("Group selected!")
            
        db_user["groups"] = saved_groups
        db_save_user(user_id, db_user)
            
        groups = USER_DATA[user_id].get("fetched_groups", [])
        buttons = []
        for g in groups[:15]:
            is_selected = g["id"] in saved_groups
            mark = "✅ " if is_selected else "➕ "
            buttons.append([Button.inline(f"{mark}{g['title'][:30]}", f"toggle_g_{g['id']}".encode())])
            
        buttons.append([Button.inline("✅ Done / Save Groups", b"save_groups_selection")])
        buttons.append([Button.inline("🔙 Back to Dashboard", b"refresh_dashboard")])
        
        await event.edit("📂 **Group Selection Menu:**\n\nApni pasand ke groups select karein:", buttons=buttons)

    @bot_client.on(events.CallbackQuery(data=b"save_groups_selection"))
    async def save_groups_cb(event):
        user_id = event.sender_id
        db_user = db_get_user(user_id) or {}
        count = len(db_user.get("groups", []))
        await event.answer(f"Success! {count} groups saved in cloud.", alert=True)
        await show_dashboard(event, edit=True)

    @bot_client.on(events.CallbackQuery(data=b"set_message"))
    async def set_message_callback(event):
        user_id = event.sender_id
        USER_DATA[user_id]["step"] = "waiting_ad_message"
        
        db_user = db_get_user(user_id) or {}
        current_msg = db_user.get("ad_message", "Not Set")
        await event.edit(
            f"📝 **Set / Edit Ad Message:**\n\n"
            f"Aapka current ad message:\n`{current_msg}`\n\n"
            f"Naya ad message bhejne ke liye seedha chat me type karke bhejein:",
            buttons=[[Button.inline("🔙 Back", b"refresh_dashboard")]]
        )

    @bot_client.on(events.CallbackQuery(data=b"set_speed"))
    async def set_speed_callback(event):
        buttons = [
            [Button.inline("⚡ Har 2 Minute me", b"spd_2"), Button.inline("⚡ Har 5 Minute me", b"spd_5")],
            [Button.inline("⚡ Har 10 Minute me", b"spd_10"), Button.inline("⚡ Har 15 Minute me", b"spd_15")],
            [Button.inline("⌨️ Custom Minutes Type Karein", b"spd_custom")],
            [Button.inline("🔙 Back", b"refresh_dashboard")]
        ]
        await event.edit("⏱️ **Select Speed Interval:**\n\nKitne time ke gap par ad send honi chahiye?", buttons=buttons)

    @bot_client.on(events.CallbackQuery(pattern=b"spd_"))
    async def speed_button_handler(event):
        user_id = event.sender_id
        data = event.data.decode()
        
        if data == "spd_custom":
            USER_DATA[user_id]["step"] = "waiting_custom_speed"
            await event.edit("⌨️ Apne hisab se minutes enter karein (Sirf number, jaise: `7`):", buttons=[[Button.inline("🔙 Back", b"set_speed")]])
            return
            
        interval_map = {"spd_2": 2, "spd_5": 5, "spd_10": 10, "spd_15": 15}
        interval = interval_map.get(data, 5)
        
        db_user = db_get_user(user_id) or {}
        db_user["interval"] = interval
        db_save_user(user_id, db_user)
        
        await event.answer(f"Speed updated: Every {interval} minutes!", alert=True)
        await show_dashboard(event, edit=True)

    @bot_client.on(events.CallbackQuery(data=b"run_ads"))
    async def run_ads_callback(event):
        user_id = event.sender_id
        db_user = db_get_user(user_id)
        
        if not db_user or not db_user.get("session_string"):
            await event.answer("⚠️ Pehle apna Telegram account connect karein!", alert=True)
            return
        if not db_user.get("groups"):
            await event.answer("⚠️ Pehle groups select karein!", alert=True)
            return
        if not db_user.get("ad_message"):
            await event.answer("⚠️ Pehle Ad Message set karein!", alert=True)
            return
        if user_id in ACTIVE_TASKS:
            await event.answer("⚠️ Ads automation pehle se chal rahi hai!", alert=True)
            return

        interval = db_user.get("interval", 5)
        groups = db_user["groups"]
        ad_msg = db_user["ad_message"]
        session_str = db_user["session_string"]

        db_user["is_active"] = True
        db_save_user(user_id, db_user)

        task = asyncio.create_task(run_background_ads(session_str, groups, ad_msg, interval, user_id))
        ACTIVE_TASKS[user_id] = task

        await event.answer("🚀 Ads Automation Start Ho Gayi Hai!", alert=True)
        await show_dashboard(event, edit=True)

    @bot_client.on(events.CallbackQuery(data=b"stop_ads"))
    async def stop_ads_callback(event):
        user_id = event.sender_id
        if user_id in ACTIVE_TASKS:
            ACTIVE_TASKS[user_id].cancel()
            del ACTIVE_TASKS[user_id]
            
            db_user = db_get_user(user_id) or {}
            db_user["is_active"] = False
            db_save_user(user_id, db_user)
            
            await event.answer("⏹️ Ads automation rok di gayi hai!", alert=True)
        else:
            await event.answer("ℹ️ Koi bhi ad active nahi hai.", alert=True)
        await show_dashboard(event, edit=True)

    @bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
    async def handle_user_input(event):
        user_id = event.sender_id
        text = event.raw_text.strip()
        
        if user_id not in USER_DATA or not USER_DATA[user_id].get("step"):
            return
            
        step = USER_DATA[user_id]["step"]
        
        if step == "waiting_account_api_id":
            if not text.isdigit():
                await event.respond("❌ Invalid API ID! Sirf numbers hone chahiye:")
                return
            USER_DATA[user_id]["acc_api_id"] = int(text)
            USER_DATA[user_id]["step"] = "waiting_account_api_hash"
            await event.respond("🔐 **Step 2: API Hash Enter Karein:**")
            
        elif step == "waiting_account_api_hash":
            USER_DATA[user_id]["acc_api_hash"] = text
            USER_DATA[user_id]["step"] = "waiting_phone"
            await event.respond("📱 **Step 3: Phone Number Enter Karein** (Jaise: `+919876543210`):")
            
        elif step == "waiting_phone":
            phone = text
            acc_api_id = USER_DATA[user_id]["acc_api_id"]
            acc_api_hash = USER_DATA[user_id]["acc_api_hash"]
            
            await event.respond("⏳ Connecting and sending OTP...")
            try:
                client = TelegramClient(StringSession(), acc_api_id, acc_api_hash)
                await client.connect()
                sent = await client.send_code_request(phone)
                
                USER_DATA[user_id]["user_client"] = client
                USER_DATA[user_id]["phone_code_hash"] = sent.phone_code_hash
                USER_DATA[user_id]["phone"] = phone
                USER_DATA[user_id]["step"] = "waiting_otp"
                
                await event.respond("📩 **OTP Sent!** Yahan bhejein (jaise: `1 2 3 4 5`):")
            except Exception as e:
                await event.respond(f"❌ Error: {e}\n\nDobara `/start` dabayein.")
                USER_DATA[user_id]["step"] = None

        elif step == "waiting_otp":
            otp = text.replace(" ", "")
            client = USER_DATA[user_id]["user_client"]
            phone = USER_DATA[user_id]["phone"]
            phone_code_hash = USER_DATA[user_id]["phone_code_hash"]
            
            try:
                await client.sign_in(phone, otp, phone_code_hash=phone_code_hash)
                session_str = client.session.save()
                
                db_user = db_get_user(user_id) or {}
                db_user["session_string"] = session_str
                db_save_user(user_id, db_user)
                
                USER_DATA[user_id]["step"] = None
                await event.respond("✅ **Account Successfully Connected & Saved to Cloud!** 🎉")
                await show_dashboard(event, edit=False)
            except Exception as e:
                if "password" in str(e).lower() or "SessionPasswordNeededError" in str(type(e)):
                    USER_DATA[user_id]["step"] = "waiting_2fa"
                    await event.respond("🔒 Two-Step Verification Password enter karein:")
                else:
                    await event.respond(f"❌ Login Failed: {e}\n\nTry `/start` again.")

        elif step == "waiting_2fa":
            password = text
            client = USER_DATA[user_id]["user_client"]
            try:
                await client.sign_in(password=password)
                session_str = client.session.save()
                
                db_user = db_get_user(user_id) or {}
                db_user["session_string"] = session_str
                db_save_user(user_id, db_user)
                
                USER_DATA[user_id]["step"] = None
                await event.respond("✅ **2FA Verified & Saved to Cloud!** 🎉")
                await show_dashboard(event, edit=False)
            except Exception as e:
                await event.respond(f"❌ Invalid Password: {e}")

        elif step == "waiting_ad_message":
            db_user = db_get_user(user_id) or {}
            db_user["ad_message"] = text
            db_save_user(user_id, db_user)
            
            USER_DATA[user_id]["step"] = None
            await event.respond("✅ **Ad Message Successfully Saved!** 🎉")
            await show_dashboard(event, edit=False)

        elif step == "waiting_custom_speed":
            if not text.isdigit():
                await event.respond("❌ Sirf number enter karein (jaise 7):")
                return
            
            db_user = db_get_user(user_id) or {}
            db_user["interval"] = int(text)
            db_save_user(user_id, db_user)
            
            USER_DATA[user_id]["step"] = None
            await event.respond(f"✅ Speed set to every {text} minutes!")
            await show_dashboard(event, edit=False)

async def run_background_ads(session_str, groups, message_text, interval_minutes, user_id):
    while True:
        try:
            client = TelegramClient(StringSession(session_str), MASTER_API_ID, MASTER_API_HASH)
            await client.connect()
            
            for group_id in groups:
                try:
                    await client.send_message(group_id, message_text)
                    await asyncio.sleep(3)
                except Exception as ex:
                    print(f"Failed to send ad to {group_id}: {ex}")
                    
            await client.disconnect()
            await asyncio.sleep(interval_minutes * 60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Background Loop Error: {e}")
            await asyncio.sleep(60)

async def handle_ping(request):
    return web.Response(text="Ghost Ads Bot is up and running smoothly on Render!")

from aiohttp import web

async def main():
    global bot
    # Initialize TelegramClient inside async event loop to support Python 3.14
    bot = TelegramClient('ghost_ads_bot_advanced_session', MASTER_API_ID, MASTER_API_HASH)
    
    register_handlers(bot)

    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Webhook server running on port {port}")

    print("👻 Advanced Ghost Ads Bot is running with Supabase & Webhook!")
    await bot.start(bot_token=MASTER_BOT_TOKEN)
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
