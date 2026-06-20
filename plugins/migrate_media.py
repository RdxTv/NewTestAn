import asyncio
import logging
import random
import io
from hydrogram import Client, filters
from hydrogram.errors import FloodWait, MessageNotModified

# कोर डेटाबेस कलेक्शंस सिंक
from database.ia_filterdb import actors, COLLECTIONS
from info import ADMINS, ACTOR_STORAGE_CHANNEL, THUMBNAIL_STORAGE_CHANNEL

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("migrate_media") & filters.user(ADMINS))
async def migrate_media_cmd(client, message):
    status_msg = await message.reply(
        "⚡ <b>Core Media Migration Pipeline Initiated...</b>\n"
        "Scanning database collections for legacy media items."
    )
    
    stats_tracker = {
        "actor": {"profile": 0, "gallery": 0},
        "app": {"profile": 0, "gallery": 0},
        "website": {"profile": 0, "gallery": 0}
    }
    
    thumb_success, thumb_skipped = 0, 0
    total_processed = 0
    
    async def safe_edit_status(text):
        try: await status_msg.edit(text)
        except MessageNotModified: pass
        except Exception: pass

    # ─────────────────────────────────────────────────────────
    # 🎭 PHASE 1: DIRECTORY MIGRATION (ACTOR, APP, WEBSITE)
    # ─────────────────────────────────────────────────────────
    try:
        await safe_edit_status("⏳ <b>Phase 1/2: Preparing Directory Assets (Actor / App / Website)...</b>")
        cursor = actors.find({})
        async for actor in cursor:
            category = actor.get("category", "actor")
            if category not in stats_tracker: category = "actor"

            # 1. मुख्य प्रोफाइल फोटो का ट्रांसफर
            p_img = actor.get("photo_url")
            if p_img and p_img.startswith("TG_ID:") and not actor.get("is_actor_permanent"):
                raw_file_id = p_img.replace("TG_ID:", "")
                
                while True:
                    try:
                        file_buffer = await client.download_media(raw_file_id, in_memory=True)
                        if file_buffer:
                            file_buffer.seek(0)
                            new_msg = await client.send_photo(chat_id=ACTOR_STORAGE_CHANNEL, photo=file_buffer)
                            
                            if new_msg and new_msg.photo:
                                new_file_id = new_msg.photo.sizes[-1].file_id if hasattr(new_msg.photo, "sizes") and new_msg.photo.sizes else new_msg.photo.file_id
                                
                                if new_file_id:
                                    logger.info(f"📁 [ACTOR PROFILE] OLD ID: {raw_file_id[:20]}... ➡️ NEW ID: {new_file_id[:20]}...")
                                    res = await actors.update_one(
                                        {"_id": actor["_id"]}, 
                                        {"$set": {"photo_url": f"TG_ID:{new_file_id}", "is_actor_permanent": True}}
                                    )
                                    if res.modified_count > 0:
                                        stats_tracker[category]["profile"] += 1
                        
                        total_processed += 1
                        await asyncio.sleep(random.uniform(1.0, 3.0))
                        break
                    except FloodWait as e: await asyncio.sleep(e.value + 2)
                    except Exception as err:
                        logger.error(f"Directory Photo Shift Error: {err}")
                        break

            # 2. लाइटबॉक्स गैलरी एरे का ट्रांसफर (🔒 DOUBLE RUN PROTECTION ADDED)
            # यदि इस डॉक्यूमेंट की गैलरी पहले ही पूरी तरह परमानेंट मार्क हो चुकी है, तो इसे स्किप करें
            if actor.get("is_gallery_permanent"):
                continue

            gallery = actor.get("gallery", [])
            if gallery:
                new_gallery = []
                has_changed = False
                
                for g_id in gallery:
                    if g_id and g_id.startswith("TG_ID:"):
                        raw_g_id = g_id.replace("TG_ID:", "")
                        
                        while True:
                            try:
                                file_buffer = await client.download_media(raw_g_id, in_memory=True)
                                if file_buffer:
                                    file_buffer.seek(0)
                                    new_msg = await client.send_photo(chat_id=ACTOR_STORAGE_CHANNEL, photo=file_buffer)
                                    
                                    if new_msg and new_msg.photo:
                                        new_f_id = new_msg.photo.sizes[-1].file_id if hasattr(new_msg.photo, "sizes") and new_msg.photo.sizes else new_msg.photo.file_id
                                        
                                        if new_f_id:
                                            logger.info(f"🖼️ [GALLERY IMAGE] OLD ID: {raw_g_id[:20]}... ➡️ NEW ID: {new_f_id[:20]}...")
                                            new_gallery.append(f"TG_ID:{new_f_id}")
                                            stats_tracker[category]["gallery"] += 1
                                            has_changed = True
                                        else: new_gallery.append(g_id)
                                    else: new_gallery.append(g_id)
                                else: new_gallery.append(g_id)
                                    
                                total_processed += 1
                                if total_processed % 5 == 0:
                                    await safe_edit_status(
                                        f"⏳ <b>Phase 1/2: Migrating Directory Hub...</b>\n\n"
                                        f"🎭 <b>Actors Profiles Modified:</b> <code>{stats_tracker['actor']['profile']}</code> | Gallery: <code>{stats_tracker['actor']['gallery']}</code>\n"
                                        f"📱 <b>Apps Profiles Modified:</b> <code>{stats_tracker['app']['profile']}</code> | Gallery: <code>{stats_tracker['app']['gallery']}</code>\n"
                                        f"🌐 <b>Websites Profiles Modified:</b> <code>{stats_tracker['website']['profile']}</code> | Gallery: <code>{stats_tracker['website']['gallery']}</code>\n\n"
                                        f"⏱️ <i>Strict 1-3s Dynamic Delay Engine Active...</i>"
                                    )
                                    
                                await asyncio.sleep(random.uniform(1.0, 3.0))
                                break
                            except FloodWait as e: await asyncio.sleep(e.value + 2)
                            except Exception:
                                new_gallery.append(g_id)
                                break
                    else:
                        new_gallery.append(g_id)
                
                if has_changed and len(new_gallery) == len(gallery):
                    # ✅ मोंगोडीबी लॉक पैच: गैलरी अपडेट होते ही 'is_gallery_permanent: True' सेट कर दिया
                    res = await actors.update_one(
                        {"_id": actor["_id"]}, 
                        {"$set": {"gallery": new_gallery, "is_gallery_permanent": True}}
                    )
                    if res.modified_count > 0:
                        logger.info("✅ [DATABASE SUCCESS] Actor Gallery Array updated and hard-locked!")
                    
    except Exception as e:
        logger.error(f"Directory Migration Crash: {e}")

    # ─────────────────────────────────────────────────────────
    # 🖼️ PHASE 2: MOVIE THUMBNAILS COMPONENT MIGRATION
    # ─────────────────────────────────────────────────────────
    try:
        await safe_edit_status("⏳ <b>Phase 2/2: Opening Vault & Scanning Movie Posters...</b>")
        for name, col in COLLECTIONS.items():
            if name == "actors": continue
            
            cursor = col.find({"thumb_url": {"$exists": True, "$regex": "^TG_ID:"}})
            async for doc in cursor:
                t_id = doc.get("thumb_url")
                
                if t_id and not doc.get("is_thumb_permanent"):
                    raw_thumb_id = t_id.replace("TG_ID:", "")
                    
                    while True:
                        try:
                            file_buffer = await client.download_media(raw_thumb_id, in_memory=True)
                            if file_buffer:
                                file_buffer.seek(0)
                                new_msg = await client.send_photo(chat_id=THUMBNAIL_STORAGE_CHANNEL, photo=file_buffer)
                                
                                if new_msg and new_msg.photo:
                                    new_t_id = new_msg.photo.sizes[-1].file_id if hasattr(new_msg.photo, "sizes") and new_msg.photo.sizes else new_msg.photo.file_id
                                    
                                    if new_t_id:
                                        logger.info(f"🎬 [MOVIE THUMB] OLD ID: {raw_thumb_id[:20]}... ➡️ NEW ID: {new_t_id[:20]}...")
                                        res = await col.update_one(
                                            {"_id": doc["_id"]}, 
                                            {"$set": {"thumb_url": f"TG_ID:{new_t_id}", "is_thumb_permanent": True}}
                                        )
                                        if res.modified_count > 0:
                                            thumb_success += 1
                                            logger.info(f"✅ [DATABASE SUCCESS] Movie Thumb ID modified in {name.upper()}!")
                            
                            total_processed += 1
                            if total_processed % 5 == 0:
                                await safe_edit_status(
                                    f"⏳ <b>Phase 2/2: Transferring Vault Posters...</b>\n\n"
                                    f"🖼️ <b>Thumbnails Modified Count:</b> <code>{thumb_success}</code>\n"
                                    f"⚠️ Skipped/Permanent: <code>{thumb_skipped}</code>\n"
                                    f"📊 Current Collection: <code>{name.upper()}</code>"
                                )
                            await asyncio.sleep(random.uniform(1.0, 3.0))
                            break
                        except FloodWait as e: await asyncio.sleep(e.value + 2)
                        except Exception as e:
                            logger.error(f"Thumbnail Migration Failed: {e}")
                            thumb_skipped += 1
                            break
                else:
                    thumb_skipped += 1
    except Exception as e:
        logger.error(f"Thumbnail Migration Crash: {e}")

    report = (
        "<b>🎉 Smart Media Migration Matrix Complete!</b>\n\n"
        f"🎭 <b>Actors Modified Count:</b> <code>{stats_tracker['actor']['profile']} Profiles</code> | <code>{stats_tracker['actor']['gallery']} Gallery</code>\n"
        f"📱 <b>Apps Modified Count:</b> <code>{stats_tracker['app']['profile']} Profiles</code> | <code>{stats_tracker['app']['gallery']} Gallery</code>\n"
        f"🌐 <b>Websites Modified Count:</b> <code>{stats_tracker['website']['profile']} Profiles</code> | <code>{stats_tracker['website']['gallery']} Gallery</code>\n"
        f"🖼️ <b>Thumbnails Modified Count:</b> <code>{thumb_success} Movie Posters</code>\n"
        f"⚠️ <b>Skipped / Clean:</b> <code>{thumb_skipped} Files</code>\n\n"
        "⚡ <i>All assets safely isolated into separate channels! Double-run protection activated.</i>"
    )
    await safe_edit_status(report)
