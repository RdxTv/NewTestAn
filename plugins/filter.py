import asyncio
import re
import math
import random
import aiohttp
import logging
import gc
from lru import LRU  # ✅ LRU-Dict imported for Auto-Pilot RAM Management
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS, DELETE_TIME, MAX_BOT_RESULTS, IS_PREMIUM, PICS, SPELL_CHECK
from utils import is_premium, get_size, is_check_admin, temp, get_settings, save_group_settings
from database.ia_filterdb import get_search_results
from database.users_chats_db import db
from Script import script  

logger = logging.getLogger(__name__)

# ✅ Auto-Pilot RAM: सिर्फ ताज़ा 300 सर्च मेमोरी में रहेंगे, पुराने अपने आप डिलीट हो जाएंगे!
BUTTONS = LRU(300) 
SRC_TO_SHORT = {"primary": "pri", "cloud": "cld", "archive": "arc", "all": "all"}
SHORT_TO_SRC = {"pri": "primary", "cld": "cloud", "arc": "archive", "all": "all"}

# ⚡ स्मार्ट डिक्शनरी जो चालू टाइमर्स को ट्रैक करेगी ताकि रिसेट किया जा सके
ACTIVE_DELETE_TASKS = {}

# ⚡ AGGRESSIVE RAM PROTECTION (Koyeb Free Tier Safe Guard)
def check_cache_limit():
    """चूंकि BUTTONS अब LRU से ऑटो-कंट्रोल हो रहा है, हम सिर्फ temp.FILES को फ्लश करेंगे"""
    if hasattr(temp, "FILES") and len(temp.FILES) > 300:
        temp.FILES.clear()
        gc.collect()
        logger.info("🧹 Auto-Pilot RAM Cleaned: temp.FILES Flushed Successfully.")

async def is_valid_search(message):
    if not message.text or message.text.startswith("/"): return False
    if message.forward_date or message.photo or message.video or message.document: return False
    if message.entities and any(e.type in [enums.MessageEntityType.URL, enums.MessageEntityType.TEXT_LINK] for e in message.entities): return False
    if not any(c.isalnum() for c in message.text): return False
    return True

# ─────────────────────────────────────────────
# ⏰ SMART AUTO-DELETE WITH RESET ENGINE
# ─────────────────────────────────────────────
async def start_auto_delete_timer(client, chat_id, message_id, delay=300):
    """5 मिनट बाद मैसेज को डिलीट करने का टास्क, जो एक्टिविटी होने पर रिसेट हो सकता है"""
    task_key = f"{chat_id}_{message_id}"
    
    # अगर इस मैसेज का टाइमर पहले से चल रहा है, Outer Time Cancel (Reset) करें
    if task_key in ACTIVE_DELETE_TASKS:
        try:
            ACTIVE_DELETE_TASKS[task_key].cancel()
        except:
            pass

    async def _delete_task():
        try:
            await asyncio.sleep(delay)
            await client.delete_messages(chat_id, message_id)
            ACTIVE_DELETE_TASKS.pop(task_key, None)
        except asyncio.CancelledError:
            pass # टाइमर रिसेट होने पर बिना डिलीट किए बंद हो जाएगा
        except Exception as e:
            logger.error(f"Auto-delete runtime error: {e}")

    # नया 5 मिनट का फ्रेश टाइमर टास्क सेट करें
    task = asyncio.create_task(_delete_task())
    ACTIVE_DELETE_TASKS[task_key] = task

# ─────────────────────────────────────────────
# 🧠 SPELL CHECKER (Google Suggest API Engine)
# ─────────────────────────────────────────────
_http_session = None

async def get_http_session():
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session

