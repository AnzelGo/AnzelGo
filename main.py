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

# Aplicar nest_asyncio
nest_asyncio.apply()

# Configuración desde variables de entorno
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1806990534")) 

# CLIENTES CON MÁXIMO PARALELISMO (Workers=200)
app1 = Client("bot1", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT1_TOKEN"), workers=200)
app2 = Client("bot2", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT2_TOKEN"), workers=200)
app3 = Client("bot3", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT3_TOKEN"), workers=200)
app4 = Client("bot4", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT4_TOKEN"), workers=200)

# ==========================================
# ⚙️ CONFIGURACIÓN Y ESTADO GLOBAL
# ==========================================
CONFIG_FILE = "system_config.json"

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
PANEL_MSG_ID = None

# Almacenes para multi-usuario
user_preference_c1 = {}
user_data_c2 = {}
url_storage_c3 = {}

# ==========================================
# 🛡️ LÓGICA DE PERMISOS
# ==========================================
async def check_permissions(client, update):
    if isinstance(update, Message):
        user_id = update.from_user.id
        reply_method = update.reply_text
    elif isinstance(update, CallbackQuery):
        user_id = update.from_user.id
        reply_method = update.answer
    else: return False

    if user_id == ADMIN_ID: return True

    if SYSTEM_MODE == "OFF":
        msg_off = "⛔ **SISTEMA EN MANTENIMIENTO**"
        if isinstance(update, CallbackQuery): await reply_method("⛔ Mantenimiento.", show_alert=True)
        else: await reply_method(msg_off, quote=True)
        return False

    if SYSTEM_MODE == "PRIVATE" and user_id not in ALLOWED_USERS:
        msg_priv = "🔒 **ACCESO RESTRINGIDO** 🔒\nEste bot está en Modo Privado."
        if isinstance(update, CallbackQuery): await reply_method("🔒 Acceso VIP", show_alert=True)
        else: await update.reply_text(msg_priv, quote=True)
        return False
    return True

# ==========================================
# 🎮 CONTROLADOR (BOT 4)
# ==========================================
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
    return f"👮‍♂️ <b>PANEL DE CONTROL</b>\n📊 Estado: <code>{SYSTEM_MODE}</code>\n👥 Usuarios: <code>{len(ALLOWED_USERS)}</code>"

@app4.on_callback_query(filters.user(ADMIN_ID))
async def controller_callbacks(c, q):
    global SYSTEM_MODE, WAITING_FOR_ID, PANEL_MSG_ID
    if q.data.startswith("set_"):
        SYSTEM_MODE = q.data.split("_")[1]
        save_config()
        await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())
    elif q.data == "ui_add":
        WAITING_FOR_ID = True
        await q.message.edit_text("✍️ Ingrese ID:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="ui_home")]]))
    elif q.data == "ui_home":
        WAITING_FOR_ID = False
        await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())

@app4.on_message(filters.user(ADMIN_ID) & filters.private)
async def admin_input_listener(c, m):
    global WAITING_FOR_ID, PANEL_MSG_ID
    if WAITING_FOR_ID and m.text.isdigit():
        uid = int(m.text)
        if uid not in ALLOWED_USERS: ALLOWED_USERS.append(uid); save_config()
        WAITING_FOR_ID = False; await m.delete()
        if PANEL_MSG_ID: await c.edit_message_text(m.chat.id, PANEL_MSG_ID, get_panel_text(), reply_markup=get_panel_menu()); return
    panel = await m.reply_text(get_panel_text(), reply_markup=get_panel_menu())
    PANEL_MSG_ID = panel.id

# ==============================================================================
# BOT 2 (ANZEL) - SOLUCIÓN AL BLOQUEO Y PROGRESO DE FFmpeg
# ==============================================================================
DOWNLOAD_DIR_C2 = "downloads_anzel"
os.makedirs(DOWNLOAD_DIR_C2, exist_ok=True)

def is_gpu_available_c2():
    try:
        subprocess.check_output(['nvidia-smi'], stderr=subprocess.STDOUT)
        return True
    except: return False

def format_size_c2(b):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024: return f"{b:.2f} {unit}"
        b /= 1024

async def progress_bar_handler_c2(current, total, client, message, start_time, action_text):
    now = time.time()
    if now - getattr(message, "last_upd", 0) < 5: return
    message.last_upd = now
    percentage = (current * 100 / total) if total > 0 else 0
    bar = "■" * int(percentage // 10) + "□" * (10 - int(percentage // 10))
    speed = current / (now - start_time) if (now - start_time) > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0
    txt = (f"**{action_text}**\n`[{bar}] {percentage:.1f}%`\n\n"
           f"**Tamaño:** `{format_size_c2(current)} / {format_size_c2(total)}`\n"
           f"**Velocidad:** `{format_size_c2(speed)}/s` | **ETA:** `{time.strftime('%H:%M:%S', time.gmtime(eta))}`")
    try: await message.edit_text(txt)
    except: pass

@app2.on_message(filters.video & filters.private)
async def video_handler_c2(c, m):
    if not await check_permissions(c, m): return
    chat_id = m.chat.id
    uid = uuid.uuid4().hex[:8]
    work_dir = os.path.join(DOWNLOAD_DIR_C2, f"{chat_id}_{uid}")
    os.makedirs(work_dir, exist_ok=True)

    user_data_c2[chat_id] = {
        'work_dir': work_dir,
        'original_msg_id': m.id,
        'video_name': m.video.file_name or f"video_{uid}.mp4"
    }
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")], [InlineKeyboardButton("⚙️ Solo Enviar", callback_data="action_convert_only")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await m.reply_text("Video recibido. ¿Qué quieres hacer?", reply_markup=kb, quote=True)

@app2.on_callback_query()
async def callback_c2(c, q):
    chat_id = q.message.chat.id
    if chat_id not in user_data_c2: return await q.answer("Expirado.")
    info = user_data_c2[chat_id]
    info['status_id'] = q.message.id

    if q.data == "action_compress":
        is_gpu = is_gpu_available_c2()
        info['opts'] = {'crf': '24' if is_gpu else '22', 'res': '360', 'preset': 'veryfast'}
        # Menu avanzado
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Usar Recomendados", callback_data="start_flow_compress")], [InlineKeyboardButton("⚙️ Avanzado", callback_data="adv_crf")]])
        await q.message.edit_text("Configuración de compresión:", reply_markup=kb)
    elif q.data == "start_flow_compress":
        await q.message.edit_text("Iniciando descarga...")
        asyncio.create_task(run_full_flow_c2(c, chat_id, "compress"))
    elif q.data == "action_convert_only":
        await q.message.edit_text("Iniciando descarga...")
        asyncio.create_task(run_full_flow_c2(c, chat_id, "convert"))
    # [Resto de callbacks: thumb, rename, cancel, etc. se manejan similar llamando a create_task]

async def run_full_flow_c2(c, chat_id, mode):
    info = user_data_c2[chat_id]
    status = await c.get_messages(chat_id, info['status_id'])
    original = await c.get_messages(chat_id, info['original_msg_id'])
    
    # 1. DESCARGA (AHORA NO BLOQUEA A OTROS)
    path = await c.download_media(original, file_name=info['work_dir']+"/", progress=progress_bar_handler_c2, progress_args=(c, status, time.time(), "📥 DESCARGANDO"))
    info['file_path'] = path

    if mode == "compress":
        out = os.path.join(info['work_dir'], "output.mp4")
        probe = ffmpeg.probe(path)
        duration = float(probe['format']['duration'])
        
        is_gpu = is_gpu_available_c2()
        cmd = ['ffmpeg', '-i', path, '-vcodec', 'libx264', '-crf', '24', '-preset', 'veryfast', '-vf', 'scale=-2:480', '-progress', 'pipe:1', '-y', out]
        if is_gpu:
            cmd = ['ffmpeg', '-hwaccel', 'cuda', '-i', path, '-c:v', 'h264_nvenc', '-cq', '28', '-vf', 'scale=-2:480', '-progress', 'pipe:1', '-y', out]

        # 2. PROGRESO DE FFMPEG (RESTAURADO)
        process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        while True:
            line = await process.stdout.readline()
            if not line: break
            line = line.decode('utf-8')
            if "out_time_us" in line:
                time_us = int(line.split('=')[1])
                percentage = (time_us / 1000000) / duration * 100
                bar = "■" * int(percentage // 10) + "□" * (10 - int(percentage // 10))
                try: await status.edit_text(f"**🗜️ COMPRIMIENDO...**\n`[{bar}] {percentage:.1f}%`")
                except: pass
        await process.wait()
        info['file_path'] = out

    # Finalizar flujo (Mostrar opciones de envío)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🖼️ Con Miniatura", callback_data="send_thumb")], [InlineKeyboardButton("📂 Como Archivo", callback_data="send_file")]])
    await status.edit_text("✅ Proceso terminado. ¿Cómo enviar?", reply_markup=kb)

# ==============================================================================
# BOT 3 (DOWNLOADER) - MULTI-HILO YT-DLP
# ==============================================================================
@app3.on_callback_query(filters.regex(r"^dl\|"))
async def download_c3(c, q):
    _, link_id, quality = q.data.split("|")
    url = url_storage_c3.get(link_id)
    status = await q.message.edit_text("⏳ Preparando descarga multihilo...")
    # Tarea de fondo para que otro usuario pueda iniciar su descarga
    asyncio.create_task(run_yt_dlp_c3(c, q.message.chat.id, url, quality, status))

async def run_yt_dlp_c3(c, chat_id, url, quality, status):
    uid = uuid.uuid4().hex[:6]
    path = f"downloads_c3/{uid}/"
    os.makedirs(path, exist_ok=True)
    
    opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best',
        'outtmpl': f'{path}%(title)s.%(ext)s',
        'concurrent_fragment_downloads': 10, # Descarga veloz
        'quiet': True
    }
    
    try:
        with YoutubeDL(opts) as ydl:
            # Ejecutar en hilo separado para no bloquear el event loop
            info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            f_path = ydl.prepare_filename(info)
        
        await status.edit_text("⬆️ Subiendo a Telegram...")
        await c.send_video(chat_id, video=f_path, caption=f"✅ {info['title']}", progress=progress_bar_handler_c2, progress_args=(c, status, time.time(), "⬆️ SUBIENDO"))
        await status.delete()
    except Exception as e: await status.edit_text(f"❌ Error: {e}")
    finally: shutil.rmtree(path, ignore_errors=True)

# ==========================================
# SERVIDOR Y MAIN
# ==========================================
app_flask = Flask(__name__)
@app_flask.route('/')
def h(): return "Bots Online"

async def main():
    print("🚀 SISTEMA INICIADO...")
    Thread(target=lambda: app_flask.run(host='0.0.0.0', port=8000), daemon=True).start()
    await asyncio.gather(app1.start(), app2.start(), app3.start(), app4.start())
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
