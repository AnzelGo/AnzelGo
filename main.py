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
app1 = Client("bot1", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT1_TOKEN"), workers=100)
app2 = Client("bot2", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT2_TOKEN"), workers=100)
app3 = Client("bot3", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT3_TOKEN"), workers=100)
app4 = Client("bot4", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT4_TOKEN"), workers=100)


# ==========================================
# ⚙️ CONFIGURACIÓN Y ESTADO GLOBAL (ESTILO REFERENCIA)
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

# --- VARIABLES GLOBALES ---
SYSTEM_MODE, ALLOWED_USERS = load_config()
WAITING_FOR_ID = False
VIEWING_LIST = False
PANEL_MSG_ID = None

# ==========================================
# 🛡️ LÓGICA DE PERMISOS
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
    else: return False

    if user_id == ADMIN_ID: return True

    if SYSTEM_MODE == "OFF":
        msg_off = "⛔ **SISTEMA EN MANTENIMIENTO**\nLos bots están temporalmente fuera de servicio por actualizaciones técnicas."
        if isinstance(update, CallbackQuery): await reply_method("⛔ Mantenimiento activo.", show_alert=True)
        elif chat_type == "private": await reply_method(msg_off, quote=True)
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
            if isinstance(update, CallbackQuery): await reply_method("🔒 Acceso Denegado (Modo VIP)", show_alert=True)
            elif chat_type == "private": await update.reply_text(msg_priv, reply_markup=btn, quote=True)
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
    return (f"👮‍♂️ <b>SISTEMA DE CONTROL DE ACCESO</b>\n"
            f"<code>──────────────────────</code>\n"
            f"📊 <b>Estado:</b> <code>{SYSTEM_MODE}</code>\n"
            f"👥 <b>Usuarios:</b> <code>{len(ALLOWED_USERS)}</code>\n"
            f"<code>──────────────────────</code>\n"
            f"<i>Gestione los accesos del sistema:</i>")

@app4.on_callback_query(filters.user(ADMIN_ID))
async def controller_callbacks(c, q):
    global SYSTEM_MODE, WAITING_FOR_ID, ALLOWED_USERS, PANEL_MSG_ID
    data = q.data
    PANEL_MSG_ID = q.message.id 
    if data.startswith("set_"):
        SYSTEM_MODE = data.split("_")[1]
        save_config()
        await q.message.edit_text(get_panel_text(), reply_markup=get_panel_menu())
    elif data == "ui_add":
        WAITING_FOR_ID = True
        await q.message.edit_text("✍️ <b>INGRESE ID DEL USUARIO</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 CANCELAR", callback_data="ui_home")]]))
    elif data == "ui_list":
        if not ALLOWED_USERS: return await q.answer("No hay usuarios autorizados.", show_alert=True)
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
        if uid in ALLOWED_USERS: ALLOWED_USERS.remove(uid); save_config()
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
            WAITING_FOR_ID = False; await m.delete()
            if PANEL_MSG_ID: await c.edit_message_text(m.chat.id, PANEL_MSG_ID, get_panel_text(), reply_markup=get_panel_menu())
            return 
        except: pass
    new_panel = await m.reply_text(get_panel_text(), reply_markup=get_panel_menu())
    PANEL_MSG_ID = new_panel.id

# ==============================================================================
# LÓGICA DEL BOT 1 (UPLOADER)
# ==============================================================================

GOFILE_TOKEN = os.getenv("GOFILE_TOKEN") 
CATBOX_HASH = os.getenv("CATBOX_HASH")
PIXELDRAIN_KEY = os.getenv("PIXELDRAIN_KEY")
user_preference_c1 = {}

async def upload_file_c1(path, server):
    headers = {'User-Agent': 'Mozilla/5.0'}
    async with aiohttp.ClientSession(headers=headers) as s:
        with open(path, 'rb') as f:
            if server == "Litterbox":
                data = aiohttp.FormData(); data.add_field('reqtype', 'fileupload'); data.add_field('time', '72h'); data.add_field('fileToUpload', f)
                async with s.post("https://litterbox.catbox.moe/resources/internals/api.php", data=data) as r: return (await r.text()).strip()
            elif server == "Catbox":
                data = aiohttp.FormData(); data.add_field('reqtype', 'fileupload')
                if CATBOX_HASH: data.add_field('userhash', CATBOX_HASH.strip())
                data.add_field('fileToUpload', f)
                async with s.post("https://catbox.moe/user/api.php", data=data) as r: return (await r.text()).strip()
            elif server == "GoFile":
                try:
                    async with s.get("https://api.gofile.io/servers") as gs:
                        s_res = await gs.json(); s_name = s_res['data']['servers'][0]['name']
                    data = aiohttp.FormData(); data.add_field('file', f, filename=os.path.basename(path))
                    if GOFILE_TOKEN: data.add_field('token', GOFILE_TOKEN.strip())
                    async with s.post(f"https://{s_name}.gofile.io/contents/uploadfile", data=data) as r:
                        res = await r.json(); return res['data']['downloadPage']
                except: return None
            elif server == "Pixeldrain":
                auth = aiohttp.BasicAuth(login="", password=PIXELDRAIN_KEY.strip() if PIXELDRAIN_KEY else "")
                data = aiohttp.FormData(); data.add_field('file', f)
                async with s.post("https://pixeldrain.com/api/file", data=data, auth=auth) as r:
                    res = await r.json(); return f"https://pixeldrain.com/api/file/{res['id']}" if r.status in [200, 201] else None
    return None

