import io
import gc
import time
import json
import html
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp, get_size
from info import BIN_CHANNEL, MAX_WEB_RESULTS
from database.ia_filterdb import actors, get_actor_search_results, delete_actor_profile, delete_gallery_image_by_index
from web.web_assets import build_page, get_auth, form_wrapper

actor_routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────
# 🎭 PUBLIC VIEW: ACTORS DIRECTORY CATALOG PAGE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actors')
async def actors_directory_page(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
        
    cursor = actors.find({}).sort("created_at", -1)
    all_actors = await cursor.to_list(length=200)
    
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
            # ✅ GRID IMAGE REFRESH OVERRIDE
            v_salt = int(time.time())
            actors_grid_html += f'''
            <div style="background:var(--card); border:1px solid var(--border); border-radius:10px; overflow:hidden; transition:0.2s; cursor:pointer;" onclick="window.location.href='/actor/{act_id}'">
                <div style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">
                    <img src="/api/actor/photo?id={act_id}&v={v_salt}" style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover;" loading="lazy">
                </div>
                <div style="padding:12px; text-align:center;">
                    <div style="font-size:14px; font-weight:700; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{html.escape(act.get('name', ''))}</div>
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
    if role != 'admin': return web.HTTPFound('/dashboard')
        
    content = f'''
    <form action="/api/create_actor" method="post" enctype="multipart/form-data">
        <input type="text" name="name" placeholder="Actor Full Name (e.g., Shah Rukh Khan)" required>
        <textarea name="bio" placeholder="Actor Biography / Details..." style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; min-height:100px; outline:none; margin-bottom:15px; font-family:inherit;" required></textarea>
        
        <div class="scard-label" style="margin-bottom:4px; color:var(--muted);">Search Tags (Comma Separated)</div>
        <input type="text" name="tags" placeholder="e.g. SRK, Shahrukh, King Khan" style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; margin-bottom:15px; outline:none;">

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
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
        
    try:
        reader = await req.multipart()
        name, bio, tags_raw, image_bytes = None, None, "", None
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == 'name': name = (await part.read()).decode().strip()
            elif part.name == 'bio': bio = (await part.read()).decode().strip()
            elif part.name == 'tags': tags_raw = (await part.read()).decode().strip()
            elif part.name == 'photo': image_bytes = await part.read()

        if not name or not bio or not image_bytes:
            return web.HTTPFound('/admin/create_actor?err=All fields are required!')

        tags_list = [t.strip() for t in tags_raw.split(",") if t.strip()]

        with io.BytesIO(image_bytes) as img_buffer:
            img_buffer.name = f"{name.replace(' ', '_')}.jpg"
            msg = await temp.BOT.send_photo(chat_id=BIN_CHANNEL, photo=img_buffer)

        if not msg or not msg.photo: return web.HTTPFound('/admin/create_actor?err=Telegram Upload Failed!')
        tg_photo_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
        
        actor_doc = {
            "name": name,
            "bio": bio,
            "tags": tags_list,
            "photo_url": f"TG_ID:{tg_photo_id}",
            "social_links": {"instagram": "", "youtube": "", "twitter": "", "other": ""},
            "gallery": [],
            "created_at": time.time()
        }
        await actors.insert_one(actor_doc)
        return web.HTTPFound('/actors?msg=Actor Profile created successfully!')
    except Exception as e:
        return web.HTTPFound(f'/admin/create_actor?err=Server Error: {str(e)}')

# ─────────────────────────────────────────────────────────
# 🖼️ ZERO-RAM GENERAL PHOTO ENGINE (CACHE BUSTER UPGRADE)
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/photo')
async def get_actor_photo(req):
    actor_id = req.query.get("id")
    img_index = req.query.get("gallery_idx")
    if not actor_id: return web.Response(status=400)
    
    try:
        doc = await actors.find_one({"_id": ObjectId(actor_id)})
        if not doc: return web.Response(status=404)
        
        if img_index is not None:
            idx = int(img_index)
            raw_url = doc.get("gallery", [])[idx]
        else:
            raw_url = doc.get("photo_url")
            
        if not raw_url or not raw_url.startswith("TG_ID:"): return web.Response(status=404)
        tg_id = raw_url.replace("TG_ID:", "")
        
        file_data = await temp.BOT.download_media(tg_id, in_memory=True)
        if not file_data: return web.Response(status=404)
        
        body_bytes = file_data.getvalue()
        file_data.close()
        del file_data
        
        # ✅ HARD REFRESH FIX: ब्राउज़र कैशे को ब्लॉक करने वाले हेडर इंजेक्ट किए गए
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Disposition": 'inline; filename="photo.jpg"'
        }
        return web.Response(body=body_bytes, content_type="image/jpeg", headers=headers)
    except Exception: return web.Response(status=500)
    finally: gc.collect()

# ─────────────────────────────────────────────────────────
# 🌐 PUBLIC VIEW: ACTOR PROFILE MASTER INTERFACE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actor/{id}')
async def actor_profile_display(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    
    try:
        actor_id = req.match_info['id']
        actor = await actors.find_one({"_id": ObjectId(actor_id)})
        if not actor: return web.Response(text="Actor Not Found", status=404)
    except: return web.Response(text="Invalid ID", status=400)
        
    actor_name = actor["name"]
    tags_list = actor.get("tags", [])
    social = actor.get("social_links", {"instagram": "", "youtube": "", "twitter": "", "other": ""})
    gallery_list = actor.get("gallery", [])
    
    tags_chips_html = '<div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:8px;">'
    for tag in tags_list:
        tags_chips_html += f'<span style="background:var(--bg3); border:1px solid var(--border); color:var(--muted); font-size:11px; padding:3px 8px; border-radius:4px; font-weight:600;">#{html.escape(tag)}</span>'
    tags_chips_html += '</div>'

    social_html = '<div style="display:flex; gap:12px; margin-top:12px; flex-wrap:wrap;">'
    if social.get("instagram"): social_html += f'<a href="{html.escape(social["instagram"])}" target="_blank" style="background:#ff007f; color:#fff; padding:6px 14px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:700;">📸 Instagram</a>'
    if social.get("youtube"): social_html += f'<a href="{html.escape(social["youtube"])}" target="_blank" style="background:#ff0000; color:#fff; padding:6px 14px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:700;">📺 YouTube</a>'
    if social.get("twitter"): social_html += f'<a href="{html.escape(social["twitter"])}" target="_blank" style="background:#1da1f2; color:#fff; padding:6px 14px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:700;">🐦 Twitter / X</a>'
    if social.get("other"): social_html += f'<a href="{html.escape(social["other"])}" target="_blank" style="background:var(--bg4); color:#fff; border:1px solid var(--border); padding:6px 14px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:700;">🌐 Other Link</a>'
    social_html += '</div>'

    gallery_grid_html = ""
    if role == 'admin':
        gallery_grid_html += f'''
        <div style="background:var(--card); border:1px dashed var(--border); padding:20px; border-radius:8px; text-align:center; margin-bottom:20px;">
            <form id="galleryForm" action="/api/actor/gallery_upload" method="post" enctype="multipart/form-data" style="margin:0;">
                <input type="hidden" name="actor_id" value="{actor_id}">
                <label style="background:var(--accent); color:#fff; padding:10px 20px; border-radius:6px; font-weight:700; cursor:pointer; font-size:13px; display:inline-block;">
                    📂 Add Multiple Images to Gallery
                    <input type="file" name="gallery_img" accept="image/*" multiple style="display:none;" onchange="submitGalleryForm()">
                </label>
            </form>
        </div>
        '''
    if not gallery_list:
        gallery_grid_html += '<div style="color:var(--muted); text-align:center; padding:40px;"> 🖼️ Gallery is empty. Upload images to show here.</div>'
    else:
        gallery_grid_html += '<div class="gallery-grid">'
        for i in range(len(gallery_list)):
            admin_img_actions = f'<button class="gal-del-btn" onclick="deleteGalleryImg(\'{actor_id}\', {i})">&#128465;</button>' if role == 'admin' else ""
            gallery_grid_html += f'''
            <div class="gallery-item-wrapper">
                <img src="/api/actor/photo?id={actor_id}&gallery_idx={i}" class="gallery-item" loading="lazy">
                {admin_img_actions}
            </div>
            '''
        gallery_grid_html += '</div>'

    admin_edit_btn = ""
    if role == 'admin':
        admin_edit_btn = f'''
        <div style="display:flex; gap:10px; margin-top:12px; flex-wrap:wrap;">
            <button onclick="openActorEditModal()" style="background:var(--bg4); border:1px solid var(--border); color:var(--text); padding:8px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer;">✏️ Edit Profile & Socials</button>
            <button onclick="deleteActorProfileMaster('{actor_id}')" style="background:rgba(160,8,8,.78); border:1px solid rgba(229,9,20,.45); color:#fff; padding:8px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer;">🗑️ Delete Profile</button>
        </div>
        '''
    
    tags_json_payload = html.escape(json.dumps(tags_list))
    safe_bio = html.escape(actor.get("bio", ""))

    # ✅ MASTER LIVE DYNAMIC TIME STAMP CACHE BUSTER
    cache_salt = int(time.time())

    tab_engine_ui = f'''
    <style>
        .actor-tab-bar {{ display: flex; gap: 10px; border-bottom: 2px solid var(--border); margin-bottom: 25px; }}
        .actor-tab {{ background: transparent; border: none; color: var(--muted); padding: 12px 20px; font-size: 15px; font-weight: 700; cursor: pointer; transition: 0.2s; position: relative; font-family: inherit; }}
        .actor-tab.active {{ color: var(--text) !important; }}
        .actor-tab.active::after {{ content: ''; position: absolute; bottom: -2px; left: 0; right: 0; height: 2px; background: var(--accent); }}
        .actor-panel {{ display: none; }}
        .actor-panel.active {{ display: block !important; }}
        
        .actor-hero-box {{ display:flex; gap:25px; background:var(--card); border:1px solid var(--border); padding:25px; border-radius:12px; margin-bottom:35px; flex-wrap:wrap; }}
        .profile-img-wrap {{ width:240px; height:240px; background:var(--bg3); border-radius:12px; overflow:hidden; border:1px solid var(--border); flex-shrink:0; position:relative; }}
        .profile-img-wrap img {{ width:100%; height:100%; object-fit:cover; }}
        @media(max-width: 600px) {{ .profile-img-wrap {{ width:100%; height:300px; }} }}

        .gallery-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }}
        .gallery-item-wrapper {{ position: relative; width: 100%; aspect-ratio: 1; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }}
        .gallery-item {{ width: 100%; height: 100%; object-fit: cover; transition: transform 0.2s; }}
        .gallery-item-wrapper:hover .gallery-item {{ transform: scale(1.03); }}
        
        .gal-del-btn {{ position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,0.7); border: 1px solid rgba(255,255,255,0.2); color: #fff; width: 32px; height: 32px; border-radius: 6px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: 0.2s; z-index: 5; }}
        .gal-del-btn:hover {{ background: #e50914; border-color: #e50914; }}

        .edit-modal {{ position: fixed; inset: 0; background: rgba(0,0,0,.85); z-index: 200; display: none; align-items: center; justify-content: center; overflow-y: auto; padding: 20px 10px; }}
        .edit-modal.open {{ display: flex !important; }}
        .em-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 25px; width: 100%; max-width: 480px; box-shadow: 0 10px 30px rgba(0,0,0,.5); position: relative; margin: auto; }}
        
        .upload-overlay {{ position: fixed; inset:0; background: rgba(0,0,0,0.85); z-index: 9999; display: none; flex-direction: column; align-items: center; justify-content: center; color: #fff; }}
        .upload-overlay.show {{ display: flex !important; }}
        .progress-box {{ width: 80%; max-width: 300px; height: 6px; background: var(--bg4); border-radius: 3px; overflow: hidden; margin-top: 15px; }}
        .progress-bar {{ width: 0%; height: 100%; background: var(--accent); transition: width 0.4s ease; }}
    </style>

    <div id="uploadNotificationOverlay" class="upload-overlay">
        <div class="spinner" style="width:48px; height:48px; border:4px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:spin .8s linear infinite;"></div>
        <div style="margin-top: 20px; font-weight: 700; font-size: 16px; letter-spacing: 0.5px;" id="uploadOverlayText">वेट करें, आपका फोटो अपलोड हो रहा है...</div>
        <div class="progress-box"><div id="uploadProgressBar" class="progress-bar"></div></div>
    </div>

    <div class="main" style="padding-top:30px; max-width:1100px; margin: 0 auto; padding-left:20px; padding-right:20px;">
        <div style="margin-bottom:15px;"><a href="/actors" style="color:var(--muted); text-decoration:none; font-size:14px; font-weight:700;">← Back to Catalog</a></div>
        
        <div class="actor-hero-box">
            <div class="profile-img-wrap">
                <img src="/api/actor/photo?id={actor_id}&v={cache_salt}">
            </div>
            <div style="flex:1; min-width:300px; display:flex; flex-direction:column; justify-content:center;">
                <h1 style="font-size:32px; font-weight:900; color:var(--text); margin-bottom:2px;">{html.escape(actor_name)}</h1>
                {tags_chips_html}
                {social_html}
                {admin_edit_btn}
            </div>
        </div>

        <div class="actor-tab-bar">
            <button class="actor-tab active" onclick="switchActorTab(this, 'tab-info')">ℹ️ Info</button>
            <button class="actor-tab" onclick="switchActorTab(this, 'tab-video')">🎬 Video</button>
            <button class="actor-tab" onclick="switchActorTab(this, 'tab-gallery')">🖼️ Gallery</button>
        </div>

        <div id="tab-info" class="actor-panel active">
            <div style="background:var(--card); border:1px solid var(--border); padding:25px; border-radius:8px; line-height:1.7; color:var(--text); font-size:15px; white-space:pre-line;">
                {safe_bio}
            </div>
        </div>

        <div id="tab-video" class="actor-panel">
            <div style="display:flex; gap:10px; margin-bottom:20px; flex-wrap:wrap; align-items:center;">
                <div style="flex:1; min-width:200px; display:flex; background:var(--bg3); border:1px solid var(--border); border-radius:8px; padding:0 12px; align-items:center;">
                    <input type="text" id="actor_movie_q" value="" placeholder="Search inside actor movies..." style="width:100%; background:transparent; border:none; padding:10px 0; color:var(--text); outline:none; font-size:14px; font-weight:600;">
                </div>
                <select id="actor_col_sel" onchange="resetActorSearchPage()" style="background:var(--bg3); color:var(--text); border:1px solid var(--border); padding:10px 14px; border-radius:8px; font-weight:700; outline:none; cursor:pointer;">
                    <option value="all">📂 All Collections</option>
                    <option value="primary">🟢 Primary</option>
                    <option value="cloud">🔵 Cloud</option>
                    <option value="archive">🟠 Archive</option>
                </select>
                <select id="actor_mode_sel" onchange="resetActorSearchPage()" style="background:var(--bg3); color:var(--text); border:1px solid var(--border); padding:10px 14px; border-radius:8px; font-weight:700; outline:none; cursor:pointer;">
                    <option value="tg">🖼️ Original TG Thumb</option>
                    <option value="none">⚡ Text Only (Fastest)</option>
                </select>
                <button onclick="triggerActorSearchAjax()" style="background:var(--accent); color:#fff; border:none; padding:11px 24px; border-radius:8px; font-weight:700; cursor:pointer;">Filter</button>
            </div>

            <div id="actor_video_results" class="res-grid"></div>
            
            <div class="pagination" id="actor_page_box" style="display:none; justify-content:center; gap:12px; margin-top:20px;">
                <button class="pg-btn" id="actor_pBtn" onclick="actorPagePrev()">Previous</button>
                <span class="pg-info" id="actor_pgInfo">Page 1</span>
                <button class="pg-btn" id="actor_nBtn" onclick="actorPageNext()">Next</button>
            </div>
        </div>

        <div id="tab-gallery" class="actor-panel">
            {gallery_grid_html}
        </div>
    </div>

    <input type="hidden" id="actor_master_tags_payload" value="{tags_json_payload}">

    <div class="edit-modal" id="actorEditModal" onclick="if(event.target===this)closeActorEditModal()">
        <div class="em-card">
            <button class="em-close" onclick="closeActorEditModal()" style="position:absolute; top:15px; right:20px; background:none; border:none; color:var(--muted); font-size:24px; cursor:pointer;">&#10005;</button>
            <div class="em-title" style="font-size:18px; font-weight:700; margin-bottom:20px; color:var(--text);">✏️ Edit Actor Profile Matrix</div>
            <form id="actorUpdateForm" onsubmit="submitActorProfileForm(event)">
                <input type="hidden" name="actor_id" value="{actor_id}">
                
                <div class="scard-label">Actor Full Name</div>
                <input type="text" name="name" value="{html.escape(actor_name)}" class="em-input" required>
                
                <div class="scard-label">Biography Details</div>
                <textarea name="bio" class="em-input" style="min-height:100px; font-family:inherit; line-height:1.5;" required>{safe_bio}</textarea>
                
                <div class="scard-label">Search Tags (Comma Separated)</div>
                <input type="text" name="tags" value="{html.escape(', '.join(tags_list))}" placeholder="e.g. SRK, Shahrukh, King Khan" class="em-input">

                <div class="scard-label" style="color:var(--accent); font-weight:700;">🔄 Change Profile Photo (Optional)</div>
                <input type="file" name="change_photo" accept="image/*" class="em-input" style="border:1px dashed var(--border); background:var(--bg3);">

                <div class="em-title" style="font-size:14px; margin-top:15px; margin-bottom:10px; color:var(--text);">🌐 Social Media Channels Matrix</div>
                
                <div class="scard-label">Instagram Link</div>
                <input type="url" name="insta" value="{html.escape(social.get('instagram',''))}" placeholder="https://instagram.com/..." class="em-input">
                
                <div class="scard-label">YouTube Channel Link</div>
                <input type="url" name="yt" value="{html.escape(social.get('youtube',''))}" placeholder="https://youtube.com/..." class="em-input">
                
                <div class="scard-label">Twitter / X Profile Link</div>
                <input type="url" name="twitter" value="{html.escape(social.get('twitter',''))}" placeholder="https://x.com/..." class="em-input">
                
                <div class="scard-label">🔗 Other Website / Channel Link</div>
                <input type="url" name="other" value="{html.escape(social.get('other',''))}" placeholder="https://external-network.com/..." class="em-input">
                
                <button class="em-save-btn" type="submit" style="width:100%; background:var(--accent); color:#fff; border:none; padding:14px; font-weight:700; border-radius:6px; cursor:pointer;">Save Changes & Sync Grid</button>
            </form>
        </div>
    </div>

    <script>
        var actCurPage = 1, actOffset = 0, actNextOffset = "";
        var actLimit = 21;

        function switchActorTab(btn, tabId) {{
            var panels = document.querySelectorAll('.actor-panel');
            for (var i = 0; i < panels.length; i++) {{ panels[i].classList.remove('active'); }}
            var tabs = document.querySelectorAll('.actor-tab');
            for (var j = 0; j < tabs.length; j++) {{ tabs[j].classList.remove('active'); }}
            
            document.getElementById(tabId).classList.add('active');
            btn.classList.add('active');
            if(tabId === 'tab-video' && document.getElementById('actor_video_results').innerHTML === "") {{
                triggerActorSearchAjax();
            }}
            localStorage.setItem('actor_active_tab', tabId);
        }}

        document.addEventListener("DOMContentLoaded", function() {{
            var savedTab = localStorage.getItem('actor_active_tab');
            if(savedTab && document.getElementById(savedTab)) {{
                var targetBtn = document.querySelector('[onclick*="'+savedTab+'"]');
                if(targetBtn) targetBtn.click();
            }}
        }});

        function openActorEditModal() {{ document.getElementById('actorEditModal').classList.add('open'); }}
        function closeActorEditModal() {{ document.getElementById('actorEditModal').classList.remove('open'); }}
        function resetActorSearchPage() {{ actCurPage = 1; actOffset = 0; }}

        // MULTI-UPLOAD PROGRESS NOTIFICATION PIPELINE
        async function submitGalleryForm() {{
            var form = document.getElementById('galleryForm');
            var input = form.querySelector('input[type="file"]');
            if(!input.files.length) return;

            var overlay = document.getElementById('uploadNotificationOverlay');
            var pBar = document.getElementById('uploadProgressBar');
            var oText = document.getElementById('uploadOverlayText');
            
            overlay.classList.add('show');
            oText.innerText = "वेट करें, आपकी तस्वीरें गैलरी में अपलोड हो रही हैं...";
            pBar.style.width = "10%";

            var formData = new FormData(form);
            formData.delete('gallery_img');
            for (var i = 0; i < input.files.length; i++) {{
                formData.append('gallery_img', input.files[i]);
            }}
            pBar.style.width = "40%";

            try {{
                var res = await fetch(form.action, {{ method: 'POST', body: formData }});
                pBar.style.width = "80%";
                if(res.ok) {{
                    pBar.style.width = "100%";
                    oText.innerText = "🎉 सक्सेसफुल! स्टार गैलरी सिंक हो गई है।";
                    setTimeout(function() {{
                        overlay.classList.remove('show');
                        localStorage.setItem('actor_active_tab', 'tab-gallery');
                        window.location.reload();
                    }}, 1000);
                }} else {{
                    alert("Upload packet node failure.");
                    overlay.classList.remove('show');
                }}
            }} catch(e) {{
                alert("Server pipeline error.");
                overlay.classList.remove('show');
            }}
        }}

        // PROFILE FORM EDIT WITH NOTIFICATION LOGIC
        async function submitActorProfileForm(event) {{
            event.preventDefault();
            var form = document.getElementById('actorUpdateForm');
            var overlay = document.getElementById('uploadNotificationOverlay');
            var pBar = document.getElementById('uploadProgressBar');
            var oText = document.getElementById('uploadOverlayText');

            closeActorEditModal();
            overlay.classList.add('show');
            oText.innerText = "मेटाडाटा और प्रोफाइल फोटो सिंक हो रही है, थोड़ा वेट करें...";
            pBar.style.width = "30%";

            var formData = new FormData(form);
            pBar.style.width = "65%";

            try {{
                var res = await fetch('/api/actor/update_profile', {{ method: 'POST', body: formData }});
                pBar.style.width = "90%";
                if(res.ok) {{
                    pBar.style.width = "100%";
                    oText.innerText = "🎉 सक्सेसफुल! प्रोफाइल डिटेल्स अपडेट हो गई हैं।";
                    setTimeout(function() {{
                        overlay.classList.remove('show');
                        window.location.reload();
                    }}, 1000);
                }} else {{
                    alert("Profile update failed.");
                    overlay.classList.remove('show');
                }}
            }} catch(e) {{
                alert("Network matrix crash.");
                overlay.classList.remove('show');
            }}
        }}

        // PURGE WHOLE PROFILE AJAX
        async function deleteActorProfileMaster(actorId) {{
            if(!confirm("⚠️ क्या आप सचमुच इस एक्टर की पूरी प्रोफाइल और गैलरी डेटाबेस से हमेशा के लिए डिलीट करना चाहते हैं?")) return;
            try {{
                var r = await fetch('/api/actor/delete_profile?id=' + actorId, {{ method: 'POST' }});
                var res = await r.json();
                if(res.success) {{
                    alert("🎭 एक्टर प्रोफाइल सफलतापूर्वक डिलीट कर दी गई है।");
                    window.location.href = '/actors';
                }} else {{ alert("Delete execution failed."); }}
            }} catch(e) {{ alert("Database response error."); }}
        }}

        // PURGE SINGLE GALLERY IMAGE AJAX
        async function deleteGalleryImg(actorId, idx) {{
            if(!confirm("क्या आप इस तस्वीर को गैलरी से हटाना चाहते हैं?")) return;
            try {{
                var r = await fetch('/api/actor/delete_gallery_img?id=' + actorId + '&idx=' + idx, {{ method: 'POST' }});
                var res = await r.json();
                if(res.success) {{
                    localStorage.setItem('actor_active_tab', 'tab-gallery');
                    window.location.reload();
                }} else {{ alert("Image purge execution failed."); }}
            }} catch(e) {{ alert("Server response error."); }}
        }}

        async function triggerActorSearchAjax() {{
            var q = document.getElementById('actor_movie_q').value.trim();
            var col = document.getElementById('actor_col_sel').value;
            var mode = document.getElementById('actor_mode_sel').value;
            var grid = document.getElementById('actor_video_results');
            
            grid.className = 'res-grid mode-' + mode;
            grid.innerHTML = '<div class="spin-wrap"><div class="spinner"></div><span>Filtering Cross-Network Matrix...</span></div>';
            
            try {{
                var targetUrl = '/api/actor/search?q=' + encodeURIComponent(q) + '&offset=' + actOffset + '&col=' + col + '&mode=' + mode + '&id={actor_id}';
                var r = await fetch(targetUrl);
                var d = await r.json();
                if(!d.results || !d.results.length) {{
                    grid.innerHTML = '<div class="empty"><p>No video assets matching filters found inside database.</p></div>';
                    document.getElementById('actor_page_box').style.display = 'none';
                    return;
                }}
                var h = '';
                d.results.forEach(function(f) {{
                    var sc = (f.source || 'primary').toLowerCase();
                    if(!['primary','cloud','archive'].includes(sc)) sc = 'primary';
                    var posterHtml = '';
                    if(mode !== 'none') {{
                        posterHtml = '<div class="poster-box"><img src="'+f.tg_thumb+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" loading="lazy"><div class="poster-top"><span class="type-chip">'+f.type.toUpperCase()+'</span><span class="size-chip">'+f.size+'</span><span class="source-pill '+sc+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span></div></div>';
                    }} else {{
                        posterHtml = '<div class="fc-text-info"><span class="tc-type">'+f.type.toUpperCase()+'</span><span class="tc-size">'+f.size+'</span><span class="source-pill '+sc+'" style="margin-left:auto"><span class="source-dot"></span>'+sc.toUpperCase()+'</span></div>';
                    }}
                    h += '<div class="file-card">' + posterHtml + '<div class="fc-body"><div class="fc-name" onclick="window.open(\\'\\'+f.watch+\\'\\',\\'_blank\\')">'+f.name+'</div></div></div>';
                }});
                grid.innerHTML = h;
                actNextOffset = d.next_offset;
                document.getElementById('actor_page_box').style.display = 'flex';
                document.getElementById('actor_pBtn').disabled = (actOffset === 0);
                document.getElementById('actor_nBtn').disabled = !actNextOffset;
                document.getElementById('actor_pgInfo').textContent = 'Page ' + actCurPage;
            }} catch(e) {{
                grid.innerHTML = '<div class="empty"><p>Matrix pipeline sync timeout error.</p></div>';
            }}
        }}

        function actorPageNext() {{ if(actNextOffset) {{ actCurPage++; actOffset = actNextOffset; triggerActorSearchAjax(); window.scrollTo(0,350); }} }}
        function actorPagePrev() {{ if(actCurPage > 1) {{ actCurPage--; actOffset = Math.max(0, actOffset - actLimit); triggerActorSearchAjax(); window.scrollTo(0,350); }} }}
        
        document.getElementById('actor_movie_q').addEventListener('keydown', function(e) {{ if(e.key === 'Enter') {{ resetActorSearchPage(); triggerActorSearchAjax(); }} }});
    </script>
    '''
    return build_page(f"{actor_name} - Profile Matrix", tab_engine_ui, "", "actors", role)

# ─────────────────────────────────────────────────────────
# ⚙️ ADMIN API: DYNAMIC AJAX OR SEARCH PIPELINE FOR ACTOR PAGE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/search')
async def api_actor_search_handler(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"error": "Unauthorized"}, status=403)
    
    actor_id = req.query.get("id")
    q_custom = req.query.get("q", "").strip()
    off = req.query.get("offset", "0")
    col = req.query.get("col", "all").lower()
    mode = req.query.get("mode", "tg").lower()
    
    if not actor_id: return web.json_response({"results": []})
    try: off = max(0, int(off))
    except: off = 0
        
    actor = await actors.find_one({"_id": ObjectId(actor_id)})
    if not actor: return web.json_response({"results": []})
    
    tags_list = actor.get("tags", [])
    
    if not q_custom:
        search_query = ""
        passing_tags = tags_list
    else:
        search_query = q_custom
        passing_tags = tags_list
    
    lim = 21
    all_m, next_offset = await get_actor_search_results(
        search_query, passing_tags, max_results=lim, offset=off, collection_type=col
    )
    
    results_list = []
    for d in all_m:
        fid = d.get("file_ref") or d.get("_id")
        db_id = d.get("_id")
        source_col = d.get("source_col", "primary")
        
        raw_thumb = d.get("thumb_url", "")
        v_salt = raw_thumb[-8:] if (raw_thumb and raw_thumb.startswith("TG_ID:")) else "0"
        tg_thumb = f"/api/thumb?file_id={db_id}&col={source_col}&v={v_salt}"
        
        results_list.append({
            "file_id": db_id,
            "name": d.get("file_name", "Unknown File"),
            "size": get_size(d.get("file_size", 0)),
            "type": d.get("file_type", "document").upper(),
            "source": source_col.lower(),
            "tg_thumb": tg_thumb,
            "watch": f"/setup_stream?file_id={fid}&mode=watch"
        })
        
    return web.json_response({"results": results_list, "next_offset": next_offset})

# ─────────────────────────────────────────────────────────
# ⚙️ ADMIN API: UPDATE PROFILE DETAILS & SOCIAL MEDIA CHANNELS
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/update_profile')
async def api_actor_update_profile(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    try:
        reader = await req.multipart()
        actor_id, name, bio, tags_raw = None, None, None, ""
        insta, yt, twitter, other = "", "", "", ""
        change_photo_bytes = None

        while True:
            part = await reader.next()
            if part is None: break
            if part.name == 'actor_id': actor_id = (await part.read()).decode().strip()
            elif part.name == 'name': name = (await part.read()).decode().strip()
            elif part.name == 'bio': bio = (await part.read()).decode().strip()
            elif part.name == 'tags': tags_raw = (await part.read()).decode().strip()
            elif part.name == 'insta': insta = (await part.read()).decode().strip()
            elif part.name == 'yt': yt = (await part.read()).decode().strip()
            elif part.name == 'twitter': twitter = (await part.read()).decode().strip()
            elif part.name == 'other': other = (await part.read()).decode().strip()
            elif part.name == 'change_photo': change_photo_bytes = await part.read()

        if not actor_id or not name or not bio: 
            return web.json_response({"error": "Missing critical fields"}, status=400)
        
        tags_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
        
        update_doc = {
            "name": name,
            "bio": bio,
            "tags": tags_list,
            "social_links": {"instagram": insta, "youtube": yt, "twitter": twitter, "other": other}
        }
        
        # ✅ PROFILE PHOTO UPDATE TRIGGER: नई प्रोफाइल फोटो अपलोड को प्रोसेस करें
        if change_photo_bytes and len(change_photo_bytes) > 10:
            with io.BytesIO(change_photo_bytes) as img_buffer:
                img_buffer.name = f"avatar_{actor_id}.jpg"
                msg = await temp.BOT.send_photo(chat_id=BIN_CHANNEL, photo=img_buffer)
            if msg and msg.photo:
                tg_photo_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
                update_doc["photo_url"] = f"TG_ID:{tg_photo_id}"

        await actors.update_one({"_id": ObjectId(actor_id)}, {"$set": update_doc})
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# ─────────────────────────────────────────────────────────
# 🖼️ ADMIN API: UPLOAD NATIVE IMAGE TO GALLERY (MULTI-SUPPORT)
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/gallery_upload')
async def api_actor_gallery_upload(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    actor_id = None
    try:
        reader = await req.multipart()
        uploaded_tg_ids = []
        
        while True:
            part = await reader.next()
            if part is None: break
            
            if part.name == 'actor_id':
                actor_id = (await part.read()).decode().strip()
            elif part.name == 'gallery_img':
                img_bytes = await part.read()
                if img_bytes and len(img_bytes) > 10:
                    with io.BytesIO(img_bytes) as img_buffer:
                        img_buffer.name = f"gal_{int(time.time())}.jpg"
                        msg = await temp.BOT.send_photo(chat_id=BIN_CHANNEL, photo=img_buffer)
                    if msg and msg.photo:
                        tg_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
                        uploaded_tg_ids.append(f"TG_ID:{tg_id}")
            
        if not actor_id or not uploaded_tg_ids:
            return web.json_response({"error": "No assets packet uploaded"}, status=400)
        
        await actors.update_one(
            {"_id": ObjectId(actor_id)}, 
            {"$push": {"gallery": {"$each": uploaded_tg_ids}}}
        )
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# ─────────────────────────────────────────────────────────
# 🗑️ ADMIN API: PURGE INDIVIDUAL GALLERY IMAGE
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/delete_gallery_img')
async def api_delete_gallery_image(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    actor_id = req.query.get("id")
    idx = req.query.get("idx")
    if not actor_id or idx is None: return web.json_response({"error": "Missing params"}, status=400)
    
    success = await delete_gallery_image_by_index(actor_id, int(idx))
    return web.json_response({"success": success})

# ─────────────────────────────────────────────────────────
# 🗑️ ADMIN API: PURGE WHOLE ACTOR PROFILE
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/delete_profile')
async def api_delete_actor_profile(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    actor_id = req.query.get("id")
    if not actor_id: return web.json_response({"error": "Missing ID"}, status=400)
    
    success = await delete_actor_profile(actor_id)
    return web.json_response({"success": success})