async def get_spell_suggestion(query):
    try:
        session = await get_http_session()
        url = f"http://suggestqueries.google.com/complete/search?client=firefox&q={query} movie"
        async with session.get(url) as resp:
            data = await resp.json()
            if data and len(data) > 1 and data[1]:
                suggestion = data[1][0].replace(" movie", "").replace(" series", "").strip()
                if suggestion.lower() != query.lower():
                    return suggestion.title()
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────
# 🎨 UI HELPER FUNCTION (Minimalist Layout Lock)
# ─────────────────────────────────────────────
def get_filter_ui(search, files, total, act_src, offset, chat_id, req_id, key, next_off, simple_mode=True):
    list_items = [
        f"📁 <a href='https://t.me/{temp.U_NAME}?start=file_{chat_id}_{f['_id']}'>[{get_size(f['file_size'])}] {f['file_name']}</a>"
        for f in files
    ]
    files_text = "\n\n".join(list_items)
    
    total_pages = math.ceil(total / MAX_BOT_RESULTS)
    curr_page = (int(offset) // MAX_BOT_RESULTS) + 1
    
    cap = (f"<b>👑 Search: {search}\n🎬 Total: {total}\n📚 Source: {act_src.upper()}\n"
           f"📄 Page: {curr_page}/{total_pages}</b>\n\n{files_text}")

    btn = []
    
    act_src_lower = act_src.lower()
    act_src_short = SRC_TO_SHORT.get(act_src_lower, "all")

    nav = []
    prev_off = int(offset) - MAX_BOT_RESULTS
    if prev_off >= 0: 
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"nav_{req_id}_{key}_{prev_off}_{act_src_short}"))
        
    if next_off: 
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"nav_{req_id}_{key}_{next_off}_{act_src_short}"))
    
    if nav: 
        btn.append(nav)

    if not simple_mode:
        col_btn = []
        for c in ["primary", "cloud", "archive"]:
            # ✅ अगर सोर्स 'all' है तो सब पर टिक लगाओ, वरना सिर्फ उसी पर लगाओ जो मैच हो
            tick = "✅" if (act_src_lower == "all" or c == act_src_lower) else "📂"
            col_btn.append(InlineKeyboardButton(f"{tick} {c.title()}", callback_data=f"coll_{req_id}_{key}_{SRC_TO_SHORT[c]}"))
        btn.append(col_btn)
        btn.append([InlineKeyboardButton("❌ Close Result", callback_data=f"close_{req_id}")])
    
    return cap, InlineKeyboardMarkup(btn) if btn else None

# ─────────────────────────────────────────────
# ⚙️ INLINE GROUP SETTINGS UI CENTER
# ─────────────────────────────────────────────
def get_settings_markup(settings):
    s_del = "✅ ON" if settings.get("auto_delete", True) else "❌ OFF"
    s_spl = "✅ ON" if settings.get("spell_check", True) else "❌ OFF"
    s_btn = "🔲 SIMPLE" if settings.get("simple_mode", True) else "🔳 FULL"
    
    buttons = [
        [InlineKeyboardButton(f"⏳ Auto Delete: {s_del}", callback_data="set_toggle_auto_delete")],
        [InlineKeyboardButton(f"🧠 Spell Check: {s_spl}", callback_data="set_toggle_spell_check")],
        [InlineKeyboardButton(f"🎨 Buttons Style: {s_btn}", callback_data="set_toggle_simple_mode")],
        [InlineKeyboardButton("❌ Close Panel", callback_data="close_admin_panel")]
    ]
    return InlineKeyboardMarkup(buttons)

@Client.on_message(filters.command("settings") & filters.group)
async def group_settings_panel(client, message):
    if not await is_check_admin(client, message.chat.id, message.from_user.id): return
    settings = await get_settings(message.chat.id)
    await message.reply(
        f"⚙️ <b>Welcome to Inline Control Center!</b>\n\nConfigure settings for <b>{message.chat.title}</b> 👇",
        reply_markup=get_settings_markup(settings)
    )

@Client.on_callback_query(filters.regex(r"^set_toggle_"))
async def toggle_settings_callback(client, query):
    try:
        if not await is_check_admin(client, query.message.chat.id, query.from_user.id):
            return await query.answer("❌ Only Group Admins can tweak settings!", show_alert=True)
            
        key = query.data.replace("set_toggle_", "")
        settings = await get_settings(query.message.chat.id)
        
        settings[key] = not settings.get(key, True)
        await save_group_settings(query.message.chat.id, key, settings[key])
        
        await query.answer("✅ Configuration Updated Successfully!", show_alert=False)
        await query.message.edit_reply_markup(reply_markup=get_settings_markup(settings))
    except Exception as e:
        logger.error(f"Settings Toggle Error: {e}")

@Client.on_callback_query(filters.regex(r"^close_admin_panel"))
async def close_admin_panel(client, query):
    try: await query.message.delete()
    except: pass

# ─────────────────────────────────────────────
# 🔍 COMMAND CONTROLS (Group + PM Sync Done ✅)
# ─────────────────────────────────────────────
@Client.on_message(filters.command("button_style") & (filters.group | filters.private))
async def button_style_toggle(client, message):
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if not await is_check_admin(client, message.chat.id, message.from_user.id): return

    settings = await get_settings(message.chat.id)
    new_mode_val = not settings.get("simple_mode", True)
    await save_group_settings(message.chat.id, "simple_mode", new_mode_val)
    
    new_mode_str = "SIMPLE (Only Next/Prev)" if new_mode_val else "FULL (With Source Buttons)"
    await message.reply(f"✅ <b>Button style changed to:</b> **{new_mode_str}**")

@Client.on_message(filters.command("search") & filters.group)
async def search_toggle(client, message):
    if not await is_check_admin(client, message.chat.id, message.from_user.id): return
    if len(message.command) < 2: return await message.reply("Usage: `/search on` or `/search off`")
    state = True if message.command[1].lower() == "on" else False
    await save_group_settings(message.chat.id, "search_enabled", state)
    await message.reply(f"✅ Search is now **{'ENABLED' if state else 'DISABLED'}**")

# ─────────────────────────────────────────────
# 🔒 STRICT PREMIUM GATE PASSENGERS
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_search(client, message):
    if not await is_valid_search(message): return
    uid = message.from_user.id
    
    if uid not in ADMINS and not await is_premium(uid, client):
        return await message.reply_photo(
            random.choice(PICS), 
            caption=script.PLAN_TXT.format(10, "@admin"), 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium Plan", callback_data="activate_plan")]])
        )
    
    settings = await get_settings(message.chat.id)
    await auto_filter(client, message, collection_type="all", settings=settings)

@Client.on_message(filters.group & filters.text & filters.incoming)
async def group_search(client, message):
    if not await is_valid_search(message): return
    chat_id, user_id = message.chat.id, message.from_user.id

    settings = await get_settings(chat_id)
    if not settings.get("search_enabled", True): return
    
    if user_id not in ADMINS and not await is_premium(user_id, client): return

    text_lower = message.text.lower()
    
    if "http" in text_lower or "t.me/" in text_lower:
        if re.search(r"(?:http|www\.|t\.me/)", text_lower):
            if not await is_check_admin(client, chat_id, user_id):
                try: await message.delete()
                except: pass
                msg = await message.reply("❌ External Links not allowed in Premium Group!", quote=True)
                await asyncio.sleep(5)
                try: await msg.delete()
                except: pass
                return

    await auto_filter(client, message, collection_type="all", settings=settings)

# ─────────────────────────────────────────────
# 🚀 AUTO FILTER CORE (Locked to 12 Buttons)
# ─────────────────────────────────────────────
async def auto_filter(client, msg, collection_type="all", settings=None):
    check_cache_limit() 
    search = msg.text.strip()
    
    files, next_offset, total, act_src = await get_search_results(search, MAX_BOT_RESULTS, 0, collection_type=collection_type)

    if not settings: settings = await get_settings(msg.chat.id)
    is_simple_mode = settings.get("simple_mode", True)

    if not files:
        if SPELL_CHECK:
            suggestion = await get_spell_suggestion(search)
            if suggestion:
                btn = [[InlineKeyboardButton(f"✅ Yes, search '{suggestion}'", callback_data=f"spellchk_{msg.from_user.id}_{suggestion}")]]
                cap = f"❌ **{search}** not found.\n\n🤔 **Did you mean:** __{suggestion}__?"
                try:
                    m = await msg.reply(cap, reply_markup=InlineKeyboardMarkup(btn), quote=True)
                    asyncio.create_task(start_auto_delete_timer(client, m.chat.id, m.id, delay=300))
                except: pass
                return

        try:
            m = await msg.reply(script.NOT_FILE_TXT.format(msg.from_user.mention, search), quote=True)
            asyncio.create_task(start_auto_delete_timer(client, m.chat.id, m.id, delay=15))
        except: pass
        return

    key = f"{msg.chat.id}-{msg.id}"
    temp.FILES[key] = files
    BUTTONS[key] = search

    cap, markup = get_filter_ui(search, files, total, act_src, 0, msg.chat.id, msg.from_user.id, key, next_offset, is_simple_mode)

    try:
        res = await msg.reply(cap, reply_markup=markup, disable_web_page_preview=True, quote=True)
        asyncio.create_task(start_auto_delete_timer(client, res.chat.id, res.id, delay=300))
    except Exception as e: 
        logger.error(f"Auto filter response error: {e}")

# ─────────────────────────────────────────────
# 📤 CALLBACK HANDLERS
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^close_"))
async def close_callback(client, query):
    try:
        chat_id = query.message.chat.id
        current_msg_id = query.message.id
        
        task_key = f"{chat_id}_{current_msg_id}"
        if task_key in ACTIVE_DELETE_TASKS:
            ACTIVE_DELETE_TASKS[task_key].cancel()
            ACTIVE_DELETE_TASKS.pop(task_key, None)

        # ✅ BUG FIX: अंधे की तरह -1/+1 डिलीट करने के बजाय सिर्फ बोट रिस्पांस और मूल यूज़र क्वेरी को ही डिलीट करें
        msg_ids_to_clean = [current_msg_id]
        if query.message.reply_to_message:
            msg_ids_to_clean.append(query.message.reply_to_message.id)
        elif getattr(query.message, "reply_to_message_id", None):
            msg_ids_to_clean.append(query.message.reply_to_message_id)
        
        for mid in msg_ids_to_clean:
            await db.remove_from_delete_queue(chat_id, mid)
            
        await client.delete_messages(chat_id, msg_ids_to_clean)
    except Exception:
        try: await query.message.delete()
        except: pass
    finally:
        gc.collect()

@Client.on_callback_query(filters.regex(r"^spellchk_"))
async def spell_check_handler(client, query):
    try:
        _, req_id, suggestion = query.data.split("_", 2)
        if int(req_id) != query.from_user.id:
            return await query.answer("❌ This suggestion is not for you!", show_alert=True)
            
        await query.answer(f"🔍 Searching for {suggestion}...", show_alert=False)
        files, next_offset, total, act_src = await get_search_results(suggestion, MAX_BOT_RESULTS, 0, collection_type="all")
        
        if not files:
            return await query.message.edit_text(f"❌ Still no results found for **{suggestion}**.")
            
        key = f"{query.message.chat.id}-{query.message.id}"
        temp.FILES[key] = files
        BUTTONS[key] = suggestion
        
        settings = await get_settings(query.message.chat.id)
        is_simple_mode = settings.get("simple_mode", True)

        cap, markup = get_filter_ui(suggestion, files, total, act_src, 0, query.message.chat.id, query.from_user.id, key, next_offset, is_simple_mode)
        await query.message.edit_text(cap, reply_markup=markup, disable_web_page_preview=True)
        
        asyncio.create_task(start_auto_delete_timer(client, query.message.chat.id, query.message.id, delay=300))
            
    except Exception as e:
        logger.error(f"Spellcheck Callback Error: {e}")
        await query.answer("❌ Error during search!", show_alert=True)
    finally:
        gc.collect()

# ─────────────────────────────────────────────
# 🔄 PAGINATION & PERFECT TIMER RESET SYNCHRONIZER
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^(nav_|coll_)"))
async def pagination_handler(client, query):
    try:
        data = query.data.split("_")
        action, req, key = data[0], data[1], data[2]
        if int(req) != query.from_user.id: return await query.answer("❌ Not for you!", show_alert=True)
    except: return await query.answer("❌ Error!", show_alert=True)

    if IS_PREMIUM and query.from_user.id not in ADMINS and not await is_premium(query.from_user.id, client): 
        return await query.answer("❌ Premium Expired!", show_alert=True)

    search = BUTTONS.get(key)
    if not search: return await query.answer("❌ Search Expired!", show_alert=True)

    # ✅ Default fallback changed to "all" to support multi-collection scrolling 
    offset, coll_short = (int(data[3]), data[4]) if action == "nav" else (0, data[3])
    coll_type = SHORT_TO_SRC.get(coll_short, "all")

    files, next_off, total, act_src = await get_search_results(search, MAX_BOT_RESULTS, offset, collection_type=coll_type)
    
    if not files:
        err = "❌ No more pages!" if action == "nav" else f"❌ No files in {coll_type.upper()}"
        return await query.answer(err, show_alert=True)

    temp.FILES[key] = files
    settings = await get_settings(query.message.chat.id)
    is_simple_mode = settings.get("simple_mode", True)
    
    cap, markup = get_filter_ui(search, files, total, act_src, offset, query.message.chat.id, req, key, next_off, is_simple_mode)

    try: 
        await query.message.edit_text(cap, reply_markup=markup, disable_web_page_preview=True)
        asyncio.create_task(start_auto_delete_timer(client, query.message.chat.id, query.message.id, delay=300))
    except Exception as e:
        logger.error(f"Pagination delivery failure: {e}")
        asyncio.create_task(start_auto_delete_timer(client, query.message.chat.id, query.message.id, delay=300))
        
    await query.answer()
    gc.collect()
