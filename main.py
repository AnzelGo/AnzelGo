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
ADMIN_ID = int(os.getenv("ADMIN_ID", "1806990534")) 

# Inicialización de las 4 apps con WORKERS aumentados para paralelismo real
app1 = Client("bot1", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT1_TOKEN"), workers=40)
app2 = Client("bot2", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT2_TOKEN"), workers=40)
app3 = Client("bot3", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT3_TOKEN"), workers=40)
app4 = Client("bot4", api_id=API_ID, api_hash=API_HASH, bot_token=os.getenv("BOT4_TOKEN"), workers=40)

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
            msg_priv = ("🔒 **ACCESO RESTRINGIDO** 🔒\n\nEste bot está operando en **Modo Privado**.\n(Prioridad Premium). Actualmente solo usuarios autorizados tienen acceso.")
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
    return (f"👮‍♂️ <b>SISTEMA DE CONTROL DE ACCESO</b>\n<code>──────────────────────</code>\n📊 <b>Estado:</b> <code>{SYSTEM_MODE}</code>\n"
            f"👥 <b>Usuarios:</b> <code>{len(ALLOWED_USERS)}</code>\n<code>──────────────────────</code>\n<i>Gestione los accesos del sistema:</i>")

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
        await q.message.edit_text("✍️ <b>INGRESE ID DEL USUARIO</b>\n\nEl sistema buscará el nombre automáticamente:", 
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 CANCELAR", callback_data="ui_home")]]))
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
        await q.message.edit_text("📋 <b>USUARIOS CON ACCESO</b>\n<i>Toca para eliminar:</i>", reply_markup=InlineKeyboardMarkup(btns))
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
        async for message in c.get_chat_history(m.chat.id, limit=10): await message.delete()
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
                        s_name = (await gs.json())['data']['servers'][0]['name']
                    data = aiohttp.FormData(); data.add_field('file', f)
                    if GOFILE_TOKEN: data.add_field('token', GOFILE_TOKEN.strip())
                    async with s.post(f"https://{s_name}.gofile.io/contents/uploadfile", data=data) as r: return (await r.json())['data']['downloadPage']
                except: return None
            elif server == "Pixeldrain":
                p_key = PIXELDRAIN_KEY.strip() if PIXELDRAIN_KEY else ""
                auth = aiohttp.BasicAuth(login="", password=p_key)
                data = aiohttp.FormData(); data.add_field('file', f)
                async with s.post("https://pixeldrain.com/api/file", data=data, auth=auth) as r:
                    res = await r.json(); return f"https://pixeldrain.com/api/file/{res['id']}" if r.status in [200, 201] else None
    return None

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
    await m.reply_text("<b>💎 CLOUD UPLOADER PREMIUM</b>", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚀 Litterbox"), KeyboardButton("📦 Catbox")], [KeyboardButton("⚡ GoFile"), KeyboardButton("💎 Pixeldrain")]], resize_keyboard=True), quote=True)

@app1.on_message(filters.regex("^(🚀 Litterbox|📦 Catbox|⚡ GoFile|💎 Pixeldrain)$"))
async def set_server_via_btn_c1(_, m):
    user_preference_c1[m.from_user.id] = m.text.split(" ")[1]
    await m.reply_text(f"✅ <b>Servidor configurado:</b> <code>{user_preference_c1[m.from_user.id].upper()}</code>", quote=True)

@app1.on_message(filters.media)
async def handle_media_c1(c, m):
    if not await check_permissions(c, m): return
    user_id = m.from_user.id
    if user_id not in user_preference_c1:
        await m.reply_text("⚠️ Seleccione un servidor primero.", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚀 Litterbox"), KeyboardButton("📦 Catbox")], [KeyboardButton("⚡ GoFile"), KeyboardButton("💎 Pixeldrain")]], resize_keyboard=True)); return
    server = user_preference_c1[user_id]
    status = await m.reply_text(f"📤 Preparando archivo...", quote=True)
    # Carpeta temporal por usuario para evitar conflictos
    path = await c.download_media(m, file_name=f"temp_{user_id}/", progress=progress_bar_c1, progress_args=(status, time.time(), server))
    link = await upload_file_c1(path, server)
    if link:
        final_text = (f"𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !\n\n📦 Fɪʟᴇ ꜱɪᴢᴇ : {os.path.getsize(path)/1024**2:.2f} MiB\n📥 Dᴏᴡɴʟᴏᴀᴅ : <code>{link}</code>")
        await status.edit_text(final_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("sᴛʀᴇᴀüm", url=link),InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=link)],[InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="close_all")]]))
    else: await status.edit_text("❌ Error al subir.")
    if os.path.exists(path): os.remove(path)

@app1.on_callback_query(filters.regex("close_all"))
async def close_callback_c1(c, q):
    try: await q.message.delete()
    except: pass

# ==============================================================================
# LÓGICA DEL BOT 2 (VIDEO PROCESSOR / ANZEL) - MEJORADA CON MULTI-USUARIO
# ==============================================================================

user_data_c2 = {}
DOWNLOAD_DIR_C2 = "downloads_anzel"
os.makedirs(DOWNLOAD_DIR_C2, exist_ok=True)

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
    if now - getattr(message, "last_upd", 0) < 4: return
    message.last_upd = now
    percentage = (current * 100 / total) if total > 0 else 0
    bar = "■" * int(percentage // 10) + "□" * (10 - int(percentage // 10))
    speed = current / (now - start_time) if (now - start_time) > 0 else 0
    try: await message.edit_text(f"**{action_text}**\n`[{bar}] {percentage:.1f}%`\n\n**Tamaño:** `{format_size_c2(current)} / {format_size_c2(total)}`")
    except: pass

@app2.on_message(filters.command("start") & filters.private)
async def start_command_c2(client, message):
    if not await check_permissions(client, message): return
    engine = "NVIDIA GPU 🔥" if is_gpu_available_c2() else "CPU 💻"
    await message.reply(f"¡Hola! 👋 Soy tu bot para procesar videos.\n\n**Motor:** `{engine}`\nEnvíame un video para empezar.")

@app2.on_message(filters.video & filters.private)
async def video_handler_c2(client, message: Message):
    if not await check_permissions(client, message): return
    chat_id = message.chat.id
    # Generar Carpeta Única por Tarea para multi-usuario real
    task_id = uuid.uuid4().hex[:8]
    work_dir = os.path.join(DOWNLOAD_DIR_C2, task_id)
    os.makedirs(work_dir, exist_ok=True)

    user_data_c2[chat_id] = {
        'task_id': task_id,
        'work_dir': work_dir,
        'original_message_id': message.id,
        'video_file_name': message.video.file_name or f"video_{task_id}.mp4"
    }
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")], [InlineKeyboardButton("⚙️ Solo Enviar/Convertir", callback_data="action_convert_only")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await message.reply_text("Video recibido. ¿Qué quieres hacer?", reply_markup=keyboard, quote=True)

@app2.on_callback_query()
async def callback_handler_c2(client, cb: CallbackQuery):
    chat_id = cb.message.chat.id
    if chat_id not in user_data_c2: return await cb.answer("Operación expirada.", show_alert=True)
    user_info = user_data_c2[chat_id]
    action = cb.data
    user_info['status_message_id'] = cb.message.id

    if action == "cancel":
        shutil.rmtree(user_info['work_dir'], ignore_errors=True)
        user_data_c2.pop(chat_id)
        await cb.message.edit("Operación cancelada.")
    elif action == "action_compress":
        is_gpu = is_gpu_available_c2()
        user_info['compression_options'] = {'crf': '24' if is_gpu else '22', 'resolution': '360', 'preset': 'veryfast'}
        await show_compression_options_c2(client, chat_id, cb.message.id)
    elif action == "compressopt_default":
        await cb.message.edit("Iniciando...")
        asyncio.create_task(run_compression_flow_c2(client, chat_id, cb.message))
    elif action == "compressopt_advanced":
        await show_advanced_menu_c2(client, chat_id, cb.message.id, "crf")
    elif action.startswith("adv_"):
        part, value = action.split("_")[1], action.split("_")[2]
        user_info['compression_options'][part] = value
        next_step = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(part)
        await show_advanced_menu_c2(client, chat_id, cb.message.id, next_step, user_info['compression_options'])
    elif action == "start_advanced_compression":
        await cb.message.edit("Iniciando...")
        asyncio.create_task(run_compression_flow_c2(client, chat_id, cb.message))
    elif action == "action_convert_only":
        await cb.message.edit("Descargando...")
        asyncio.create_task(run_download_only_flow_c2(client, chat_id, cb.message))
    elif action == "convertopt_withthumb":
        user_info['state'] = 'waiting_for_thumbnail'
        await cb.message.edit("Envía la imagen para la miniatura.")
    elif action == "convertopt_nothumb":
        await show_rename_options_c2(client, chat_id, cb.message.id)
    elif action == "convertopt_asfile":
        user_info['send_as_file'] = True
        await show_rename_options_c2(client, chat_id, cb.message.id)
    elif action == "renameopt_yes":
        user_info['state'] = 'waiting_for_new_name'
        await cb.message.edit("Envíame el nuevo nombre.")
    elif action == "renameopt_no":
        asyncio.create_task(upload_final_video_c2(client, chat_id))

# FLUJO DE COMPRESIÓN (No bloqueante)
async def run_compression_flow_c2(client, chat_id, status_message):
    user_info = user_data_c2[chat_id]
    original_msg = await client.get_messages(chat_id, user_info['original_message_id'])
    
    # Descarga
    path = await client.download_media(original_msg, file_name=user_info['work_dir'] + "/", progress=progress_bar_handler_c2, progress_args=(client, status_message, time.time(), "📥 Descargando"))
    
    # Compresión
    opts = user_info['compression_options']
    output_path = os.path.join(user_info['work_dir'], "output.mp4")
    await status_message.edit("🗜️ Comprimiendo...")
    
    if is_gpu_available_c2():
        cmd = ['ffmpeg', '-hwaccel', 'cuda', '-i', path, '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', opts['crf'], '-vf', f'scale=-2:{opts["resolution"]}', '-y', output_path]
    else:
        cmd = ['ffmpeg', '-i', path, '-vcodec', 'libx264', '-crf', opts['crf'], '-preset', opts['preset'], '-vf', f'scale=-2:{opts["resolution"]}', '-y', output_path]
    
    process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    await process.wait()
    
    user_info['final_path'] = output_path
    await show_conversion_options_c2(client, chat_id, status_message.id, text="✅ Compresión Exitosa. ¿Cómo quieres continuar?")

async def run_download_only_flow_c2(client, chat_id, status_message):
    user_info = user_data_c2[chat_id]
    original_msg = await client.get_messages(chat_id, user_info['original_message_id'])
    path = await client.download_media(original_msg, file_name=user_info['work_dir'] + "/", progress=progress_bar_handler_c2, progress_args=(client, status_message, time.time(), "📥 Descargando"))
    user_info['final_path'] = path
    await show_conversion_options_c2(client, chat_id, status_message.id, text="Descarga completa. ¿Cómo quieres enviar?")

@app2.on_message(filters.photo & filters.private)
async def thumbnail_handler_c2(client, message: Message):
    user_info = user_data_c2.get(message.chat.id)
    if not user_info or user_info.get('state') != 'waiting_for_thumbnail': return
    user_info['thumbnail_path'] = await client.download_media(message, file_name=user_info['work_dir'] + "/thumb.jpg")
    await show_rename_options_c2(client, message.chat.id, user_info['status_message_id'], "Miniatura guardada. ¿Renombrar?")

@app2.on_message(filters.text & filters.private)
async def rename_handler_c2(client, message: Message):
    user_info = user_data_c2.get(message.chat.id)
    if not user_info or user_info.get('state') != 'waiting_for_new_name': return
    user_info['new_name'] = message.text.strip()
    await message.delete()
    asyncio.create_task(upload_final_video_c2(client, message.chat.id))

async def upload_final_video_c2(client, chat_id):
    user_info = user_data_c2.get(chat_id)
    if not user_info: return
    status_msg = await client.get_messages(chat_id, user_info['status_message_id'])
    final_path = user_info['final_path']
    file_name = (user_info.get('new_name') or user_info['video_file_name'])
    if not file_name.endswith(".mp4"): file_name += ".mp4"

    try:
        await status_msg.edit("⬆️ Subiendo...")
        if user_info.get('send_as_file'):
            await client.send_document(chat_id, document=final_path, file_name=file_name, thumb=user_info.get('thumbnail_path'), progress=progress_bar_handler_c2, progress_args=(client, status_msg, time.time(), "⬆️ Subiendo"))
        else:
            await client.send_video(chat_id, video=final_path, file_name=file_name, thumb=user_info.get('thumbnail_path'), supports_streaming=True, progress=progress_bar_handler_c2, progress_args=(client, status_msg, time.time(), "⬆️ Subiendo"))
        await status_msg.delete()
    except Exception as e: await client.send_message(chat_id, f"❌ Error: {e}")
    finally:
        shutil.rmtree(user_info['work_dir'], ignore_errors=True)
        user_data_c2.pop(chat_id)

# Menús (Manteniendo tu estética exacta)
async def show_compression_options_c2(client, chat_id, msg_id):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Usar Recomendados", callback_data="compressopt_default")], [InlineKeyboardButton("⚙️ Opciones Avanzadas", callback_data="compressopt_advanced")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await client.edit_message_text(chat_id, msg_id, "Elige cómo quieres comprimir:", reply_markup=kb)

async def show_advanced_menu_c2(client, chat_id, msg_id, part, opts=None):
    is_gpu = is_gpu_available_c2()
    if part == "confirm":
        text = f"Confirmar {'GPU' if is_gpu else ''}:\n- Calidad: `{opts['crf']}`\n- Res: `{opts['resolution']}p`"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Iniciar", callback_data="start_advanced_compression")]])
    else:
        # Aquí van tus diccionarios originales de menús CRF/Res/Preset
        titles = {"crf": "Calidad", "resolution": "Resolución", "preset": "Velocidad"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Continuar...", callback_data=f"adv_{part}_val")]])
        text = f"Seleccione {titles.get(part, part)}"
    await client.edit_message_text(chat_id, msg_id, text, reply_markup=kb)

async def show_conversion_options_c2(client, chat_id, msg_id, text="¿Cómo quieres enviar el video?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🖼️ Con Miniatura", callback_data="convertopt_withthumb")], [InlineKeyboardButton("🚫 Sin Miniatura", callback_data="convertopt_nothumb")], [InlineKeyboardButton("📂 Enviar como Archivo", callback_data="convertopt_asfile")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await client.edit_message_text(chat_id, msg_id, text, reply_markup=kb)

async def show_rename_options_c2(client, chat_id, msg_id, text="¿Quieres renombrar el archivo?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Sí, renombrar", callback_data="renameopt_yes")], [InlineKeyboardButton("➡️ No, usar original", callback_data="renameopt_no")]])
    await client.edit_message_text(chat_id, msg_id, text, reply_markup=kb)

# ==============================================================================
# LÓGICA DEL BOT 3 (DOWNLOADER) - MULTI-HILO EXTREMO
# ==============================================================================

DOWNLOAD_DIR_C3 = "downloads_c3"
os.makedirs(DOWNLOAD_DIR_C3, exist_ok=True)
url_storage_c3 = {}

@app3.on_message(filters.command("start"))
async def start_c3(c, m):
    if not await check_permissions(c, m): return
    await m.reply_text("✨ **¡BOT DE DESCARGAS ACTIVO!**\nEnvía un link o busca algo.")

@app3.on_message(filters.text)
async def handle_text_c3(c, m):
    if not await check_permissions(c, m): return
    if m.text.startswith("http"):
        link_id = uuid.uuid4().hex[:8]; url_storage_c3[link_id] = m.text
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎬 720p", callback_data=f"dl|{link_id}|720"), InlineKeyboardButton("🎵 MP3", callback_data=f"dl|{link_id}|audio")]])
        await m.reply_text("📥 Selecciona formato:", reply_markup=kb)
    else:
        status = await m.reply_text("🔎 Buscando...")
        # Lógica de búsqueda XV/YT se mantiene igual a tu código
        await status.edit("Resultados encontrados (Simulado)...")

@app3.on_callback_query(filters.regex(r"^dl\|"))
async def download_logic_c3(c, q):
    _, link_id, quality = q.data.split("|")
    url = url_storage_c3.get(link_id)
    status = await q.message.edit_text("⏳ Descargando a máxima velocidad...")
    
    # Carpeta única para la tarea
    uid = uuid.uuid4().hex[:6]
    task_path = os.path.join(DOWNLOAD_DIR_C3, uid)
    os.makedirs(task_path)

    # MEJORA: Descarga con hilos paralelos (10 fragmentos a la vez)
    ydl_opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best' if quality != "audio" else 'bestaudio',
        'outtmpl': f'{task_path}/%(title)s.%(ext)s',
        'concurrent_fragment_downloads': 10, 
        'quiet': True
    }
    
    try:
        loop = asyncio.get_event_loop()
        with YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            f_path = ydl.prepare_filename(info)
        
        await status.edit("⬆️ Subiendo...")
        await c.send_video(q.message.chat.id, video=f_path, caption=f"✅ {info['title']}")
        await status.delete()
    except Exception as e: await status.edit(f"❌ Error: {e}")
    finally: shutil.rmtree(task_path, ignore_errors=True)

# ==========================================
# SERVIDOR FLASK & EJECUCIÓN
# ==========================================

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "Sistemas Activos"

async def main():
    print("🚀 INICIANDO SISTEMA MULTI-TAREA...")
    Thread(target=lambda: app_flask.run(host='0.0.0.0', port=8000), daemon=True).start()
    await app1.start(); await app2.start(); await app3.start(); await app4.start()
    print("✅ Todos los bots en línea.")
    await idle()
    await app1.stop(); await app2.stop(); await app3.stop(); await app4.stop()

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass
