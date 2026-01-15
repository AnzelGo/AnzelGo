# ==========================================
# DEFINITIVO IMPORTACIONES GLOBALES
# ==========================================
import os
import asyncio
import aiohttp
import nest_asyncio
import time
import uuid
import json
import subprocess
import shutil
import psutil
import re
import logging
import ffmpeg
from threading import Thread
from flask import Flask

from pyrogram import Client, filters, idle
from pyrogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, Message
)
from pyrogram.errors import MessageNotModified, FloodWait
from yt_dlp import YoutubeDL

# Aplicar nest_asyncio para permitir bucles anidados
nest_asyncio.apply()

# Configuración desde variables de entorno
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# AGREGAS ESTA LÍNEA para "importar" tu ID desde la configuración de Kaggle
ADMIN_ID = int(os.getenv("ADMIN_ID")) 

# Inicialización de las 4 apps con Workers aumentados para evitar bloqueos
app1 = Client("bot1", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT1_TOKEN"), workers=50)
app2 = Client("bot2", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT2_TOKEN"), workers=50)
app3 = Client("bot3", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT3_TOKEN"), workers=50)
app4 = Client("bot4", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT4_TOKEN"), workers=50)


# ==========================================
# ⚙️ CONFIGURACIÓN Y ESTADO GLOBAL (ESTILO REFERENCIA)
# ==========================================

CONFIG_FILE = "system_config.json"
ADMIN_ID = int(os.getenv("ADMIN_ID", "12345678")) # Asegúrate que esto cargue tu ID real

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("mode", "OFF"), data.get("allowed", [])
        except: return "OFF", []
    return "OFF", []

def save_config():
    data = {"mode": SYSTEM_MODE, "allowed": ALLOWED_USERS}
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

# --- VARIABLES GLOBALES (Igual que tu código funcional) ---
SYSTEM_MODE, ALLOWED_USERS = load_config() # Modos: "ON", "OFF", "PRIVATE"
WAITING_FOR_ID = False
VIEWING_LIST = False
PANEL_MSG_ID = None

# ==========================================
# 🛡️ LÓGICA DE PERMISOS CONECTADA AL PANEL
# ==========================================

async def check_permissions(client, update):
    if isinstance(update, Message):
        user_id = update.from_user.id
        chat_type = update.chat.type.value
        reply_method = update.reply_text
    elif isinstance(update, CallbackQuery):
        user_id = update.from_user.id
        chat_type = update.message.chat.type.value
        reply_method = update.answer
    else:
        return False

    if user_id == ADMIN_ID:
        return True

    if SYSTEM_MODE == "OFF":
        msg_off = "⛔ **SISTEMA EN MANTENIMIENTO**\nLos bots están temporalmente fuera de servicio por actualizaciones técnicas."
        if isinstance(update, CallbackQuery):
            await reply_method("⛔ Mantenimiento activo.", show_alert=True)
        elif chat_type == "private":
            await reply_method(msg_off, quote=True)
        return False

    if SYSTEM_MODE == "PRIVATE":
        if user_id not in ALLOWED_USERS:
            texto_solicitud = f"Hola, solicito acceso al bot. Mi ID es: `{user_id}`"
            import urllib.parse
            encoded_text = urllib.parse.quote(texto_solicitud)
            link_soporte = f"https://t.me/AnzZGTv1?text={encoded_text}"
            msg_priv = (
                "🔒 **ACCESO RESTRINGIDO** 🔒\n\n"
                "Este bot está operando en **Modo Privado**.\n"
                "(Prioridad Premium). Actualmente solo usuarios autorizados tienen acceso."
            )
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Solicitar Acceso", url=link_soporte)]])
            if isinstance(update, CallbackQuery):
                await reply_method("🔒 Acceso Denegado (Modo VIP)", show_alert=True)
            elif chat_type == "private":
                if isinstance(update, Message):
                    await update.reply_text(msg_priv, reply_markup=btn, quote=True)
                else:
                    await reply_method(msg_priv, show_alert=True)
            return False

    return True

# ==========================================
# 🎮 CONTROLADOR (BOT 4) - DISEÑO COMPACTO Y NOMBRES
# ==========================================

ADMIN_ID = 1806990534 
PANEL_MSG_ID = None 

def get_panel_menu():
    m_on = "🟢" if SYSTEM_MODE == "ON" else "⚪"
    m_vip = "🔒" if SYSTEM_MODE == "PRIVATE" else "⚪"
    m_off = "🔴" if SYSTEM_MODE == "OFF" else "⚪"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{m_on} ON", callback_data="set_ON"),
         InlineKeyboardButton(f"{m_vip} VIP", callback_data="set_PRIVATE"),
         InlineKeyboardButton(f"{m_off} OFF", callback_data="set_OFF")],
        [InlineKeyboardButton("➕ AGREGAR USUARIO", callback_data="ui_add")],
        [InlineKeyboardButton(f"📋 LISTA AUTORIZADOS ({len(ALLOWED_USERS)})", callback_data="ui_list")]
    ])

def get_panel_text():
    return (
        f"👮‍♂️ <b>SISTEMA DE CONTROL DE ACCESO</b>\n"
        f"<code>──────────────────────</code>\n"
        f"📊 <b>Estado:</b> <code>{SYSTEM_MODE}</code>\n"
        f"👥 <b>Usuarios:</b> <code>{len(ALLOWED_USERS)}</code>\n"
        f"<code>──────────────────────</code>\n"
        f"<i>Gestione los accesos del sistema:</i>"
    )

@app4.on_callback_query(filters.user(ADMIN_ID))
async def controller_callbacks(c, q):
    global SYSTEM_MODE, WAITING_FOR_ID, ALLOWED_USERS, PANEL_MSG_ID
    data = q.data
    PANEL_MSG_ID = q.message.id 

    if data.startswith("set_"):
        new_mode = data.split("_")[1]
        SYSTEM_MODE = new_mode
        save_config()
        await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())
    elif data == "ui_add":
        WAITING_FOR_ID = True
        await q.message.edit_text("✍️ <b>INGRESE ID DEL USUARIO</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 CANCELAR", callback_data="ui_home")]]))
    elif data == "ui_list":
        if not ALLOWED_USERS: return await q.answer("No hay usuarios autorizados.", show_alert=True)
        await q.answer("Cargando nombres...")
        btns = []
        for uid in ALLOWED_USERS:
            try:
                user = await c.get_users(uid)
                name = user.first_name
            except: name = f"ID: {uid}"
            btns.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"del_{uid}")])
        btns.append([InlineKeyboardButton("🔙 VOLVER AL MENÚ", callback_data="ui_home")])
        await q.message.edit_text("📋 <b>USUARIOS CON ACCESO</b>", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("del_"):
        uid = int(data.split("_")[1])
        if uid in ALLOWED_USERS: 
            ALLOWED_USERS.remove(uid)
            save_config()
            await q.answer("Usuario eliminado")
        if ALLOWED_USERS: await controller_callbacks(c, q)
        else: await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())
    elif data == "ui_home":
        WAITING_FOR_ID = False
        await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())

@app4.on_message(filters.user(ADMIN_ID) & filters.private)
async def admin_input_listener(c, m):
    global WAITING_FOR_ID, ALLOWED_USERS, PANEL_MSG_ID
    if WAITING_FOR_ID and m.text and not m.text.startswith("/"):
        try:
            target_id = int("".join(filter(str.isdigit, m.text)))
            if target_id not in ALLOWED_USERS:
                ALLOWED_USERS.append(target_id)
                save_config()
            WAITING_FOR_ID = False
            await m.delete()
            if PANEL_MSG_ID:
                await c.edit_message_text(m.chat.id, PANEL_MSG_ID, get_panel_text(), reply_markup=get_panel_menu())
                return 
        except: pass
    try:
        async for message in c.get_chat_history(m.chat.id, limit=30): await message.delete()
    except: pass
    new_panel = await c.send_message(m.chat.id, get_panel_text(), reply_markup=get_panel_menu())
    PANEL_MSG_ID = new_panel.id

# ==============================================================================
# LÓGICA DEL BOT 1 (UPLOADER)
# ==============================================================================

GOFILE_TOKEN = os.getenv("GOFILE_TOKEN") 
CATBOX_HASH = os.getenv("CATBOX_HASH")
PIXELDRAIN_KEY = os.getenv("PIXELDRAIN_KEY")
user_preference_c1 = {}

async def upload_file_c1(path, server):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'Accept': 'application/json'}
    async with aiohttp.ClientSession(headers=headers) as s:
        with open(path, 'rb') as f:
            if server == "Litterbox":
                data = aiohttp.FormData(); data.add_field('reqtype', 'fileupload'); data.add_field('time', '72h'); data.add_field('fileToUpload', f)
                async with s.post("https://litterbox.catbox.moe/resources/internals/api.php", data=data) as r: return (await r.text()).strip()
            elif server == "Catbox":
                data = aiohttp.FormData(); data.add_field('reqtype', 'fileupload')
                if 'CATBOX_HASH' in globals() and CATBOX_HASH: data.add_field('userhash', CATBOX_HASH.strip())
                data.add_field('fileToUpload', f)
                async with s.post("https://catbox.moe/user/api.php", data=data) as r: return (await r.text()).strip()
            elif server == "GoFile":
                try:
                    async with s.get("https://api.gofile.io/servers") as gs:
                        server_res = await gs.json()
                        server_name = server_res['data']['servers'][0]['name']
                    data = aiohttp.FormData(); data.add_field('file', f, filename=os.path.basename(path))
                    if 'GOFILE_TOKEN' in globals() and GOFILE_TOKEN: data.add_field('token', GOFILE_TOKEN.strip())
                    async with s.post(f"https://{server_name}.gofile.io/contents/uploadfile", data=data) as r:
                        res = await r.json(); return res['data']['downloadPage'] if res['status'] == 'ok' else None
                except: return None
            elif server == "Pixeldrain":
                try:
                    p_key = PIXELDRAIN_KEY.strip() if PIXELDRAIN_KEY else ""
                    auth = aiohttp.BasicAuth(login="", password=p_key)
                    data = aiohttp.FormData(); data.add_field('file', f, filename=os.path.basename(path))
                    async with s.post("https://pixeldrain.com/api/file", data=data, auth=auth) as r:
                        if r.status in [200, 201]:
                            res = await r.json()
                            return f"https://pixeldrain.com/api/file/{res['id']}"
                        else: return None
                except: return None
    return None

def get_fixed_menu_c1():
    return ReplyKeyboardMarkup([[KeyboardButton("🚀 Litterbox"), KeyboardButton("📦 Catbox")], [KeyboardButton("⚡ GoFile"), KeyboardButton("💎 Pixeldrain")]], resize_keyboard=True)

async def progress_bar_c1(current, total, msg, start_time, server_name):
    now = time.time()
    if now - getattr(msg, "last_upd", 0) < 4: return
    msg.last_upd = now
    percentage = current * 100 / total
    bar = "▰" * int(percentage / 10) + "▱" * (10 - int(percentage / 10))
    speed = current / (now - start_time) if (now - start_time) > 0 else 0
    txt = (f"<b>Descargando...</b>\n<code>{bar}</code> {percentage:.1f}%\n📊 <b>Velocidad:</b> <code>{speed/1024**2:.1f} MB/s</code>")
    try: await msg.edit_text(txt)
    except: pass

@app1.on_message(filters.command("start"))
async def start_cmd_c1(_, m):
    if not await check_permissions(_, m): return
    user_preference_c1.pop(m.from_user.id, None)
    await m.reply_text("<b>💎 CLOUD UPLOADER PREMIUM</b>", reply_markup=get_fixed_menu_c1(), quote=True)

@app1.on_message(filters.regex("^(🚀 Litterbox|📦 Catbox|⚡ GoFile|💎 Pixeldrain)$"))
async def set_server_via_btn_c1(_, m):
    user_preference_c1[m.from_user.id] = m.text.split(" ")[1]
    await m.reply_text(f"✅ <b>Servidor configurado:</b> <code>{user_preference_c1[m.from_user.id].upper()}</code>", quote=True)

@app1.on_message(filters.media)
async def handle_media_c1(c, m):
    if not await check_permissions(c, m): return
    user_id = m.from_user.id
    if user_id not in user_preference_c1:
        await m.reply_text("⚠️ Seleccione un servidor primero.", reply_markup=get_fixed_menu_c1(), quote=True); return
    server = user_preference_c1[user_id]
    status = await m.reply_text(f"📤 Preparando archivo...", quote=True)
    path = None
    try:
        path = await c.download_media(m, file_name="./", progress=progress_bar_c1, progress_args=(status, time.time(), server))
        link = await upload_file_c1(path, server)
        if link:
            size_mb = os.path.getsize(path) / (1024**2)
            bot_username = (await c.get_me()).username
            share_link = f"https://t.me/{bot_username}?start=file_{uuid.uuid4().hex[:10]}"
            final_text = (f"𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !\n\n📦 Fɪʟᴇ ꜱɪᴢᴇ : {size_mb:.2f} MiB\n📥 Dᴏᴡɴʟᴏᴀᴅ : <code>{link}</code>\n🔗 Sʜᴀʀᴇ : {share_link}")
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("sᴛʀᴇᴀüm", url=link),InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=link)],[InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="close_all")]])
            await status.edit_text(final_text, reply_markup=keyboard, disable_web_page_preview=True)
        else: await status.edit_text(f"❌ Error al subir a {server}.")
    except Exception as e: await status.edit_text(f"⚠️ Fallo: {str(e)}")
    finally:
        if path and os.path.exists(path): os.remove(path)

@app1.on_callback_query(filters.regex("close_all"))
async def close_callback_c1(c, q):
    try: await q.message.delete(); await q.message.reply_to_message.delete()
    except: pass

# ==============================================================================
# LÓGICA DEL BOT 2 (VIDEO PROCESSOR / ANZEL) - OPTIMIZACIÓN MULTI-HILO
# ==============================================================================

MAX_VIDEO_SIZE_MB_C2 = 4000
DOWNLOAD_DIR_C2 = "downloads"
os.makedirs(DOWNLOAD_DIR_C2, exist_ok=True)
user_data_c2 = {}

app_flask = Flask(__name__)
@app_flask.route('/')
def hello_world(): return 'Bot 2 Alive'

def run_flask_server():
    port = int(os.environ.get('PORT', 8000))
    app_flask.run(host='0.0.0.0', port=port)

def is_gpu_available_c2():
    try:
        subprocess.check_output(['nvidia-smi'], stderr=subprocess.STDOUT)
        return True
    except: return False

def format_size_c2(size_bytes):
    if size_bytes < 1024**2: return f"{size_bytes/1024:.2f} KB"
    if size_bytes < 1024**3: return f"{size_bytes/1024**2:.2f} MB"
    return f"{size_bytes/1024**3:.2f} GB"

def human_readable_time_c2(seconds: int) -> str:
    m, s = divmod(int(seconds), 60); h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

async def update_message_c2(client, chat_id, message_id, text, reply_markup=None):
    try: await client.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup)
    except: pass

def get_progress_bar_c2(percentage):
    cb = int(percentage // 10); return '■' * cb + '□' * (10 - cb)

async def progress_bar_handler_c2(current, total, client, message, start_time, action_text):
    now = time.time()
    chat_id = message.chat.id
    if now - user_data_c2.get(chat_id, {}).get('last_update_time', 0) < 5: return
    user_data_c2.setdefault(chat_id, {})['last_update_time'] = now
    pct = (current * 100 / total) if total > 0 else 0
    elapsed = now - start_time
    speed = current / elapsed if elapsed > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0
    text = (f"**{action_text}**\n`[{get_progress_bar_c2(pct)}] {pct:.1f}%`\n\n**Tamaño:** `{format_size_c2(current)} / {format_size_c2(total)}`\n**Velocidad:** `{format_size_c2(speed)}/s` | **ETA:** `{human_readable_time_c2(eta)}`")
    await update_message_c2(client, chat_id, message.id, text)

async def download_video_c2(client, chat_id, status_message):
    user_info = user_data_c2.get(chat_id)
    start_time = time.time()
    try:
        original_message = await client.get_messages(chat_id, user_info['original_message_id'])
        # Descarga aislada por carpeta para multi-usuario
        path = await client.download_media(original_message, file_name=os.path.join(DOWNLOAD_DIR_C2, f"{uuid.uuid4().hex[:5]}_{user_info['video_file_name']}"), progress=progress_bar_handler_c2, progress_args=(client, status_message, start_time, "📥 DESCARGANDO..."))
        user_info['final_path'] = path; return path
    except: return None

async def run_compression_flow_c2(client, chat_id, status_message):
    # Usar task para no bloquear el bot
    path = await download_video_c2(client, chat_id, status_message)
    if not path: return
    user_info = user_data_c2[chat_id]
    opts = user_info['compression_options']
    output = os.path.join(DOWNLOAD_DIR_C2, f"comp_{uuid.uuid4().hex[:5]}.mp4")
    probe = ffmpeg.probe(path); duration = float(probe.get('format', {}).get('duration', 0)); orig_size = os.path.getsize(path)

    if is_gpu_available_c2():
        await update_message_c2(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO (GPU)...")
        preset_map = {'ultrafast': 'p1', 'veryfast': 'p2', 'fast': 'p3', 'medium': 'p4', 'slow': 'p6'}
        cmd = ['ffmpeg', '-hwaccel', 'cuda', '-i', path, '-vf', f"scale_cuda=-2:{opts['resolution']}", '-c:v', 'h264_nvenc', '-preset', preset_map.get(opts['preset'], 'p4'), '-cq', opts['crf'], '-acodec', 'aac', '-b:a', '64k', '-threads', '0', '-progress', 'pipe:1', '-y', output]
    else:
        await update_message_c2(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO...")
        cmd = ['ffmpeg', '-i', path, '-vf', f"scale=-2:{opts['resolution']}", '-crf', opts['crf'], '-preset', opts['preset'], '-vcodec', 'libx264', '-acodec', 'aac', '-b:a', '64k', '-threads', '0', '-progress', 'pipe:1', '-y', output]

    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    if await track_ffmpeg_progress_c2(client, chat_id, status_message.id, process, duration, orig_size, output):
        user_info['final_path'] = output
        reduction = ((orig_size - os.path.getsize(output)) / orig_size) * 100
        summary = (f"✅ **Compresión Exitosa**\n\n**📏 Original:** `{format_size_c2(orig_size)}`\n**📂 Comprimido:** `{format_size_c2(os.path.getsize(output))}` (`{reduction:.1f}%` menos)")
        await show_conversion_options_c2(client, chat_id, status_message.id, text=summary)
    if os.path.exists(path): os.remove(path)

async def track_ffmpeg_progress_c2(client, chat_id, msg_id, process, duration, original_size, output_path):
    last_upd = 0; ffmpeg_data = {}; is_gpu = is_gpu_available_c2()
    while True:
        line = await process.stdout.readline()
        if not line: break
        match = re.match(r'(\w+)=(.*)', line.decode('utf-8').strip())
        if match: ffmpeg_data[match.group(1)] = match.group(2)
        if ffmpeg_data.get('progress') == 'continue':
            now = time.time()
            if now - last_upd < 2: continue
            last_upd = now
            cur_time_sec = int(ffmpeg_data.get('out_time_us', 0)) / 1_000_000
            pct = min((cur_time_sec / duration) * 100, 100) if duration > 0 else 0
            speed = ffmpeg_data.get('speed', '0x').replace('x', '')
            eta = (duration - cur_time_sec) / float(speed) if float(speed or 0) > 0 else 0
            header = "COMPRIMIENDO (GPU)..." if is_gpu else "COMPRIMIENDO..."
            text = (f"**{header}**\n`[{get_progress_bar_c2(pct)}] {pct:.1f}%`\n\n**Tamaño:** `{format_size_c2(os.path.getsize(output_path)) if os.path.exists(output_path) else '0 B'}` / `{format_size_c2(original_size)}`\n**Velocidad:** `{speed}x` | **ETA:** `{human_readable_time_c2(eta)}`")
            await update_message_c2(client, chat_id, msg_id, text)
    await process.wait(); return process.returncode == 0

async def upload_final_video_c2(client, chat_id):
    user_info = user_data_c2.get(chat_id)
    if not user_info: return
    final_path, status_id = user_info['final_path'], user_info['status_message_id']
    status_message = await client.get_messages(chat_id, status_id)
    file_name = user_info.get('new_name') or os.path.basename(user_info['video_file_name'])
    if not file_name.endswith(".mp4"): file_name += ".mp4"
    try:
        probe = ffmpeg.probe(final_path); stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), {})
        dur, w, h = int(float(stream.get('duration', 0))), int(stream.get('width', 0)), int(stream.get('height', 0))
        await update_message_c2(client, chat_id, status_id, "⬆️ SUBIENDO...")
        if user_info.get('send_as_file'):
            await client.send_document(chat_id, document=final_path, thumb=user_info.get('thumbnail_path'), file_name=file_name, caption=f"`{file_name}`", progress=progress_bar_handler_c2, progress_args=(client, status_message, time.time(), "⬆️ Subiendo"))
        else:
            await client.send_video(chat_id, video=final_path, caption=f"`{file_name}`", thumb=user_info.get('thumbnail_path'), duration=dur, width=w, height=h, supports_streaming=True, progress=progress_bar_handler_c2, progress_args=(client, status_message, time.time(), "⬆️ Subiendo"))
        await status_message.delete(); await client.send_message(chat_id, "✅ ¡Proceso completado!")
    finally: clean_up_c2(chat_id)

def clean_up_c2(chat_id):
    ui = user_data_c2.pop(chat_id, None)
    if ui:
        for k in ['final_path', 'thumbnail_path']:
            if ui.get(k) and os.path.exists(ui[k]): os.remove(ui[k])

@app2.on_message(filters.command("start") & filters.private)
async def start_command_c2(client, message):
    if not await check_permissions(client, message): return
    clean_up_c2(message.chat.id)
    engine = "NVIDIA GPU 🔥" if is_gpu_available_c2() else "CPU 💻"
    await message.reply(f"¡Hola! Soy tu procesador de videos.\n**Motor:** `{engine}`\nEnvíame un video.")

@app2.on_message(filters.video & filters.private)
async def video_handler_c2(client, message):
    if not await check_permissions(client, message): return
    chat_id = message.chat.id
    user_data_c2[chat_id] = {'original_message_id': message.id, 'video_file_name': message.video.file_name or f"v_{message.id}.mp4"}
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")], [InlineKeyboardButton("⚙️ Solo Enviar", callback_data="action_convert_only")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await message.reply_text("Video recibido. ¿Qué quieres hacer?", reply_markup=kb, quote=True)

@app2.on_callback_query()
async def callback_handler_c2(client, cb):
    chat_id, user_info = cb.message.chat.id, user_data_c2.get(cb.message.chat.id)
    if not user_info: return await cb.answer("Expirado.", show_alert=True)
    user_info['status_message_id'] = cb.message.id
    await cb.answer()
    if cb.data == "cancel": await cb.message.edit("Operación cancelada."); clean_up_c2(chat_id)
    elif cb.data == "action_compress":
        user_info['compression_options'] = {'crf': '24' if is_gpu_available_c2() else '22', 'resolution': '360', 'preset': 'veryfast'}
        await show_compression_options_c2(client, chat_id, cb.message.id)
    elif cb.data == "compressopt_default":
        await cb.message.edit("Iniciando..."); asyncio.create_task(run_compression_flow_c2(client, chat_id, cb.message))
    elif cb.data == "compressopt_advanced": await show_advanced_menu_c2(client, chat_id, cb.message.id, "crf")
    elif cb.data.startswith("adv_"):
        p, v = cb.data.split("_")[1], cb.data.split("_")[2]
        user_info.setdefault('compression_options', {})[p] = v
        nx = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(p)
        if nx: await show_advanced_menu_c2(client, chat_id, cb.message.id, nx, user_info['compression_options'])
    elif cb.data == "start_advanced_compression":
        await cb.message.edit("Iniciando..."); asyncio.create_task(run_compression_flow_c2(client, chat_id, cb.message))
    elif cb.data == "action_convert_only":
        await cb.message.edit("Iniciando..."); asyncio.create_task(run_download_only_flow(client, chat_id, cb.message))
    elif cb.data == "convertopt_withthumb": user_info['state'] = 'waiting_for_thumbnail'; await cb.message.edit("Envía la miniatura.")
    elif cb.data == "convertopt_nothumb": user_info['thumbnail_path'] = None; await show_rename_options_c2(client, chat_id, cb.message.id)
    elif cb.data == "convertopt_asfile": user_info['send_as_file'] = True; await show_rename_options_c2(client, chat_id, cb.message.id)
    elif cb.data == "renameopt_yes": user_info['state'] = 'waiting_for_new_name'; await cb.message.edit("Nuevo nombre (sin extensión):")
    elif cb.data == "renameopt_no": user_info['new_name'] = None; asyncio.create_task(upload_final_video_c2(client, chat_id))

async def run_download_only_flow(client, chat_id, status_message):
    if await download_video_c2(client, chat_id, status_message):
        await show_conversion_options_c2(client, chat_id, status_message.id, text="Descarga completa. ¿Cómo quieres continuar?")

@app2.on_message(filters.photo & filters.private)
async def thumbnail_handler_c2(client, message):
    chat_id, ui = message.chat.id, user_data_c2.get(message.chat.id)
    if not ui or ui.get('state') != 'waiting_for_thumbnail': return
    ui['thumbnail_path'] = await client.download_media(message, file_name=os.path.join(DOWNLOAD_DIR_C2, f"t_{chat_id}.jpg"))
    await show_rename_options_c2(client, chat_id, ui['status_message_id'], "Miniatura guardada. ¿Renombrar?")

@app2.on_message(filters.text & filters.private)
async def rename_handler_c2(client, message):
    ui = user_data_c2.get(message.chat.id)
    if ui and ui.get('state') == 'waiting_for_new_name':
        ui['new_name'] = message.text.strip(); await message.delete()
        await update_message_c2(client, message.chat.id, ui['status_message_id'], "🚀 Iniciando subida...")
        asyncio.create_task(upload_final_video_c2(client, message.chat.id))

async def show_compression_options_c2(c, cid, mid):
    btn = "✅ Usar GPU (Rec)" if is_gpu_available_c2() else "✅ Usar Recomendadas"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn, callback_data="compressopt_default")], [InlineKeyboardButton("⚙️ Avanzado", callback_data="compressopt_advanced")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await update_message_c2(c, cid, mid, "Elige cómo quieres comprimir:", kb)

async def show_advanced_menu_c2(c, cid, mid, part, opts=None):
    is_gpu = is_gpu_available_c2()
    if part == "confirm":
        text = f"Confirmar:\n- Calidad: `{opts.get('crf')}`\n- Res: `{opts.get('resolution')}p`"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Iniciar", callback_data="start_advanced_compression")]])
    else:
        titles = {"crf": "1/3 Calidad", "resolution": "2/3 Res", "preset": "3/3 Velocidad"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Confirmar", callback_data=f"adv_{part}_val")]])
        text = titles.get(part, part)
    await update_message_c2(c, cid, mid, text, kb)

async def show_conversion_options_c2(c, cid, mid, text="¿Cómo quieres enviar?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🖼️ Miniatura", callback_data="convertopt_withthumb")], [InlineKeyboardButton("🚫 Sin Mini", callback_data="convertopt_nothumb")], [InlineKeyboardButton("📂 Como Archivo", callback_data="convertopt_asfile")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await update_message_c2(c, cid, mid, text, kb)

async def show_rename_options_c2(c, cid, mid, text="¿Renombrar?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Sí", callback_data="renameopt_yes")], [InlineKeyboardButton("➡️ No", callback_data="renameopt_no")]])
    await update_message_c2(c, cid, mid, text, kb)

# ==============================================================================
# LÓGICA DEL BOT 3 (DOWNLOADER)
# ==============================================================================
@app3.on_message(filters.command("start"))
async def start_c3(c, m):
    if not await check_permissions(c, m): return
    await m.reply_text("✨ **¡BOT DE DESCARGAS ACTIVO!** ✨")

@app3.on_message(filters.text)
async def handle_text_c3(c, m):
    if not await check_permissions(c, m): return
    if m.text.startswith("http"):
        s = await m.reply_text("🔎 Analizando..."); await show_options_c3(m.text, s)
    else:
        s = await m.reply_text("🔎 Buscando..."); res = search_videos_c3(m.text)
        btns = [[InlineKeyboardButton(f"🎥 {v['title'][:40]}", callback_data=f"opts|{str(uuid.uuid4())[:8]}")] for v in res]
        for i, v in enumerate(res): url_storage_c3[btns[i][0].callback_data.split('|')[1]] = v.get('webpage_url')
        await s.edit_text("✅ Elige un video:", reply_markup=InlineKeyboardMarkup(btns))

@app3.on_callback_query(filters.regex(r"^dl\|"))
async def dl_c3(c, q):
    _, link_id, quality = q.data.split("|"); url = url_storage_c3.get(link_id)
    s = await q.message.edit_text("⏳ Descargando...")
    opts = {'format': f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best', 'outtmpl': f'{DOWNLOAD_DIR_C3}/%(title)s.%(ext)s'}
    with YoutubeDL(opts) as ydl:
        info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
        p = ydl.prepare_filename(info)
        await q.message.reply_video(p, caption=f"✅ {info['title']}", supports_streaming=True, progress=progress_bar_c3, progress_args=(s, time.time()))
    if os.path.exists(p): os.remove(p)
    await s.delete()

# ==========================================
# EJECUCIÓN (MAIN)
# ==========================================
async def main():
    print("🚀 SISTEMA INICIADO...")
    Thread(target=run_flask_server).start()
    await app1.start(); await app2.start(); await app3.start(); await app4.start()
    await idle()
    await app1.stop(); await app2.stop(); await app3.stop(); await app4.stop()

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass
