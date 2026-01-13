# ==========================================
# PRU3BA IMPORTACIONES GLOBALES
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

# Inicialización de las 4 apps
app1 = Client("bot1", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT1_TOKEN"))
app2 = Client("bot2", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT2_TOKEN"))
app3 = Client("bot3", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT3_TOKEN"))
app4 = Client("bot4", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT4_TOKEN"))


# ==========================================
# ⚙️ CONFIGURACIÓN Y PERSISTENCIA (ESTADO)
# ==========================================

CONFIG_FILE = "system_config.json"
ADMIN_ID = int(os.getenv("ADMIN_ID", "12345678"))

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

SYSTEM_MODE, ALLOWED_USERS = load_config()
WAITING_FOR_ID = False
TEMP_MSG_ID = None # Para rastrear el mensaje de "Ingrese ID"
# ==========================================
# 🛡️ SEGURIDAD (MENSAJE VIP PERSONALIZADO)
# ==========================================

async def check_permissions(client, update):
    user_id = update.from_user.id if update.from_user else 0
    chat_type = update.chat.type.value if hasattr(update, 'chat') else "private"
    
    if user_id == ADMIN_ID: return True

    if SYSTEM_MODE == "OFF":
        if isinstance(update, CallbackQuery): await update.answer("⛔ Mantenimiento.", show_alert=True)
        elif chat_type == "private": await update.reply_text("⛔ **SISTEMA EN MANTENIMIENTO**")
        return False

    if SYSTEM_MODE == "PRIVATE":
        if user_id not in ALLOWED_USERS:
            msg_priv = (
                "🔒 **ACCESO RESTRINGIDO** 🔒\n\n"
                "Este bot está operando en **Modo Privado** (Prioridad Premium). "
                "Actualmente solo usuarios autorizados tienen acceso.\n\n"
                "Pulsa abajo para solicitar acceso al administrador."
            )
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("📩 SOLICITAR ACCESO", url=f"https://t.me/AnzZGTv1?text=Hola,%20solicito%20acceso.%20ID:%20{user_id}")]])
            if isinstance(update, CallbackQuery): await update.answer("🔒 Modo Privado.", show_alert=True)
            else: await update.reply_text(msg_priv, reply_markup=btn)
            return False
    return True

# ==========================================
# 🎮 CONTROLADOR (BOT 4) - DISEÑO MINIMALISTA
# ==========================================

def get_panel_menu():
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
            InlineKeyboardButton("➕ AGREGAR ID", callback_data="ui_add"),
            InlineKeyboardButton(f"📋 LISTA VIP ({len(ALLOWED_USERS)})", callback_data="ui_list")
        ]
    ])

def get_panel_text():
    return (
        f"👮‍♂️ <b>SISTEMA DE CONTROL DE ACCESO</b>\n"
        f"<code>──────────────────────</code>\n"
        f"📊 <b>Estado Actual:</b> <code>{SYSTEM_MODE}</code>\n"
        f"👥 <b>Usuarios VIP:</b>  <code>{len(ALLOWED_USERS)}</code>\n"
        f"<code>──────────────────────</code>\n"
        f"<i>Seleccione el modo de operación:</i>"
    )

async def purge_and_send_panel(c, chat_id, text=None, markup=None):
    """
    Elimina agresivamente el historial reciente y envía un panel nuevo.
    Mantiene el chat extremadamente limpio.
    """
    ids_to_delete = []
    # Escaneamos los últimos 50 mensajes para asegurar limpieza total
    async for message in c.get_chat_history(chat_id, limit=50):
        ids_to_delete.append(message.id)
    
    if ids_to_delete:
        try: await c.delete_messages(chat_id, ids_to_delete)
        except: pass # Si falla alguno antiguo, no importa
        
    return await c.send_message(chat_id, text or get_panel_text(), reply_markup=markup or get_panel_menu())

@app4.on_callback_query(filters.user(ADMIN_ID))
async def controller_callbacks(c, q):
    global SYSTEM_MODE, WAITING_FOR_ID, ALLOWED_USERS
    data = q.data
    
    if data.startswith("set_"):
        new_mode = data.split("_")[1]
        if SYSTEM_MODE != new_mode:
            SYSTEM_MODE = new_mode
            save_config()
            # Editamos en lugar de borrar para que sea fluido al cambiar modos
            await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())
        else: await q.answer(f"Ya está en {new_mode}")

    elif data == "ui_add":
        WAITING_FOR_ID = True
        # Editamos el mensaje actual para pedir el ID
        await q.message.edit_text("✍️ <b>INGRESE ID</b>\n\nEnvíe el número para autorizar:", 
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 VOLVER", callback_data="ui_home")]]))
    
    elif data == "ui_list":
        if not ALLOWED_USERS: return await q.answer("Lista vacía", show_alert=True)
        btns = []
        await q.answer("Cargando nombres...")
        for uid in ALLOWED_USERS:
            try:
                user = await c.get_users(uid)
                name = (user.first_name[:12] + "..") if len(user.first_name) > 12 else user.first_name
            except: name = f"ID: {uid}"
            btns.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"del_{uid}")])
        btns.append([InlineKeyboardButton("🔙 VOLVER", callback_data="ui_home")])
        await q.message.edit_text("📋 <b>GESTIÓN DE ACCESOS</b>", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("del_"):
        uid = int(data.split("_")[1])
        if uid in ALLOWED_USERS:
            ALLOWED_USERS.remove(uid)
            save_config()
            await q.answer("Eliminado")
            # Truco para recargar la lista sin spammear
            if ALLOWED_USERS: 
                # Re-llamamos a la lógica de ui_list manualmente
                btns = []
                for u in ALLOWED_USERS:
                     btns.append([InlineKeyboardButton(f"🗑 {u}", callback_data=f"del_{u}")]) # Simplificado para velocidad
                btns.append([InlineKeyboardButton("🔙 VOLVER", callback_data="ui_home")])
                await q.message.edit_reply_markup(InlineKeyboardMarkup(btns))
                return
        # Si no quedan usuarios o error, volvemos al home
        await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())

    elif data == "ui_home":
        WAITING_FOR_ID = False
        await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())

@app4.on_message(filters.user(ADMIN_ID) & filters.private & ~filters.command("start"))
async def admin_input_listener(c, m):
    global WAITING_FOR_ID, ALLOWED_USERS
    # Si estamos esperando ID y hay texto
    if WAITING_FOR_ID and m.text:
        try:
            target_id = int("".join(filter(str.isdigit, m.text)))
            if target_id not in ALLOWED_USERS:
                ALLOWED_USERS.append(target_id)
                save_config()
            WAITING_FOR_ID = False
            # AQUÍ LA MAGIA: Borramos todo (input del admin + mensaje del bot) y mostramos panel limpio
            await purge_and_send_panel(c, m.chat.id)
        except:
            # Si falla, borramos el mensaje erróneo del usuario y avisamos brevemente
            try: await m.delete() 
            except: pass
            tmp = await m.reply("❌ ID Inválido")
            await asyncio.sleep(1.5)
            await tmp.delete()

@app4.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_handler(c, m):
    global WAITING_FOR_ID
    WAITING_FOR_ID = False
    # Al poner start, borra TODO lo anterior y muestra solo el panel
    await purge_and_send_panel(c, m.chat.id)

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
        downloaded_path = await download_video_c2(client, chat_id, status_message)
        if not downloaded_path: return

        user_info = user_data_c2[chat_id]
        user_info['state'] = 'compressing'
        opts = user_info['compression_options']
        output_path = os.path.join(DOWNLOAD_DIR_C2, f"compressed_{chat_id}.mp4")

        probe = ffmpeg.probe(downloaded_path)
        duration = float(probe.get('format', {}).get('duration', 0))
        original_size = os.path.getsize(downloaded_path)

        if is_gpu_available_c2():
            await update_message_c2(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO (GPU)...")
            preset_map = {'ultrafast': 'p1', 'veryfast': 'p2', 'fast': 'p3', 'medium': 'p4', 'slow': 'p6'}
            gpu_preset = preset_map.get(opts['preset'], 'p4')
            cmd = [
                'ffmpeg', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda',
                '-i', downloaded_path,
                '-vf', f"scale_cuda=-2:{opts['resolution']}",
                '-c:v', 'h264_nvenc', '-preset', gpu_preset,
                '-rc', 'vbr', '-cq', opts['crf'], '-b:v', '0',
                '-acodec', 'aac', '-b:a', '64k', '-movflags', '+faststart',
                '-progress', 'pipe:1', '-nostats', '-y', output_path
            ]
            engine_text = "GPU T4"
        else:
            await update_message_c2(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO...")
            cmd = [
                'ffmpeg', '-i', downloaded_path,
                '-vf', f"scale=-2:{opts['resolution']}",
                '-r', '30', '-crf', opts['crf'], '-preset', opts['preset'],
                '-vcodec', 'libx264', '-acodec', 'aac', '-b:a', '64k',
                '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', '-y', output_path
            ]
            engine_text = "Estándar"

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        success = await track_ffmpeg_progress_c2(client, chat_id, status_message.id, process, duration, original_size, output_path)

        if not success:
            await update_message_c2(client, chat_id, status_message.id, "❌ Error de compresión.")
            return

        user_info['final_path'] = output_path
        compressed_size = os.path.getsize(output_path)
        reduction = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
        
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

    if action == "cancel":
        user_info['state'] = 'cancelled'
        await cb.message.edit("Operación cancelada.")
        clean_up_c2(chat_id)
    elif action == "action_compress":
        is_gpu = is_gpu_available_c2()
        user_info['compression_options'] = {'crf': '24' if is_gpu else '22', 'resolution': '360', 'preset': 'veryfast'}
        await show_compression_options_c2(client, chat_id, cb.message.id)
    elif action == "compressopt_default":
        await cb.message.edit(f"Iniciando compresión {'GPU' if is_gpu_available_c2() else ''}...")
        await run_compression_flow_c2(client, chat_id, cb.message)
    elif action == "compressopt_advanced":
        await show_advanced_menu_c2(client, chat_id, cb.message.id, "crf")
    elif action.startswith("adv_"):
        part, value = action.split("_")[1], action.split("_")[2]
        user_info.setdefault('compression_options', {})[part] = value
        next_step = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(part)
        if next_step: await show_advanced_menu_c2(client, chat_id, cb.message.id, next_step, user_info['compression_options'])
    elif action == "start_advanced_compression":
        await cb.message.edit(f"Opciones guardadas. Iniciando compresión {'GPU' if is_gpu_available_c2() else ''}...")
        await run_compression_flow_c2(client, chat_id, cb.message)
    elif action == "action_convert_only":
        await cb.message.edit("Iniciando descarga...")
        if await download_video_c2(client, chat_id, cb.message):
            await show_conversion_options_c2(client, chat_id, cb.message.id, text="Descarga completa. ¿Cómo quieres continuar?")
    elif action == "convertopt_withthumb":
        user_info['state'] = 'waiting_for_thumbnail'
        await cb.message.edit("Por favor, envía la imagen para la miniatura.")
    elif action == "convertopt_nothumb":
        user_info['thumbnail_path'] = None
        await show_rename_options_c2(client, chat_id, cb.message.id)
    elif action == "convertopt_asfile":
        user_info['send_as_file'] = True
        await show_rename_options_c2(client, chat_id, cb.message.id)
    elif action == "renameopt_yes":
        user_info['state'] = 'waiting_for_new_name'
        await cb.message.edit("Ok, envíame el nuevo nombre (sin extensión).")
    elif action == "renameopt_no":
        user_info['new_name'] = None
        user_info['state'] = 'uploading'
        await cb.message.edit("Entendido. Preparando para subir...")
        await upload_final_video_c2(client, chat_id)

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

@app2.on_message(filters.text & filters.private)
async def rename_handler_c2(client, message: Message):
    chat_id, user_info = message.chat.id, user_data_c2.get(message.chat.id)
    if not user_info or user_info.get('state') != 'waiting_for_new_name': return
    user_info['new_name'] = message.text.strip()
    await message.delete()
    await update_message_c2(client, chat_id, user_info['status_message_id'], f"✅ Nombre guardado. Preparando para subir...")
    user_info['state'] = 'uploading'
    await upload_final_video_c2(client, chat_id)

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
# EJECUCIÓN (MAIN)
# ==========================================

async def main():
    print("🚀 SISTEMA INICIADO...")
    
    # Iniciamos el servidor Flask en otro hilo
    Thread(target=run_flask_server).start()

    # Iniciamos los 4 bots
    await app1.start()
    await app2.start()
    await app3.start()
    await app4.start()
    
    me1 = await app1.get_me()
    me2 = await app2.get_me()
    me3 = await app3.get_me()
    me4 = await app4.get_me()

    print(f"✅ Bot Uploader: @{me1.username}")
    print(f"✅ Bot AnzelGo (Integrado): @{me2.username}")
    print(f"✅ Bot Descargas: @{me3.username}")
    print(f"✅ Master Controller: @{me4.username}")

    # Mantenemos vivo el loop
    await idle()
    
    # Al detenerse
    await app1.stop(); await app2.stop(); await app3.stop(); await app4.stop()

if __name__ == "__main__":
    try: asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt: pass
