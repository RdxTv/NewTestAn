import io
import gc
import time
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp, get_size
from info import BIN_CHANNEL
from database.ia_filterdb import actors, get_search_results
from web.web_assets import build_page, get_auth, form_wrapper

actor_routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────
# 🎭 PUBLIC VIEW: ACTORS DIRECTORY CATALOG PAGE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actors')
async def actors_directory_page(req):
    role, _ = await get_auth(req)
    if not role: 
        return web.HTTPFound('/login')
        
    # डेटाबेस से सभी एक्टर्स को नए से पुराने के क्रम में निकालना
    cursor = actors.find({}).sort("created_at", -1)
    all_actors = await cursor.to_list(length=200)
    
    # अगर एडमिन है तो सबसे ऊपर क्रिएशन एक्शन बटन दिखाओ
    admin_header_action = ""
    if role == 'admin':
        admin_header_action = '''
        <div style="display:flex; justify-content:flex-end; margin-bottom:25px;">
            <a href="/admin/create_actor" style="background:var(--accent); color:#fff; padding:12px 24px; border-radius:8px; font-weight:700; text-decoration:none; font-size:14px; transition:0.2s; box-shadow:0 4px 15px rgba(229,9,20,0.3);">➕ Create New Actor</a>
        </div>
        '''
        
    actors_grid_html = ""
    if not all_actors:
        actors_grid_html = '<div style="color:var(--muted); text-align:center; padding:60px 20px; grid-column:1/-1;">🎭 No actor profiles created yet.</div>'
    else:
        actors_grid_html = '<div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:20px;">'
        for act in all_actors:
            act_id = str(act["_id"])
            actors_grid_html += f'''
            <div style="background:var(--card); border:1px solid var(--border); border-radius:10px; overflow:hidden; transition:0.2s; cursor:pointer;" onclick="window.location.href='/actor/{act_id}'">
                <div style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">
                    <img src="/api/actor/photo?id={act_id}" style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover;" loading="lazy">
                </div>
                <div style="padding:12px; text-align:center;">
                    <div style="font-size:14px; font-weight:700; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{act.get('name')}</div>
                </div>
            </div>
            '''
        actors_grid_html += '</div>'

    page_body = f'''
    <div class="main" style="padding-top:30px; max-width:1100px; margin:0 auto; padding-left:20px; padding-right:20px;">
        <div style="margin-bottom:20px;">
            <h1 style="font-size:28px; font-weight:900; color:var(--text); margin-bottom:4px;">🎭 Actors Catalog</h1>
            <p style="color:var(--muted); font-size:14px;">Browse verified star profiles and linked content grids.</p>
        </div>
        {admin_header_action}
        {actors_grid_html}
    </div>
    '''
    return build_page("Actors Directory - Fast Finder", page_body, "", "actors", role)

# ─────────────────────────────────────────────────────────
# 🎭 ADMIN VIEW: CREATE ACTOR PROFILE PAGE FORM
# ─────────────────────────────────────────────────────────
@actor_routes.get('/admin/create_actor')
async def create_actor_page(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.HTTPFound('/dashboard')
        
    content = f'''
    <form action="/api/create_actor" method="post" enctype="multipart/form-data">
        <input type="text" name="name" placeholder="Actor Full Name (e.g., Shah Rukh Khan)" required>
        <textarea name="bio" placeholder="Actor Biography / Details..." style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; min-height:100px; outline:none; margin-bottom:15px; font-family:inherit;" required></textarea>
        
        <div class="scard-label" style="margin-bottom:8px; color:var(--muted);">Actor Profile Photo</div>
        <input type="file" name="photo" accept="image/*" required style="padding:10px 0; color:var(--text);">
        
        <button class="submit-btn" type="submit" style="background:var(--accent); color:#fff; width:100%; padding:14px; border:0; border-radius:6px; font-weight:700; cursor:pointer; margin-top:10px;">Create Actor Profile</button>
    </form>
    <div style="margin-top:15px; text-align:center;"><a href="/actors" style="color:var(--muted); text-decoration:none; font-size:13px;">← Back to Actors Catalog</a></div>
    '''
    return build_page("Create Actor Profile", form_wrapper("Add New Actor", content, req.query.get('err',''), req.query.get('msg','')), "login-bg", "actors", role)

# ─────────────────────────────────────────────────────────
# ⚙️ ADMIN API: UPLOAD TO TG & SAVE TO MONGO
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/create_actor')
async def api_create_actor(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.json_response({"error": "Unauthorized"}, status=403)
        
    try:
        reader = await req.multipart()
        name, bio, image_bytes = None, None, None
        
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == 'name':
                name = (await part.read()).decode().strip()
            elif part.name == 'bio':
                bio = (await part.read()).decode().strip()
            elif part.name == 'photo':
                image_bytes = await part.read()

        if not name or not bio or not image_bytes:
            return web.HTTPFound('/admin/create_actor?err=All fields are required!')

        with io.BytesIO(image_bytes) as img_buffer:
            img_buffer.name = f"{name.replace(' ', '_')}.jpg"
            msg = await temp.BOT.send_photo(chat_id=BIN_CHANNEL, photo=img_buffer)

        if not msg or not msg.photo:
            return web.HTTPFound('/admin/create_actor?err=Telegram Upload Failed!')

        tg_photo_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
        
        actor_doc = {
            "name": name,
            "bio": bio,
            "photo_url": f"TG_ID:{tg_photo_id}",
            "created_at": time.time()
        }
        await actors.insert_one(actor_doc)
        
        return web.HTTPFound('/actors?msg=Actor Profile created successfully!')
    except Exception as e:
        return web.HTTPFound(f'/admin/create_actor?err=Server Error: {str(e)}')

# ─────────────────────────────────────────────────────────
# 🖼️ ZERO-RAM ACTOR PHOTO ENGINE (Koyeb Crash Proof)
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/photo')
async def get_actor_photo(req):
    actor_id = req.query.get("id")
    if not actor_id: return web.Response(status=400)
    
    try:
        doc = await actors.find_one({"_id": ObjectId(actor_id)}, {"photo_url": 1})
        if not doc or not doc.get("photo_url"): return web.Response(status=404)
        
        tg_id = doc["photo_url"].replace("TG_ID:", "")
        file_data = await temp.BOT.download_media(tg_id, in_memory=True)
        if not file_data: return web.Response(status=404)
        
        body_bytes = file_data.getvalue()
        file_data.close()
        del file_data
        
        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": 'inline; filename="actor.jpg"'
        }
        return web.Response(body=body_bytes, content_type="image/jpeg", headers=headers)
    except Exception:
        return web.Response(status=500)
    finally:
        gc.collect()

# ─────────────────────────────────────────────────────────
# 🌐 PUBLIC VIEW: ACTOR PROFILE + 3 TABS SYSTEM
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actor/{id}')
async def actor_profile_display(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    
    try:
        actor_id = req.match_info['id']
        actor = await actors.find_one({"_id": ObjectId(actor_id)})
        if not actor: return web.Response(text="Actor Not Found", status=404)
    except:
        return web.Response(text="Invalid ID", status=400)
        
    actor_name = actor["name"]
    video_docs, _, _, _ = await get_search_results(
        query=actor_name, max_results=30, offset=0, collection_type="all", bypass_count=True
    )
    
    grid_html = ""
    if not video_docs:
        grid_html = '<div style="color:var(--muted); padding:30px; text-align:center;">No files found matching this actor name.</div>'
    else:
        grid_html = '<div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:16px;">'
        for f in video_docs:
            sc = (f.get("source_col", "primary")).lower()
            fid = f.get("file_ref") or f.get("_id")
            raw_thumb = f.get("thumb_url", "")
            v_salt = raw_thumb[-8:] if (raw_thumb and raw_thumb.startswith("TG_ID:")) else "0"
            
            grid_html += f'''
            <div style="background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:hidden; padding:10px; display:flex; flex-direction:column; justify-content:space-between;">
                <div style="position:relative; padding-top:56.25%; background:var(--bg3); overflow:hidden; border-radius:4px;">
                    <img src="/api/thumb?file_id={f['_id']}&col={sc}&v={v_salt}" style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover;" loading="lazy">
                </div>
                <div style="padding-top:8px;">
                    <div style="font-size:13px; font-weight:600; line-height:1.4; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; margin-bottom:8px; color:var(--text);">{f.get('file_name')}</div>
                    <div style="font-size:11px; color:var(--muted); margin-bottom:10px;">Size: {get_size(f.get('file_size', 0))}</div>
                    <a href="/setup_stream?file_id={fid}&mode=watch" target="_blank" style="background:#fff; color:#000; text-align:center; padding:8px; border-radius:4px; font-size:12px; font-weight:700; text-decoration:none; display:block;">⚡ Play Now</a>
                </div>
            </div>
            '''
        grid_html += '</div>'

    tab_engine_ui = f'''
    <style>
        .actor-tab-bar {{ display: flex; gap: 10px; border-bottom: 2px solid var(--border); margin-bottom: 25px; }}
        .actor-tab {{ background: transparent; border: none; color: var(--muted); padding: 12px 20px; font-size: 15px; font-weight: 700; cursor: pointer; transition: 0.2s; position: relative; font-family: inherit; }}
        .actor-tab.active {{ color: var(--text); }}
        .actor-tab.active::after {{ content: ''; position: absolute; bottom: -2px; left: 0; right: 0; height: 2px; background: var(--accent); }}
        .actor-panel {{ display: none; }}
        .actor-panel.active {{ display: block; }}
        .gallery-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }}
        .gallery-item {{ width: 100%; height: 180px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); }}
    </style>

    <div class="main" style="padding-top:30px; max-width:1100px; margin: 0 auto; padding-left:20px; padding-right:20px;">
        <div style="margin-bottom:15px;"><a href="/actors" style="color:var(--muted); text-decoration:none; font-size:14px; font-weight:700;">← Back to Catalog</a></div>
        <div style="display:flex; gap:25px; background:var(--card); border:1px solid var(--border); padding:25px; border-radius:12px; margin-bottom:35px; flex-wrap:wrap;">
            <div style="width:160px; height:220px; background:var(--bg3); border-radius:8px; overflow:hidden; border:1px solid var(--border); flex-shrink:0;">
                <img src="/api/actor/photo?id={actor_id}" style="width:100%; height:100%; object-fit:cover;">
            </div>
            <div style="flex:1; min-width:300px; display:flex; flex-direction:column; justify-content:center;">
                <h1 style="font-size:32px; font-weight:900; color:var(--text); margin-bottom:6px;">{actor_name}</h1>
                <div style="font-size:12px; color:var(--accent); font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:12px;">🌟 Superstar Profile</div>
                <p style="color:var(--muted); font-size:14px; line-height:1.6; max-width:700px;">Managed by Fast Finder Core Engine.</p>
            </div>
        </div>

        <div class="actor-tab-bar">
            <button class="actor-tab active" onclick="switchActorTab(event, 'tab-info')">ℹ️ Info</button>
            <button class="actor-tab" onclick="switchActorTab(event, 'tab-video')">🎬 Video ({len(video_docs) if video_docs else 0})</button>
            <button class="actor-tab" onclick="switchActorTab(event, 'tab-gallery')">🖼️ Gallery</button>
        </div>

        <div id="tab-info" class="actor-panel active">
            <div style="background:var(--card); border:1px solid var(--border); padding:25px; border-radius:8px; line-height:1.7; color:var(--text); font-size:15px; white-space:pre-line;">
                {actor["bio"]}
            </div>
        </div>

        <div id="tab-video" class="actor-panel">
            {grid_html}
        </div>

        <div id="tab-gallery" class="actor-panel">
            <div class="gallery-grid">
                <img src="/api/actor/photo?id={actor_id}" class="gallery-item">
            </div>
        </div>
    </div>

    <script>
        function switchActorTab(evt, tabId) {{
            var panels = document.querySelectorAll('.actor-panel');
            for (var i = 0; i < panels.length; i++) {{
                panels[i].classList.remove('active');
            }}
            
            var tabs = document.querySelectorAll('.actor-tab');
            for (var j = 0; j < tabs.length; j++) {{
                tabs[j].classList.remove('active');
            }}
            
            document.getElementById(tabId).classList.add('active');
            evt.currentTarget.classList.add('active');
        }}
    </script>
    '''
    return build_page(f"{actor_name} - Profile", tab_engine_ui, "", "actors", role)