async def progress_bar_c1(current, total, msg, start_time, server_name):
    now = time.time()
    if now - getattr(msg, "last_upd", 0) < 4: return
    msg.last_upd = now
    percentage = current * 100 / total
    bar = "▰" * int(percentage/10) + "▱" * (10 - int(percentage/10))
    speed = current / (now - start_time) if (now - start_time) > 0 else 0
    txt = (f"<b>Descargando...</b>\n<code>{bar}</code> {percentage:.1f}%\n📊 <b>Velocidad:</b> <code>{speed/1024**2:.1f} MB/s</code>")
    try: await msg.edit_text(txt)
    except: pass

@app1.on_message(filters.command("start"))
async def start_cmd_c1(_, m):
    if not await check_permissions(_, m): return
    await m.reply_text("<b>💎 CLOUD UPLOADER PREMIUM</b>", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚀 Litterbox"), KeyboardButton("📦 Catbox")], [KeyboardButton("⚡ GoFile"), KeyboardButton("💎 Pixeldrain")]], resize_keyboard=True), quote=True)

@app1.on_message(filters.regex("^(🚀 Litterbox|📦 Catbox|⚡ GoFile|💎 Pixeldrain)$"))
async def set_server_c1(_, m):
    user_preference_c1[m.from_user.id] = m.text.split(" ")[1]
    await m.reply_text(f"✅ <b>Servidor configurado:</b> <code>{user_preference_c1[m.from_user.id].upper()}</code>")

@app1.on_message(filters.media)
async def handle_media_c1(c, m):
    if not await check_permissions(c, m): return
    uid = m.from_user.id
    if uid not in user_preference_c1: return await m.reply_text("⚠️ Seleccione servidor.")
    server = user_preference_c1[uid]
    status = await m.reply_text(f"📤 Preparando archivo...", quote=True)
    path = await c.download_media(m, file_name=f"./temp_{uid}/", progress=progress_bar_c1, progress_args=(status, time.time(), server))
    link = await upload_file_c1(path, server)
    if link:
        final_text = (f"𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !\n\n📦 Fɪʟᴇ ꜱɪᴢᴇ : {os.path.getsize(path)/1024**2:.2f} MiB\n📥 Dᴏᴡɴʟᴏᴀᴅ : <code>{link}</code>")
        await status.edit_text(final_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("sᴛʀᴇᴀüm", url=link),InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="close_all")]]))
    else: await status.edit_text("❌ Error al subir.")
    if os.path.exists(path): os.remove(path)

# ==============================================================================
# LÓGICA DEL BOT 2 (VIDEO PROCESSOR / ANZEL) - COMPRESIÓN MULTI-USUARIO FIX
# ==============================================================================

DOWNLOAD_DIR_C2 = "downloads"
os.makedirs(DOWNLOAD_DIR_C2, exist_ok=True)
user_data_c2 = {}

def is_gpu_available_c2():
    try:
        subprocess.check_output(['nvidia-smi'], stderr=subprocess.STDOUT)
        return True
    except: return False

def format_size_c2(size_bytes):
    if size_bytes < 1024**2: return f"{size_bytes/1024:.2f} KB"
    if size_bytes < 1024**3: return f"{size_bytes/1024**2:.2f} MB"
    return f"{size_bytes/1024**3:.2f} GB"

async def progress_bar_handler_c2(current, total, client, message, start_time, action_text):
    now = time.time()
    if now - getattr(message, "last_upd", 0) < 5: return
    message.last_upd = now
    pct = (current * 100 / total) if total > 0 else 0
    bar = "■" * int(pct // 10) + "□" * (10 - int(pct // 10))
    speed = current / (now - start_time) if (now - start_time) > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0
    txt = (f"**{action_text}**\n`[{bar}] {pct:.1f}%`\n\n**Tamaño:** `{format_size_c2(current)} / {format_size_c2(total)}`\n**Velocidad:** `{format_size_c2(speed)}/s` | **ETA:** `{time.strftime('%H:%M:%S', time.gmtime(eta))}`")
    try: await client.edit_message_text(message.chat.id, message.id, txt)
    except: pass

async def track_ffmpeg_progress_c2(client, chat_id, msg_id, process, duration, original_size, output_path):
    last_upd = 0
    while True:
        line = await process.stdout.readline()
        if not line: break
        line = line.decode('utf-8')
        if "out_time_us" in line:
            now = time.time()
            if now - last_upd < 4: continue
            last_upd = now
            us = int(line.split('=')[1])
            pct = min((us / 1_000_000 / duration) * 100, 100) if duration > 0 else 0
            bar = "■" * int(pct // 10) + "□" * (10 - int(pct // 10))
            cur_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            try: await client.edit_message_text(chat_id, msg_id, f"**COMPRIMIENDO...**\n`[{bar}] {pct:.1f}%`\n\n**Tamaño:** `{format_size_c2(cur_size)} / {format_size_c2(original_size)}`")
            except: pass
    await process.wait(); return process.returncode == 0

async def run_compression_task_c2(client, chat_id, status_message):
    user_info = user_data_c2.get(chat_id)
    try:
        # Descarga
        original = await client.get_messages(chat_id, user_info['original_message_id'])
        work_dir = os.path.join(DOWNLOAD_DIR_C2, uuid.uuid4().hex[:8])
        os.makedirs(work_dir)
        path = await client.download_media(original, file_name=work_dir + "/", progress=progress_bar_handler_c2, progress_args=(client, status_message, time.time(), "📥 DESCARGANDO..."))
        
        # Compresión
        opts = user_info['compression_options']
        output = os.path.join(work_dir, "output.mp4")
        probe = ffmpeg.probe(path); duration = float(probe['format']['duration']); orig_size = os.path.getsize(path)

        if is_gpu_available_c2():
            cmd = ['ffmpeg', '-hwaccel', 'cuda', '-i', path, '-vf', f"scale=-2:{opts['resolution']}", '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', opts['crf'], '-acodec', 'aac', '-b:a', '64k', '-progress', 'pipe:1', '-y', output]
        else:
            cmd = ['ffmpeg', '-i', path, '-vf', f"scale=-2:{opts['resolution']}", '-crf', opts['crf'], '-preset', opts['preset'], '-vcodec', 'libx264', '-acodec', 'aac', '-threads', '0', '-progress', 'pipe:1', '-y', output]

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        if await track_ffmpeg_progress_c2(client, chat_id, status_message.id, process, duration, orig_size, output):
            user_info['final_path'] = output
            await show_conversion_options_c2(client, chat_id, status_message.id, text="✅ Compresión Exitosa. ¿Cómo lo enviamos?")
        if os.path.exists(path): os.remove(path)
    except Exception as e: await client.send_message(chat_id, f"❌ Error: {e}")

@app2.on_message(filters.video & filters.private)
async def video_handler_c2(c, m):
    if not await check_permissions(c, m): return
    user_data_c2[m.chat.id] = {'original_message_id': m.id, 'video_file_name': m.video.file_name or "video.mp4"}
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")], [InlineKeyboardButton("⚙️ Solo Enviar", callback_data="action_convert_only")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await m.reply_text("Video recibido. ¿Qué quieres hacer?", reply_markup=kb, quote=True)

@app2.on_callback_query()
async def cb_handler_c2(c, cb):
    chat_id, ui = cb.message.chat.id, user_data_c2.get(cb.message.chat.id)
    if not ui: return await cb.answer("Expirado.")
    ui['status_message_id'] = cb.message.id
    if cb.data == "action_compress":
        ui['compression_options'] = {'crf': '24' if is_gpu_available_c2() else '22', 'resolution': '360', 'preset': 'veryfast'}
        await show_compression_options_c2(c, chat_id, cb.message.id)
    elif cb.data == "compressopt_default":
        await cb.message.edit("Iniciando..."); asyncio.create_task(run_compression_task_c2(c, chat_id, cb.message))
    elif cb.data == "compressopt_advanced": await show_advanced_menu_c2(c, chat_id, cb.message.id, "crf")
    elif cb.data.startswith("adv_"):
        p, v = cb.data.split("_")[1], cb.data.split("_")[2]
        ui.setdefault('compression_options', {})[p] = v
        nx = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(p)
        if nx: await show_advanced_menu_c2(c, chat_id, cb.message.id, nx, ui['compression_options'])
    elif cb.data == "start_advanced_compression":
        await cb.message.edit("Iniciando..."); asyncio.create_task(run_compression_task_c2(c, chat_id, cb.message))
    elif cb.data == "convertopt_nothumb": ui['thumbnail_path'] = None; await show_rename_options_c2(c, chat_id, cb.message.id)
    elif cb.data == "renameopt_no": ui['new_name'] = None; asyncio.create_task(upload_final_video_c2(c, chat_id))

async def upload_final_video_c2(client, chat_id):
    ui = user_data_c2.get(chat_id)
    f_path, status_id = ui['final_path'], ui['status_message_id']
    file_name = ui.get('new_name') or os.path.basename(ui['video_file_name'])
    if not file_name.endswith(".mp4"): file_name += ".mp4"
    try:
        await client.edit_message_text(chat_id, status_id, "⬆️ SUBIENDO...")
        await client.send_video(chat_id, video=f_path, caption=f"`{file_name}`", supports_streaming=True, progress=progress_bar_handler_c2, progress_args=(client, await client.get_messages(chat_id, status_id), time.time(), "⬆️ Subiendo"))
        await client.delete_messages(chat_id, status_id)
    finally:
        shutil.rmtree(os.path.dirname(f_path), ignore_errors=True); user_data_c2.pop(chat_id)

async def show_compression_options_c2(c, cid, mid):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Usar Recomendados", callback_data="compressopt_default")], [InlineKeyboardButton("⚙️ Avanzado", callback_data="compressopt_advanced")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await c.edit_message_text(cid, mid, "Elige cómo quieres comprimir:", reply_markup=kb)

async def show_advanced_menu_c2(c, cid, mid, part, opts=None):
    if part == "confirm":
        text = f"Confirmar:\n- Calidad: `{opts.get('crf')}`\n- Res: `{opts.get('resolution')}p`"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Iniciar", callback_data="start_advanced_compression")]])
    else:
        titles = {"crf": "1/3 Calidad", "resolution": "2/3 Res", "preset": "3/3 Velocidad"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Confirmar", callback_data=f"adv_{part}_val")]])
        text = titles.get(part, part)
    await c.edit_message_text(cid, mid, text, reply_markup=kb)

async def show_conversion_options_c2(c, cid, mid, text="¿Cómo quieres enviar?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Sin Mini", callback_data="convertopt_nothumb")], [InlineKeyboardButton("📂 Como Archivo", callback_data="convertopt_asfile")]])
    await c.edit_message_text(cid, mid, text, reply_markup=kb)

async def show_rename_options_c2(c, cid, mid, text="¿Renombrar?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Sí", callback_data="renameopt_yes")], [InlineKeyboardButton("➡️ No", callback_data="renameopt_no")]])
    await c.edit_message_text(cid, mid, text, reply_markup=kb)

# ==============================================================================
# LÓGICA DEL BOT 3 (DOWNLOADER) - MULTI-HILO FIX
# ==============================================================================

@app3.on_message(filters.command("start"))
async def start_c3(c, m):
    if not await check_permissions(c, m): return
    await m.reply_text("✨ **¡BOT DE DESCARGAS ACTIVO!** ✨")

@app3.on_callback_query(filters.regex(r"^dl\|"))
async def dl_c3(c, q):
    _, link_id, quality = q.data.split("|"); url = url_storage_c3.get(link_id)
    status = await q.message.edit_text("⏳ Descargando..."); task_dir = f"dl_{uuid.uuid4().hex[:5]}"
    os.makedirs(task_dir, exist_ok=True)
    # 10 hilos por descarga
    opts = {'format': f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best', 'outtmpl': f'{task_dir}/%(title)s.%(ext)s', 'concurrent_fragment_downloads': 10, 'quiet': True}
    try:
        with YoutubeDL(opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            p = ydl.prepare_filename(info)
            await c.send_video(q.message.chat.id, p, caption=f"✅ {info['title']}", progress=progress_bar_c1, progress_args=(status, time.time(), "Telegram"))
    finally:
        shutil.rmtree(task_dir); await status.delete()

# ==========================================
# EJECUCIÓN (MAIN)
# ==========================================

async def main():
    def run_f():
        app_f = Flask(__name__)
        @app_f.route('/')
        def h(): return "Bots Online"
        app_f.run(host='0.0.0.0', port=8000)
    Thread(target=run_f, daemon=True).start()
    await asyncio.gather(app1.start(), app2.start(), app3.start(), app4.start())
    await idle()

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass
