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
import GPUtil 
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

# Aplicar nest_asyncio inmediatamente
nest_asyncio.apply()

# ==========================================
# ⚙️ CONFIGURACIÓN Y ESTADO GLOBAL (CORREGIDO)
# ==========================================

# 1. Carga segura de variables de entorno
# Usamos .get() y valores por defecto para que el bot no "muera" si falta un dato
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

BOT1_TOKEN = os.environ.get("BOT1_TOKEN", "")
BOT2_TOKEN = os.environ.get("BOT2_TOKEN", "")
BOT3_TOKEN = os.environ.get("BOT3_TOKEN", "")
BOT4_TOKEN = os.environ.get("BOT4_TOKEN", "")

# 2. Inicialización UNIFICADA de las 4 apps
# Solo se definen una vez aquí.
app1 = Client("bot1", api_id=API_ID, api_hash=API_HASH, bot_token=BOT1_TOKEN, workers=20)
app2 = Client("bot2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT2_TOKEN, workers=20)
app3 = Client("bot3", api_id=API_ID, api_hash=API_HASH, bot_token=BOT3_TOKEN, workers=20)
app4 = Client("bot4", api_id=API_ID, api_hash=API_HASH, bot_token=BOT4_TOKEN, workers=5)

CONFIG_FILE = "/kaggle/working/system_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("mode", "OFF"), data.get("allowed", [])
        except: return "OFF", []
    return "OFF", []

def save_config():
    try:
        data = {"mode": SYSTEM_MODE, "allowed": ALLOWED_USERS}
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except: pass

# Inicialización de variables de estado
SYSTEM_MODE, ALLOWED_USERS = load_config()
WAITING_FOR_ID = False
PANEL_MSG_ID = None

# Definición de clientes (Asumo que ya los tienes iniciados como en tu ejemplo)
# app1 = ... 
# app4 = ... (Este es el controlador)

# ==========================================
# 🛡️ LÓGICA DE PERMISOS CONECTADA AL PANEL
# ==========================================

async def check_permissions(client, update):
    """
    Verifica si el usuario tiene permiso para usar los bots 
    basándose en el estado global del Bot 4 (SYSTEM_MODE).
    """
    # Detectar si es Mensaje o Callback
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

    # 1. 👑 El ADMIN siempre entra (pase lo que pase)
    if user_id == ADMIN_ID:
        return True

    # 2. 🔴 Modo MANTENIMIENTO (OFF)
    if SYSTEM_MODE == "OFF":
        msg_off = "⛔ **SISTEMA EN MANTENIMIENTO**\nLos bots están temporalmente fuera de servicio por actualizaciones técnicas."
        
        if isinstance(update, CallbackQuery):
            await reply_method("⛔ Mantenimiento activo.", show_alert=True)
        elif chat_type == "private":
            await reply_method(msg_off, quote=True)
        return False

                # 3. 🔒 Modo PRIVADO (VIP)
    if SYSTEM_MODE == "PRIVATE":
        if user_id not in ALLOWED_USERS:
            # Usamos acentos graves (`) para que en tu chat el ID sea copiable
            # El texto que recibirá el administrador será: Mi ID es: `12345678`
            texto_solicitud = f"Hola, solicito acceso al bot. Mi ID es: `{user_id}`"
            
            import urllib.parse
            encoded_text = urllib.parse.quote(texto_solicitud)
            link_soporte = f"https://t.me/AnzZGTv1?text={encoded_text}"
            
            # El mensaje exacto que pediste
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


    # 🟢 Si está en ON o el usuario es VIP/Admin, retorna True
    return True

# ==========================================
# ==========================================
# ==========================================
# 🎮 CONTROLADOR (BOT 4) - DISEÑO COMPACTO Y NOMBRES
# ==========================================

ADMIN_ID = 1806990534 
PANEL_MSG_ID = None 

def get_panel_menu():
    # Usamos indicadores visuales minimalistas para mantener el ancho parejo
    m_on = "🟢" if SYSTEM_MODE == "ON" else "⚪"
    m_vip = "🔒" if SYSTEM_MODE == "PRIVATE" else "⚪"
    m_off = "🔴" if SYSTEM_MODE == "OFF" else "⚪"
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{m_on} ON", callback_data="set_ON"),
            InlineKeyboardButton(f"{m_vip} VIP", callback_data="set_PRIVATE"),
            InlineKeyboardButton(f"{m_off} OFF", callback_data="set_OFF")
        ],
        [
            InlineKeyboardButton("➕ AGREGAR USUARIO", callback_data="ui_add")
        ],
        [
            InlineKeyboardButton(f"📋 LISTA AUTORIZADOS ({len(ALLOWED_USERS)})", callback_data="ui_list")
        ]
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
        await q.message.edit_text(
            "✍️ <b>INGRESE ID DEL USUARIO</b>\n\nEl sistema buscará el nombre automáticamente:", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 CANCELAR", callback_data="ui_home")]])
        )
    
    elif data == "ui_list":
        if not ALLOWED_USERS: return await q.answer("No hay usuarios autorizados.", show_alert=True)
        
        await q.answer("Cargando nombres...")
        btns = []
        for uid in ALLOWED_USERS:
            try:
                # Intentamos obtener el nombre del usuario
                user = await c.get_users(uid)
                name = user.first_name
            except:
                name = f"ID: {uid}"
            
            btns.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"del_{uid}")])
        
        btns.append([InlineKeyboardButton("🔙 VOLVER AL MENÚ", callback_data="ui_home")])
        await q.message.edit_text("📋 <b>USUARIOS CON ACCESO</b>\n<i>Toca para eliminar:</i>", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("del_"):
        uid = int(data.split("_")[1])
        if uid in ALLOWED_USERS: 
            ALLOWED_USERS.remove(uid)
            save_config()
            await q.answer("Usuario eliminado")
        
        # Refrescar lista o volver si queda vacía
        if ALLOWED_USERS:
            await controller_callbacks(c, q) # Reutilizamos la lógica de lista
        else:
            await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())

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
            
            await m.delete() # Borra el número enviado
            
            if PANEL_MSG_ID:
                # Al agregar con éxito, vuelve al panel principal automáticamente
                await c.edit_message_text(m.chat.id, PANEL_MSG_ID, get_panel_text(), reply_markup=get_panel_menu())
                return 
        except: pass

    # Limpieza total para /start o entradas no válidas
    try:
        async for message in c.get_chat_history(m.chat.id, limit=30):
            await message.delete()
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
    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=600)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
        with open(path, 'rb') as f:
            if server == "Litterbox":
                data = aiohttp.FormData()
                data.add_field('reqtype', 'fileupload'); data.add_field('time', '72h'); data.add_field('fileToUpload', f)
                async with s.post("https://litterbox.catbox.moe/resources/internals/api.php", data=data) as r:
                    return (await r.text()).strip() if r.status == 200 else None
            elif server == "Catbox":
                data = aiohttp.FormData()
                data.add_field('reqtype', 'fileupload')
                if 'CATBOX_HASH' in globals() and CATBOX_HASH: 
                    data.add_field('userhash', CATBOX_HASH.strip())
                data.add_field('fileToUpload', f)
                async with s.post("https://catbox.moe/user/api.php", data=data) as r:
                    return (await r.text()).strip() if r.status == 200 else None
            elif server == "GoFile":
                try:
                    async with s.get("https://api.gofile.io/servers") as gs:
                        server_res = await gs.json()
                        server_name = server_res['data']['servers'][0]['name']
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=os.path.basename(path))
                    if 'GOFILE_TOKEN' in globals() and GOFILE_TOKEN: 
                        data.add_field('token', GOFILE_TOKEN.strip())
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
                            try:
                                res = await r.json()
                                return f"https://pixeldrain.com/api/file/{res['id']}"
                            except:
                                resp_text = await r.text()
                                try: 
                                    res = json.loads(resp_text)
                                    return f"https://pixeldrain.com/api/file/{res['id']}"
                                except: return None
                        else: return None
                except: return None
    return None

def get_fixed_menu_c1():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀 Litterbox"), KeyboardButton("📦 Catbox")], 
        [KeyboardButton("⚡ GoFile"), KeyboardButton("💎 Pixeldrain")]
    ], resize_keyboard=True, placeholder="Seleccione servidor...")

async def progress_bar_c1(current, total, msg, start_time, server_name):
    now = time.time()
    if now - getattr(msg, "last_upd", 0) < 4: return
    msg.last_upd = now
    percentage = current * 100 / total
    completed = int(percentage / 10); bar = "▰" * completed + "▱" * (10 - completed)
    elapsed_time = now - start_time; speed = current / elapsed_time if elapsed_time > 0 else 0
    txt = (f"<b>Descargando...</b>\n<code>{bar}</code> {percentage:.1f}%\n📊 <b>Velocidad:</b> <code>{speed/1024**2:.1f} MB/s</code>\n📦 <b>Carga:</b> <code>{current/1024**2:.1f}/{total/1024**2:.1f} MB</code>")
    try: await msg.edit_text(txt)
    except: pass

@app1.on_message(filters.command("start"))
async def start_cmd_c1(_, m):
    # --- VERIFICACIÓN DE PERMISOS ---
    if not await check_permissions(_, m): return
    # --------------------------------
    
    user_preference_c1.pop(m.from_user.id, None)
    welcome = "<b>💎 CLOUD UPLOADER PREMIUM</b>\n\nSeleccione un servidor para comenzar."
    await m.reply_text(welcome, reply_markup=get_fixed_menu_c1(), quote=True)


@app1.on_message(filters.regex("^(🚀 Litterbox|📦 Catbox|⚡ GoFile|💎 Pixeldrain)$"))
async def set_server_via_btn_c1(_, m):
    server_choice = m.text.split(" ")[1]
    user_preference_c1[m.from_user.id] = server_choice
    await m.reply_text(f"✅ <b>Servidor configurado:</b> <code>{server_choice.upper()}</code>", quote=True)

@app1.on_message(filters.media)
async def handle_media_c1(c, m):
    # --- VERIFICACIÓN DE PERMISOS (NUEVO) ---
    if not await check_permissions(c, m): 
        return
    # ----------------------------------------

    user_id = m.from_user.id
    if user_id not in user_preference_c1:
        await m.reply_text("⚠️ <b>Error:</b> Seleccione un servidor primero.", reply_markup=get_fixed_menu_c1(), quote=True); return
    server = user_preference_c1[user_id]
    status = await m.reply_text(f"📤 Preparando archivo...", quote=True)
    path = None
    try:
        path = await c.download_media(m, file_name="./", progress=progress_bar_c1, progress_args=(status, time.time(), server))
        if server != "Catbox": await status.edit_text(f"📤 Subiendo a {server.upper()}...")
        link = await upload_file_c1(path, server)
        if link:
            size_mb = os.path.getsize(path) / (1024**2)
            bot_username = (await c.get_me()).username
            share_link = f"https://t.me/{bot_username}?start=file_{uuid.uuid4().hex[:10]}"
            if server == "Litterbox": vence = "72 Horas"
            elif server == "Pixeldrain": vence = "60 Días (tras inactividad)"
            else: vence = "Permanente"
            final_text = (f"𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !\n\n📦 Fɪʟᴇ ꜱɪᴢᴇ : {size_mb:.2f} MiB\n\n📥 Dᴏᴡɴʟᴏᴀᴅ : <code>{link}</code>\n\n🔗 Sʜᴀʀᴇ : {share_link}\n\n⏳ Vencimiento: {vence}")
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("sᴛʀᴇᴀüm", url=link),InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=link)],[InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="close_all")]])
            await status.edit_text(final_text, reply_markup=keyboard, disable_web_page_preview=True)
        else: await status.edit_text(f"❌ Error al subir a {server}.")
    except Exception as e: await status.edit_text(f"⚠️ Fallo: {str(e)}")
    finally:
        if path and os.path.exists(path): os.remove(path)


@app1.on_callback_query(filters.regex("close_all"))
async def close_callback_c1(c, q):
    try:
        await q.message.delete()
        if q.message.reply_to_message: await q.message.reply_to_message.delete()
    except: await q.answer("Mensaje borrado", show_alert=False)


# ==============================================================================
# LÓGICA DEL BOT 2 (VIDEO PROCESSOR / ANZEL) - INTEGRADO
# ==============================================================================

# Variables específicas del Bot 2
MAX_VIDEO_SIZE_MB_C2 = 4000
DOWNLOAD_DIR_C2 = "downloads"
os.makedirs(DOWNLOAD_DIR_C2, exist_ok=True)
user_data_c2 = {}

# --- Servidor Flask (Keep-Alive) ---
app_flask = Flask(__name__)

@app_flask.route('/')
def hello_world():
    return 'Bot 2 Alive'

def run_flask_server():
    port = int(os.environ.get('PORT', 8000))
    # Desactivamos logs de flask para no ensuciar consola
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app_flask.run(host='0.0.0.0', port=port)

# --- Utilidades Bot 2 ---
def is_gpu_available_c2():
    try:
        subprocess.check_output(['nvidia-smi'], stderr=subprocess.STDOUT)
        return True
    except:
        return False

def get_best_gpu_c2():
    """Selecciona la GPU T4 con menos carga actual para balancear el trabajo"""
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if not gpus or len(gpus) < 2: 
            return "0"
        # Ordenar las GPUs por menor uso de memoria actual
        best_gpu = sorted(gpus, key=lambda x: x.memoryUsed)[0]
        return str(best_gpu.id)
    except:
        return "0"

def format_size_c2(size_bytes):
    if size_bytes is None: return "0 B"
    if size_bytes < 1024: return f"{size_bytes} Bytes"
    if size_bytes < 1024**2: return f"{size_bytes/1024:.2f} KB"
    if size_bytes < 1024**3: return f"{size_bytes/1024**2:.2f} MB"
    return f"{size_bytes/1024**3:.2f} GB"

def human_readable_time_c2(seconds: int) -> str:
    if seconds is None: return "00:00"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

async def update_message_c2(client, chat_id, message_id, text, reply_markup=None):
    try:
        await client.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup)
    except MessageNotModified: pass
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await update_message_c2(client, chat_id, message_id, text, reply_markup)

def get_progress_bar_c2(percentage):
    completed_blocks = int(percentage // 10)
    if percentage >= 100: return '■' * 10
    return '■' * completed_blocks + '□' * (10 - completed_blocks)

async def progress_bar_handler_c2(current, total, client, message, start_time, action_text):
    chat_id = message.chat.id
    user_info = user_data_c2.get(chat_id, {})
    last_update_time = user_info.get('last_update_time', 0)
    current_time = time.time()

    if current_time - last_update_time < 5: return
    user_info['last_update_time'] = current_time

    percentage = (current * 100 / total) if total > 0 else 0
    elapsed_time = current_time - start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    progress_bar = get_progress_bar_c2(percentage)
    action_text_clean = action_text.replace('📥 Descargando', 'DESCARGANDO...').replace('⬆️ Subiendo', 'SUBIENDO...').replace('🗜️ Comprimiendo...', 'COMPRIMIENDO...')

    text = (
        f"**{action_text_clean}**\n"
        f"`[{progress_bar}] {percentage:.1f}%`\n\n"
        f"**Tamaño:** `{format_size_c2(current)} / {format_size_c2(total)}`\n"
        f"**Velocidad:** `{format_size_c2(speed)}/s` | **ETA:** `{human_readable_time_c2(eta)}`"
    )
    await update_message_c2(client, chat_id, message.id, text)

# --- Lógica de Procesamiento Bot 2 ---

async def download_video_c2(client, chat_id, status_message):
    user_info = user_data_c2.get(chat_id)
    if not user_info: return None
    user_info['state'] = 'downloading'
    start_time = time.time()
    try:
        original_message = await client.get_messages(chat_id, user_info['original_message_id'])
        video_path = await client.download_media(
            message=original_message,
            file_name=os.path.join(DOWNLOAD_DIR_C2, f"{chat_id}_{user_info['video_file_name']}"),
            progress=progress_bar_handler_c2,
            progress_args=(client, status_message, start_time, "📥 Descargando")
        )
        if not video_path: return None
        user_info['download_path'] = video_path
        user_info['final_path'] = video_path
        return video_path
    except Exception as e:
        logger.error(f"Error descarga: {e}")
        return None

async def run_compression_flow_c2(client, chat_id, status_message):
    downloaded_path = None
    try:
        # La descarga ahora es llamada de forma asíncrona
        downloaded_path = await download_video_c2(client, chat_id, status_message)
        if not downloaded_path: return

        user_info = user_data_c2[chat_id]
        user_info['state'] = 'compressing'
        opts = user_info['compression_options']
        # Usamos UUID para que si dos personas comprimen a la vez, los archivos no choquen
        output_path = os.path.join(DOWNLOAD_DIR_C2, f"comp_{uuid.uuid4().hex[:5]}_{chat_id}.mp4")

        probe = ffmpeg.probe(downloaded_path)
        duration = float(probe.get('format', {}).get('duration', 0))
        original_size = os.path.getsize(downloaded_path)

        if is_gpu_available_c2():
            selected_gpu = get_best_gpu_c2() # <--- Selecciona T4 (0 o 1)
            await update_message_c2(client, chat_id, status_message.id, f"🗜️ COMPRIMIENDO (GPU {selected_gpu})...")
            
            preset_map = {'ultrafast': 'p1', 'veryfast': 'p2', 'fast': 'p3', 'medium': 'p4', 'slow': 'p6'}
            gpu_preset = preset_map.get(opts['preset'], 'p4')
            
            cmd = [
                'ffmpeg', '-hwaccel', 'cuda', '-hwaccel_device', selected_gpu,
                '-hwaccel_output_format', 'cuda', '-i', downloaded_path,
                '-vf', f"scale_cuda=-2:{opts['resolution']}",
                '-c:v', 'h264_nvenc', '-preset', gpu_preset,
                '-rc', 'vbr', '-cq', opts['crf'], '-b:v', '0',
                '-acodec', 'aac', '-b:a', '64k', '-movflags', '+faststart',
                '-progress', 'pipe:1', '-nostats', '-y', output_path
            ]
            engine_text = f"GPU T4 (Slot {selected_gpu})"
        else:
            await update_message_c2(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO (CPU)...")
            cmd = [
                'ffmpeg', '-i', downloaded_path,
                '-vf', f"scale=-2:{opts['resolution']}",
                '-r', '30', '-crf', opts['crf'], '-preset', opts['preset'],
                '-vcodec', 'libx264', '-acodec', 'aac', '-b:a', '64k',
                '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', '-y', output_path
            ]
            engine_text = "CPU Estándar"

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        success = await track_ffmpeg_progress_c2(client, chat_id, status_message.id, process, duration, original_size, output_path)

        if success:
            user_info['final_path'] = output_path
            compressed_size = os.path.getsize(output_path)
            reduction = ((original_size - compressed_size) / original_size) * 100
            summary = (f"✅ **Compresión Finalizada ({engine_text})**\n\n"
                       f"**Reducción:** `{reduction:.1f}%` | **Tamaño:** `{format_size_c2(compressed_size)}` \n"
                       f"¿Cómo procedemos?")
            await show_conversion_options_c2(client, chat_id, status_message.id, text=summary)
    except Exception as e:
        await client.send_message(chat_id, f"❌ Error en flujo: {e}")
    finally:
        if downloaded_path and os.path.exists(downloaded_path): 
            try: os.remove(downloaded_path)
            except: pass

        
        title = f"✅ **Compresión Exitosa ({engine_text})**" if is_gpu_available_c2() else "✅ **Compresión Exitosa**"
        summary = (f"{title}\n\n"
                    f"**📏 Original:** `{format_size_c2(original_size)}`\n"
                    f"**📂 Comprimido:** `{format_size_c2(compressed_size)}` (`{reduction:.1f}%` menos)\n\n"
                    f"Ahora, ¿cómo quieres continuar?")
        await show_conversion_options_c2(client, chat_id, status_message.id, text=summary)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update_message_c2(client, chat_id, status_message.id, "❌ Error inesperado.")
    finally:
        if downloaded_path and os.path.exists(downloaded_path): os.remove(downloaded_path)

async def track_ffmpeg_progress_c2(client, chat_id, msg_id, process, duration, original_size, output_path):
    last_update = 0
    ffmpeg_data = {}
    is_gpu = is_gpu_available_c2()

    while True:
        if user_data_c2.get(chat_id, {}).get('state') == 'cancelled':
            if process.returncode is None: process.terminate()
            await update_message_c2(client, chat_id, msg_id, "🛑 Operación cancelada.")
            return False

        line = await process.stdout.readline()
        if not line: break
        line = line.decode('utf-8').strip()
        match = re.match(r'(\w+)=(.*)', line)
        if match:
            key, value = match.groups()
            ffmpeg_data[key] = value

        if 'progress' in ffmpeg_data and ffmpeg_data['progress'] == 'continue':
            raw_time = ffmpeg_data.get('out_time_us', '0')
            current_time_us = int(raw_time) if str(raw_time).isdigit() else 0
            if current_time_us == 0:
                ffmpeg_data.clear(); continue

            current_time = time.time()
            interval = 2.0 if is_gpu else 1.5
            if current_time - last_update < interval:
                ffmpeg_data.clear(); continue
            last_update = current_time

            current_time_sec = current_time_us / 1_000_000
            speed_str = ffmpeg_data.get('speed', '0x').replace('x', '')
            try: speed_mult = float(speed_str)
            except: speed_mult = 0

            percentage = min((current_time_sec / duration) * 100, 100) if duration > 0 else 0
            eta = (duration - current_time_sec) / speed_mult if speed_mult > 0 else 0
            progress_bar = get_progress_bar_c2(percentage)
            current_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            header = "COMPRIMIENDO (GPU)..." if is_gpu else "COMPRIMIENDO..."
            text = (
                f"**{header}**\n"
                f"`[{progress_bar}] {percentage:.1f}%`\n\n"
                f"**Tamaño:** `{format_size_c2(current_size)} / {format_size_c2(original_size)}`\n"
                f"**Velocidad:** `{speed_mult:.2f}x` | **ETA:** `{human_readable_time_c2(eta)}`"
            )
            await update_message_c2(client, chat_id, msg_id, text)
            ffmpeg_data.clear()

    await process.wait()
    return process.returncode == 0

async def upload_final_video_c2(client, chat_id):
    user_info = user_data_c2.get(chat_id)
    if not user_info or not user_info.get('final_path'): return
    final_path, status_id = user_info['final_path'], user_info['status_message_id']
    status_message = await client.get_messages(chat_id, status_id)
    final_filename = user_info.get('new_name') or os.path.basename(user_info['video_file_name'])
    if not final_filename.endswith(".mp4"): final_filename += ".mp4"

    try:
        probe = ffmpeg.probe(final_path)
        stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), {})
        duration, width, height = int(float(stream.get('duration', 0))), int(stream.get('width', 0)), int(stream.get('height', 0))
        start_time = time.time()
        await update_message_c2(client, chat_id, status_id, "⬆️ SUBIENDO...")

        if user_info.get('send_as_file'):
            await client.send_document(
                chat_id=chat_id, document=final_path, thumb=user_info.get('thumbnail_path'),
                file_name=final_filename, caption=f"`{final_filename}`",
                progress=progress_bar_handler_c2, progress_args=(client, status_message, start_time, "⬆️ Subiendo")
            )
        else:
            await client.send_video(
                chat_id=chat_id, video=final_path, caption=f"`{final_filename}`",
                thumb=user_info.get('thumbnail_path'), duration=duration, width=width, height=height,
                supports_streaming=True, progress=progress_bar_handler_c2, progress_args=(client, status_message, start_time, "⬆️ Subiendo")
            )
        await status_message.delete()
        await client.send_message(chat_id, "✅ ¡Proceso completado!")
    except Exception as e:
        logger.error(f"Error subida: {e}")
        await update_message_c2(client, chat_id, status_id, "❌ Error durante la subida.")
    finally: clean_up_c2(chat_id)

def clean_up_c2(chat_id):
    user_info = user_data_c2.pop(chat_id, None)
    if not user_info: return
    for key in ['download_path', 'thumbnail_path', 'final_path']:
        path = user_info.get(key)
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass

# --- Handlers Bot 2 ---

@app2.on_message(filters.command("start") & filters.private)
async def start_command_c2(client, message):
    # --- VERIFICACIÓN DE PERMISOS ---
    if not await check_permissions(client, message): return
    # --------------------------------

    clean_up_c2(message.chat.id)
    gpu_active = is_gpu_available_c2()
    engine = "NVIDIA GPU 🔥" if gpu_active else "CPU 💻"
    await message.reply(
        f"¡Hola! 👋 Soy tu bot para procesar videos (Integrado).\n\n"
        f"**Motor detectado:** `{engine}`\n\n"
        "Puedo **comprimir** y **convertir** tus videos. **Envíame un video para empezar.**"
    )

@app2.on_message(filters.video & filters.private)
async def video_handler_c2(client, message: Message):
    # --- VERIFICACIÓN DE PERMISOS (NUEVO) ---
    if not await check_permissions(client, message): 
        return
    # ----------------------------------------

    chat_id = message.chat.id
    if user_data_c2.get(chat_id): clean_up_c2(chat_id)
    if message.video.file_size > MAX_VIDEO_SIZE_MB_C2 * 1024 * 1024:
        await message.reply(f"❌ El video supera el límite de {MAX_VIDEO_SIZE_MB_C2} MB.")
        return
    user_data_c2[chat_id] = {'state': 'awaiting_action', 'original_message_id': message.id, 'video_file_name': message.video.file_name or f"video_{message.id}.mp4", 'last_update_time': 0}
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")], [InlineKeyboardButton("⚙️ Solo Enviar/Convertir", callback_data="action_convert_only")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await message.reply_text("Video recibido. ¿Qué quieres hacer?", reply_markup=keyboard, quote=True)


@app2.on_callback_query()
async def callback_handler_c2(client, cb: CallbackQuery):
    chat_id, user_info = cb.message.chat.id, user_data_c2.get(cb.message.chat.id)
    if not user_info:
        await cb.answer("Esta operación ha expirado.", show_alert=True)
        return
    
    action = cb.data
    user_info['status_message_id'] = cb.message.id
    await cb.answer()

    # --- LÓGICA DE CANCELACIÓN ---
    if action == "cancel":
        user_info['state'] = 'cancelled'
        await cb.message.edit("🛑 Operación cancelada.")
        clean_up_c2(chat_id)

    # --- FLUJO DE COMPRESIÓN ---
    elif action == "action_compress":
        is_gpu = is_gpu_available_c2()
        user_info['compression_options'] = {'crf': '24' if is_gpu else '22', 'resolution': '360', 'preset': 'veryfast'}
        await show_compression_options_c2(client, chat_id, cb.message.id)

    elif action == "compressopt_default":
        # USAMOS create_task para que la compresión corra sola y el bot quede libre
        asyncio.create_task(run_compression_flow_c2(client, chat_id, cb.message))

    elif action == "compressopt_advanced":
        await show_advanced_menu_c2(client, chat_id, cb.message.id, "crf")

    elif action.startswith("adv_"):
        part, value = action.split("_")[1], action.split("_")[2]
        user_info.setdefault('compression_options', {})[part] = value
        next_step = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(part)
        if next_step: 
            await show_advanced_menu_c2(client, chat_id, cb.message.id, next_step, user_info['compression_options'])

    elif action == "start_advanced_compression":
        await cb.message.edit(f"⚙️ Aplicando configuración avanzada...")
        asyncio.create_task(run_compression_flow_c2(client, chat_id, cb.message))

    # --- FLUJO DE SOLO CONVERTIR / ENVIAR ---
    elif action == "action_convert_only":
        await cb.message.edit("📥 Iniciando descarga rápida...")
        # Creamos una tarea interna para no frenar al bot
        async def dl_task():
            path = await download_video_c2(client, chat_id, cb.message)
            if path:
                await show_conversion_options_c2(client, chat_id, cb.message.id, text="✅ Descarga completa.")
        asyncio.create_task(dl_task())

    elif action == "convertopt_withthumb":
        user_info['state'] = 'waiting_for_thumbnail'
        await cb.message.edit("🖼️ Por favor, envía la imagen que quieres como miniatura.")

    elif action == "convertopt_nothumb":
        user_info['thumbnail_path'] = None
        await show_rename_options_c2(client, chat_id, cb.message.id)

    elif action == "convertopt_asfile":
        user_info['send_as_file'] = True
        await show_rename_options_c2(client, chat_id, cb.message.id)

    # --- LÓGICA DE RENOMBRADO ---
    elif action == "renameopt_yes":
        user_info['state'] = 'waiting_for_new_name'
        await cb.message.edit("✏️ Envíame el nuevo nombre para el archivo (sin extensión).")

    elif action == "renameopt_no":
        user_info['new_name'] = None
        user_info['state'] = 'uploading'
        await cb.message.edit("🚀 Preparando subida directa...")
        asyncio.create_task(upload_final_video_c2(client, chat_id))

@app2.on_message(filters.photo & filters.private)
async def thumbnail_handler_c2(client, message: Message):
    chat_id, user_info = message.chat.id, user_data_c2.get(message.chat.id)
    if not user_info or user_info.get('state') != 'waiting_for_thumbnail': return
    status_id = user_info['status_message_id']
    await update_message_c2(client, chat_id, status_id, "🖼️ Descargando miniatura...")
    try:
        user_info['thumbnail_path'] = await client.download_media(message=message, file_name=os.path.join(DOWNLOAD_DIR_C2, f"thumb_{chat_id}.jpg"))
        await show_rename_options_c2(client, chat_id, status_id, "Miniatura guardada. ¿Quieres renombrar el video?")
    except: await update_message_c2(client, chat_id, status_id, "❌ Error al descargar la miniatura.")

# ==============================================================================
# 🛠️ CORRECCIÓN DE SUBIDA POST-RENOMBRADO (BOT 2)
# ==============================================================================

@app2.on_message(filters.text & filters.private)
async def rename_handler_c2(client, message: Message):
    chat_id = message.chat.id
    user_info = user_data_c2.get(chat_id)
    
    # Verificamos que realmente estemos esperando un nombre
    if not user_info or user_info.get('state') != 'waiting_for_new_name':
        return

    # 1. Guardamos el nuevo nombre y limpiamos el mensaje del usuario
    new_name = message.text.strip()
    user_info['new_name'] = new_name
    try: await message.delete()
    except: pass

    # 2. Actualizamos el mensaje de estado para que el usuario vea que hay actividad
    status_id = user_info.get('status_message_id')
    await update_message_c2(
        client, 
        chat_id, 
        status_id, 
        f"✅ Nombre establecido: <code>{new_name}</code>\n🚀 Iniciando subida inmediata..."
    )

    # 3. CAMBIO CRUCIAL: Forzamos el estado a 'uploading' y llamamos a la subida
    user_info['state'] = 'uploading'
    
    # Ejecutamos la subida. Usamos create_task para que no bloquee el handler
    asyncio.create_task(upload_final_video_c2(client, chat_id))

# --- AJUSTE EN LA FUNCIÓN DE SUBIDA PARA RECONOCER EL NOMBRE ---
async def upload_final_video_c2(client, chat_id):
    user_info = user_data_c2.get(chat_id)
    
    if not user_info:
        await client.send_message(chat_id, "❌ **La sesión ha expirado.**")
        return

    final_path = user_info.get('final_path')
    if not final_path: return
        
    status_id = user_info.get('status_message_id')
    
    if not os.path.exists(final_path):
        try:
            await client.send_message(chat_id, "⚠️ **Archivo no encontrado.**")
            if status_id: await client.delete_messages(chat_id, status_id)
        except: pass
        clean_up_c2(chat_id)
        return

    # Preparación de miniatura segura
    thumb_path = user_info.get('thumbnail_path')
    if thumb_path and not os.path.exists(thumb_path):
        thumb_path = None

    # Determinar nombre del archivo
    if user_info.get('new_name'):
        ext = os.path.splitext(final_path)[1] or ".mp4"
        file_name = user_info['new_name'] if user_info['new_name'].endswith(ext) else user_info['new_name'] + ext
    else:
        file_name = os.path.basename(user_info.get('video_file_name', 'video.mp4'))

    try:
        try: status_message = await client.get_messages(chat_id, status_id)
        except: status_message = await client.send_message(chat_id, "⬆️ Preparando subida...")

        start_time = time.time()
        
        try:
            probe = ffmpeg.probe(final_path)
            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), {})
            duration = int(float(video_stream.get('duration', 0)))
            width = int(video_stream.get('width', 0))
            height = int(video_stream.get('height', 0))
        except:
            duration, width, height = 0, 0, 0

        # --- SUBIDA REAL CORREGIDA ---
        if user_info.get('send_as_file'):
            await client.send_document(
                chat_id=chat_id, document=final_path, file_name=file_name,
                thumb=thumb_path, 
                caption=f"<code>{file_name}</code>",
                progress=progress_bar_handler_c2, progress_args=(client, status_message, start_time, "⬆️ Subiendo")
            )
        else:
            await client.send_video(
                chat_id=chat_id, video=final_path, file_name=file_name,
                caption=f"<code>{file_name}</code>",
                thumb=thumb_path, 
                duration=duration, width=width, height=height, supports_streaming=True,
                progress=progress_bar_handler_c2, progress_args=(client, status_message, start_time, "⬆️ Subiendo")
            )
        
        try: await status_message.delete()
        except: pass
        await client.send_message(chat_id, "✅ <b>Proceso Finalizado con éxito.</b>")
        
    except Exception as e:
        await client.send_message(chat_id, f"❌ <b>Error en subida:</b>\n<code>{str(e)}</code>")
    finally:
        clean_up_c2(chat_id)


# --- Menús Diferenciados Bot 2 ---
async def show_compression_options_c2(client, chat_id, msg_id):
    if is_gpu_available_c2():
        btn_rec = "✅ Usar GPU (Recomendado)"
    else:
        btn_rec = "✅ Usar Opciones Recomendadas"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(btn_rec, callback_data="compressopt_default")], [InlineKeyboardButton("⚙️ Configurar Opciones Avanzadas", callback_data="compressopt_advanced")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await update_message_c2(client, chat_id, msg_id, "Elige cómo quieres comprimir:", reply_markup=keyboard)

async def show_advanced_menu_c2(client, chat_id, msg_id, part, opts=None):
    is_gpu = is_gpu_available_c2()
    
    if is_gpu:
        crf_title = "1/3: Calidad GPU (CQ)"
        crf_opts = [("Alta", "20"), ("Media", "24"), ("Económica", "28"), ("Baja", "32")]
        preset_title = "3/3: Velocidad GPU"
        preset_opts = [("Máxima", "ultrafast"), ("Equilibrada", "medium"), ("Calidad", "slow")]
        confirm_btn = "🚀 Iniciar Compresión GPU"
    else:
        crf_title = "1/3: Calidad (CRF)"
        crf_opts = [("18", "18"), ("20", "20"), ("22", "22"), ("25", "25"), ("28", "28")]
        preset_title = "3/3: Velocidad"
        preset_opts = [("Lenta", "slow"), ("Media", "medium"), ("Muy rápida", "veryfast"), ("Rápida", "fast"), ("Ultra rápida", "ultrafast")]
        confirm_btn = "✅ Iniciar Compresión"

    menus = {
        "crf": {"text": crf_title, "opts": crf_opts, "prefix": "adv_crf"},
        "resolution": {"text": "2/3: Resolución", "opts": [("1080p", "1080"), ("720p", "720"), ("480p", "480"), ("360p", "360"), ("240p", "240")], "prefix": "adv_resolution"},
        "preset": {"text": preset_title, "opts": preset_opts, "prefix": "adv_preset"}
    }
    
    if part == "confirm":
        label = " (CQ)" if is_gpu else " (CRF)"
        text = (f"Confirmar opciones {'GPU' if is_gpu else ''}:\n"
                f"- Calidad{label}: `{opts.get('crf', 'N/A')}`\n"
                f"- Resolución: `{opts.get('resolution', 'N/A')}p`\n"
                f"- Preset: `{opts.get('preset', 'N/A')}`")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(confirm_btn, callback_data="start_advanced_compression")]])
    else:
        info = menus[part]
        buttons = [InlineKeyboardButton(t, callback_data=f"{info['prefix']}_{v}") for t, v in info["opts"]]
        keyboard = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
        text = info["text"]
    await update_message_c2(client, chat_id, msg_id, text, reply_markup=keyboard)

async def show_conversion_options_c2(client, chat_id, msg_id, text="¿Cómo quieres enviar el video?"):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🖼️ Con Miniatura", callback_data="convertopt_withthumb")], [InlineKeyboardButton("🚫 Sin Miniatura", callback_data="convertopt_nothumb")], [InlineKeyboardButton("📂 Enviar como Archivo", callback_data="convertopt_asfile")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await update_message_c2(client, chat_id, msg_id, text, reply_markup=keyboard)

async def show_rename_options_c2(client, chat_id, msg_id, text="¿Quieres renombrar el archivo?"):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Sí, renombrar", callback_data="renameopt_yes")], [InlineKeyboardButton("➡️ No, usar original", callback_data="renameopt_no")]])
    await update_message_c2(client, chat_id, msg_id, text, reply_markup=keyboard)


# ==============================================================================
# LÓGICA DEL BOT 3 (DOWNLOADER)
# ==============================================================================

DOWNLOAD_DIR_C3 = "/kaggle/working/downloads"
if not os.path.exists(DOWNLOAD_DIR_C3): os.makedirs(DOWNLOAD_DIR_C3)
url_storage_c3 = {}; chat_messages_c3 = {}

def save_msg_c3(chat_id, msg_id):
    if chat_id not in chat_messages_c3: chat_messages_c3[chat_id] = []
    chat_messages_c3[chat_id].append(msg_id)

def search_videos_c3(query):
    ydl_opts = {'quiet': True, 'nocheckcertificate': True, 'noplaylist': True, 'extract_flat': 'in_playlist'}
    search_query = f"xvsearch5:{query}" if any(w in query.lower() for w in ["xv", "xxx", "adulto", "porno"]) else f"ytsearch5:{query}"
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_query, download=False); return info['entries']

def create_thumb_c3(video_path):
    thumb_path = f"{video_path}.jpg"
    try:
        subprocess.call(['ffmpeg', '-y', '-i', video_path, '-ss', '00:00:01', '-vframes', '1', '-q:v', '2', thumb_path])
        return thumb_path if os.path.exists(thumb_path) else None
    except: return None

def get_metadata_c3(file_path):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file_path]
    data = json.loads(subprocess.check_output(cmd).decode('utf-8'))
    duration = int(float(data['format']['duration'])); width = height = 0
    for s in data['streams']:
        if s['codec_type'] == 'video': width, height = s['width'], s['height']; break
    return duration, width, height

async def progress_bar_c3(current, total, msg, start_time):
    now = time.time()
    if now - getattr(msg, "last_upd", 0) < 3: return
    msg.last_upd = now
    pct = (current * 100 / total) if total > 0 else 0
    bar = "▰" * int(pct // 10) + "▱" * (10 - int(pct // 10))
    try: await msg.edit_text(f"📤 Subiendo...\n<code>{bar}</code> {pct:.1f}%")
    except: pass

@app3.on_message(filters.command("start"))
async def start_and_clean_c3(c, m):
    # --- VERIFICACIÓN DE PERMISOS ---
    if not await check_permissions(c, m): return
    # --------------------------------

    chat_id = m.chat.id
    if chat_id in chat_messages_c3:
        try: await c.delete_messages(chat_id, chat_messages_c3[chat_id]); chat_messages_c3[chat_id] = []
        except: pass
    try: await m.delete()
    except: pass
    welcome = await m.reply_text("✨ **¡BOT DE DESCARGAS ACTIVO!** ✨\n--------------------------------------\nEnvía un **enlace** o escribe lo que quieras **buscar**.\n*(Todo se borrará cuando uses /start)*")
    save_msg_c3(chat_id, welcome.id)

@app3.on_message(filters.text)
async def handle_text_c3(c, m):
    # --- VERIFICACIÓN DE PERMISOS (NUEVO) ---
    if not await check_permissions(c, m): 
        return
    # ----------------------------------------

    save_msg_c3(m.chat.id, m.id)
    if m.text.startswith("http"):
        status = await m.reply_text("🔎 Analizando..."); save_msg_c3(m.chat.id, status.id)
        return await show_options_c3(m.text, status)
    status = await m.reply_text(f"🔎 Buscando '{m.text}'..."); save_msg_c3(m.chat.id, status.id)
    try:
        results = search_videos_c3(m.text)
        if not results: return await status.edit_text("❌ Sin resultados.")
        buttons = []
        for video in results:
            link_id = str(uuid.uuid4())[:8]; url_storage_c3[link_id] = video.get('url') or video.get('webpage_url')
            title = video.get('title', 'Video'); buttons.append([InlineKeyboardButton(f"🎥 {title[:45]}...", callback_data=f"opts|{link_id}")])
        await status.edit_text("✅ Elige un video:", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e: await status.edit_text(f"❌ Error: {str(e)[:50]}")


async def show_options_c3(url, status_msg):
    link_id = str(uuid.uuid4())[:8]; url_storage_c3[link_id] = url
    buttons = [[InlineKeyboardButton("🎬 720p", callback_data=f"dl|{link_id}|720"), InlineKeyboardButton("🎬 360p", callback_data=f"dl|{link_id}|360")], [InlineKeyboardButton("🎵 MP3", callback_data=f"dl|{link_id}|audio")]]
    await status_msg.edit_text("📥 **Selecciona formato:**", reply_markup=InlineKeyboardMarkup(buttons))

@app3.on_callback_query(filters.regex(r"^opts\|"))
async def on_option_select_c3(c, q):
    link_id = q.data.split("|")[1]; url = url_storage_c3.get(link_id); await show_options_c3(url, q.message)

@app3.on_callback_query(filters.regex(r"^dl\|"))
async def download_logic_c3(c, q):
    _, link_id, quality = q.data.split("|"); url = url_storage_c3.get(link_id); status = await q.message.edit_text(f"⏳ Descargando...")
    path = None
    try:
        ydl_opts = {'outtmpl': f'{DOWNLOAD_DIR_C3}/%(title)s.%(ext)s', 'quiet': True}
        if quality == "audio": ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]})
        else: ydl_opts.update({'format': f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]/best'})
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            path = ydl.prepare_filename(info)
            if quality == "audio": path = os.path.splitext(path)[0] + ".mp3"
        if quality != "audio":
            thumb = create_thumb_c3(path); duration, width, height = get_metadata_c3(path)
            sent_video = await q.message.reply_video(video=path, thumb=thumb, duration=duration, width=width, height=height, caption=f"✅ **{info.get('title')}**", supports_streaming=True, progress=progress_bar_c3, progress_args=(status, time.time()))
            save_msg_c3(q.message.chat.id, sent_video.id)
            if thumb: os.remove(thumb)
        else:
            sent_audio = await q.message.reply_audio(audio=path, title=info.get('title')); save_msg_c3(q.message.chat.id, sent_audio.id)
        await status.delete()
    except Exception as e: await status.edit_text(f"❌ Error: {str(e)[:50]}")
    finally:
        if path and os.path.exists(path): os.remove(path)

# ==========================================
# EJECUCIÓN (MAIN) - VERSIÓN FINAL CORREGIDA
# ==========================================

async def main():
    print("🚀 SISTEMA INICIADO...")
    
    # Iniciamos el servidor Flask en otro hilo
    try:
        Thread(target=run_flask_server, daemon=True).start()
    except Exception as e:
        print(f"⚠️ Error al iniciar Flask: {e}")

    # Iniciamos los 4 bots
    await app1.start()
    await app2.start()
    await app3.start()
    await app4.start()
    
    try:
        me1 = await app1.get_me()
        me2 = await app2.get_me()
        me3 = await app3.get_me()
        me4 = await app4.get_me()

        print(f"✅ Bot Uploader: @{me1.username}")
        print(f"✅ Bot AnzelGo (Integrado): @{me2.username}")
        print(f"✅ Bot Descargas: @{me3.username}")
        print(f"✅ Master Controller: @{me4.username}")
    except Exception as e:
        print(f"⚠️ Error al obtener info de los bots: {e}")

    # Mantenemos vivo el loop
    print("🔔 Bots en línea y operando desde la nube de Kaggle.")
    await idle()
    
    # Al detenerse
    await app1.stop()
    await app2.stop()
    await app3.stop()
    await app4.stop()

if __name__ == "__main__":
    try:
        # Ejecución del loop principal
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("\n🛑 Detenido por el usuario.")
    except Exception as e:
        print(f"❌ Error crítico: {e}")
