# =======================================================
# IMPORTACIONES
# =======================================================
import os
import ffmpeg
import psutil
import time
import re
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified, FloodWait
import nest_asyncio

# Importaciones para el servidor web de Render/Koyeb
from threading import Thread
from flask import Flask

# =======================================================
# CÓDIGO PARA EL SERVIDOR WEB (NO TOCAR)
# =======================================================
app_flask = Flask(__name__)

@app_flask.route('/')
def hello_world():
    return 'Bot is alive!'

def run_server():
    port = int(os.environ.get('PORT', 8000))
    app_flask.run(host='0.0.0.0', port=port)

# =======================================================
# LÓGICA DE TU BOT
# =======================================================

nest_asyncio.apply()

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_VIDEO_SIZE_MB = 4000
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Diccionario para persistencia de configuración por usuario
user_settings = {} 
# Diccionario para datos temporales del proceso actual
user_process = {}

app = Client("video_processor_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Funciones de Utilidad ---
def format_size(size_bytes):
    if size_bytes is None: return "0 B"
    if size_bytes < 1024: return f"{size_bytes} Bytes"
    if size_bytes < 1024**2: return f"{size_bytes/1024:.2f} KB"
    if size_bytes < 1024**3: return f"{size_bytes/1024**2:.2f} MB"
    return f"{size_bytes/1024**3:.2f} GB"

def human_readable_time(seconds: int) -> str:
    if seconds is None: return "00:00"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

async def update_message(client, chat_id, message_id, text, reply_markup=None):
    try:
        await client.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup)
    except MessageNotModified:
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await update_message(client, chat_id, message_id, text, reply_markup)
    except Exception as e:
        logger.error(f"Error al actualizar mensaje: {e}")

def get_progress_bar(percentage):
    completed_blocks = int(percentage // 10)
    if percentage >= 100: return '■' * 10
    return '■' * completed_blocks + '□' * (10 - completed_blocks)

async def progress_bar_handler(current, total, client, message, start_time, action_text):
    chat_id = message.chat.id
    last_update_time = user_process.get(chat_id, {}).get('last_update_time', 0)
    current_time = time.time()
    if current_time - last_update_time < 5: return
    user_process.setdefault(chat_id, {})['last_update_time'] = current_time
    percentage = (current * 100 / total) if total > 0 else 0
    elapsed_time = current_time - start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0
    progress_bar = get_progress_bar(percentage)
    text = (f"**{action_text}**\n"
            f"`[{progress_bar}] {percentage:.1f}%`\n\n"
            f"**Tamaño:** `{format_size(current)} / {format_size(total)}`\n"
            f"**Velocidad:** `{format_size(speed)}/s` | **ETA:** `{human_readable_time(eta)}`")
    await update_message(client, chat_id, message.id, text)

# --- Procesamiento ---

async def download_video(client, chat_id, status_message):
    process_info = user_process.get(chat_id)
    if not process_info: return None
    start_time = time.time()
    original_message = await client.get_messages(chat_id, process_info['original_message_id'])
    try:
        video_path = await client.download_media(
            message=original_message,
            file_name=os.path.join(DOWNLOAD_DIR, f"{chat_id}_{process_info['video_file_name']}"),
            progress=progress_bar_handler,
            progress_args=(client, status_message, start_time, "DESCARGANDO...")
        )
        process_info['download_path'] = video_path
        process_info['final_path'] = video_path
        return video_path
    except Exception as e:
        logger.error(f"Error descarga: {e}")
        return None

async def run_compression_flow(client, chat_id, status_message):
    downloaded_path = None
    try:
        downloaded_path = await download_video(client, chat_id, status_message)
        if not downloaded_path: return
        process_info = user_process[chat_id]
        opts = process_info['compression_options']
        output_path = os.path.join(DOWNLOAD_DIR, f"compressed_{chat_id}.mp4")
        probe = ffmpeg.probe(downloaded_path)
        duration = float(probe.get('format', {}).get('duration', 0))
        original_size = os.path.getsize(downloaded_path)

        use_gpu = user_settings.get(chat_id, {}).get('use_gpu', True)
        if use_gpu:
            modo_label = "GPU"
            preset_map = {'ultrafast': 'p1', 'veryfast': 'p2', 'fast': 'p3', 'medium': 'p4', 'slow': 'p6'}
            cmd = ['ffmpeg', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-i', downloaded_path,
                   '-vf', f"scale_cuda=-2:{opts['resolution']}", '-c:v', 'h264_nvenc', '-preset', preset_map.get(opts['preset'], 'p4'),
                   '-rc', 'vbr', '-cq', opts['crf'], '-b:v', '0', '-acodec', 'aac', '-b:a', '64k', '-movflags', '+faststart',
                   '-progress', 'pipe:1', '-nostats', '-y', output_path]
        else:
            modo_label = "CPU"
            # AJUSTE: Ahora CPU usa los mismos parámetros de 'opts' que GPU para mostrar detalles idénticos
            cmd = ['ffmpeg', '-i', downloaded_path, 
                   '-vf', f"scale=-2:{opts['resolution']}", 
                   '-c:v', 'libx264', '-preset', opts['preset'],
                   '-crf', opts['crf'], '-acodec', 'aac', '-b:a', '64k', '-movflags', '+faststart',
                   '-progress', 'pipe:1', '-nostats', '-y', output_path]

        await update_message(client, chat_id, status_message.id, f"COMPRIMIENDO ({modo_label})...")
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        success = await track_ffmpeg_progress(client, chat_id, status_message.id, process, duration, original_size, output_path, modo_label)

        if success:
            process_info['final_path'] = output_path
            # Borrar original tras comprimir para ahorrar espacio
            if os.path.exists(downloaded_path): os.remove(downloaded_path)
            
            compressed_size = os.path.getsize(output_path)
            reduction = ((original_size - compressed_size) / original_size) * 100
            summary = (f"✅ **Compresión Exitosa ({modo_label})**\n\n"
                       f"**📏 Original:** `{format_size(original_size)}`\n"
                       f"**📂 Comprimido:** `{format_size(compressed_size)}` (`{reduction:.1f}%` menos)")
            await show_conversion_options(client, chat_id, status_message.id, text=summary)
    except Exception as e:
        logger.error(f"Error compresión: {e}")
    finally:
        if downloaded_path and os.path.exists(downloaded_path): os.remove(downloaded_path)

async def track_ffmpeg_progress(client, chat_id, msg_id, process, duration, original_size, output_path, label):
    last_update = 0
    ffmpeg_data = {}
    while True:
        line = await process.stdout.readline()
        if not line: break
        line = line.decode('utf-8').strip()
        match = re.match(r'(\w+)=(.*)', line)
        if match:
            key, value = match.groups()
            ffmpeg_data[key] = value
        if 'progress' in ffmpeg_data and ffmpeg_data['progress'] == 'continue':
            cur_us = int(ffmpeg_data.get('out_time_us', 0))
            if time.time() - last_update < 4: continue
            last_update = time.time()
            perc = min((cur_us / 1_000_000 / duration) * 100, 100) if duration > 0 else 0
            text = (f"**COMPRIMIENDO ({label})...**\n"
                    f"`[{get_progress_bar(perc)}] {perc:.1f}%`\n\n"
                    f"**Tamaño:** `{format_size(os.path.getsize(output_path)) if os.path.exists(output_path) else '0'} / {format_size(original_size)}`")
            await update_message(client, chat_id, msg_id, text)
    await process.wait()
    return process.returncode == 0

async def upload_final_video(client, chat_id):
    p_info = user_process.get(chat_id)
    final_path = p_info['final_path']
    status_id = p_info['status_message_id']
    status_message = await client.get_messages(chat_id, status_id)
    final_filename = p_info.get('new_name') or os.path.basename(p_info['video_file_name'])
    if not final_filename.endswith(".mp4"): final_filename += ".mp4"
    try:
        await update_message(client, chat_id, status_id, "SUBIENDO...")
        if p_info.get('send_as_file'):
            await client.send_document(chat_id, final_path, thumb=p_info.get('thumbnail_path'), file_name=final_filename, progress=progress_bar_handler, progress_args=(client, status_message, time.time(), "SUBIENDO..."))
        else:
            await client.send_video(chat_id, final_path, thumb=p_info.get('thumbnail_path'), caption=f"`{final_filename}`", supports_streaming=True, progress=progress_bar_handler, progress_args=(client, status_message, time.time(), "SUBIENDO..."))
        await status_message.delete()
    except Exception as e: logger.error(f"Error subida: {e}")
    finally: clean_up_process(chat_id)

# --- Handlers ---

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    clean_up_process(message.chat.id)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Usar GPU (Kaggle)", callback_data="hw_gpu")],
                                     [InlineKeyboardButton("🍃 Usar CPU (Gratis)", callback_data="hw_cpu")]])
    await message.reply("Hardware de compresión seleccionado. Esta opción se guardará para siempre hasta que vuelvas a usar /start:", reply_markup=keyboard)

@app.on_message(filters.video & filters.private)
async def video_handler(client, message: Message):
    chat_id = message.chat.id
    if chat_id not in user_settings:
        await message.reply("⚠️ No has configurado el hardware. Usa /start primero.")
        return
    
    user_process[chat_id] = {
        'original_message_id': message.id, 
        'video_file_name': message.video.file_name or "video.mp4", 
        'last_update_time': 0
    }
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")],
                                     [InlineKeyboardButton("⚙️ Solo Enviar/Convertir", callback_data="action_convert_only")],
                                     [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await message.reply_text("¿Qué quieres hacer con este video?", reply_markup=keyboard, quote=True)

@app.on_message(filters.photo & filters.private)
async def thumb_handler(client, message):
    chat_id = message.chat.id
    p_info = user_process.get(chat_id)
    if not p_info or p_info.get('state') != 'waiting_thumb': return
    p_info['thumbnail_path'] = await client.download_media(message, file_name=f"{DOWNLOAD_DIR}/thumb_{chat_id}.jpg")
    await show_rename_options(client, chat_id, p_info['status_message_id'])

@app.on_message(filters.text & filters.private)
async def name_handler(client, message):
    chat_id = message.chat.id
    p_info = user_process.get(chat_id)
    if not p_info or p_info.get('state') != 'waiting_name': return
    p_info['new_name'] = message.text
    await message.delete()
    await upload_final_video(client, chat_id)

@app.on_callback_query()
async def callback_handler(client, cb: CallbackQuery):
    chat_id = cb.message.chat.id
    data = cb.data
    
    if data.startswith("hw_"):
        user_settings[chat_id] = {'use_gpu': (data == "hw_gpu")}
        await cb.message.edit(f"✅ Modo **{'GPU 🚀' if data == 'hw_gpu' else 'CPU 🍃'}** guardado permanentemente. Ya puedes enviarme videos.")
        return
    
    p_info = user_process.get(chat_id)
    if not p_info: return
    p_info['status_message_id'] = cb.message.id
    await cb.answer()

    if data == "action_compress":
        # Ahora tanto GPU como CPU pasan por el menú de opciones para tener la configuración lista
        await show_compression_options(client, chat_id, cb.message.id)
    elif data == "compressopt_default":
        p_info['compression_options'] = {'crf': '24', 'resolution': '360', 'preset': 'veryfast'}
        await run_compression_flow(client, chat_id, cb.message)
    elif data == "compressopt_advanced": await show_advanced_menu(client, chat_id, cb.message.id, "crf")
    elif data.startswith("adv_"):
        part, val = data.split("_")[1], data.split("_")[2]
        p_info.setdefault('compression_options', {})[part] = val
        next_part = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(part)
        if next_part: await show_advanced_menu(client, chat_id, cb.message.id, next_part, p_info['compression_options'])
    elif data == "start_advanced_compression": await run_compression_flow(client, chat_id, cb.message)
    elif data == "action_convert_only":
        await download_video(client, chat_id, cb.message)
        await show_conversion_options(client, chat_id, cb.message.id)
    elif data == "convertopt_withthumb": p_info['state'] = 'waiting_thumb'; await cb.message.edit("Envía la imagen para la miniatura.")
    elif data == "convertopt_nothumb": await show_rename_options(client, chat_id, cb.message.id)
    elif data == "convertopt_asfile": p_info['send_as_file'] = True; await show_rename_options(client, chat_id, cb.message.id)
    elif data == "renameopt_yes": p_info['state'] = 'waiting_name'; await cb.message.edit("Envía el nuevo nombre.")
    elif data == "renameopt_no": await upload_final_video(client, chat_id)
    elif data == "cancel": clean_up_process(chat_id); await cb.message.edit("Cancelado.")

# --- Menús ---
async def show_compression_options(client, chat_id, msg_id):
    # Texto adaptado según el hardware seleccionado
    hw_label = "GPU" if user_settings[chat_id].get('use_gpu') else "CPU"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ {hw_label} Default", callback_data="compressopt_default")],
                                     [InlineKeyboardButton(f"⚙️ {hw_label} Avanzada", callback_data="compressopt_advanced")],
                                     [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await update_message(client, chat_id, msg_id, f"Opciones de hardware {hw_label}:", reply_markup=keyboard)

async def show_advanced_menu(client, chat_id, msg_id, part, opts=None):
    hw_label = "GPU (CQ)" if user_settings[chat_id].get('use_gpu') else "CPU (CRF)"
    menus = {
        "crf": {"text": f"Calidad {hw_label}", "opts": [("Alta", "20"), ("Media", "24"), ("Económica", "28"), ("Baja", "32")], "prefix": "adv_crf"},
        "resolution": {"text": "Resolución", "opts": [("1080p", "1080"), ("720p", "720"), ("480p", "480"), ("360p", "360"), ("240p", "240")], "prefix": "adv_resolution"},
        "preset": {"text": f"Velocidad {hw_label.split()[0]}", "opts": [("Máxima", "ultrafast"), ("Equilibrada", "medium"), ("Calidad", "slow")], "prefix": "adv_preset"}
    }
    if part == "confirm":
        text = f"Confirmar {hw_label.split()[0]}: Calidad {opts.get('crf')} | {opts.get('resolution')}p | {opts.get('preset')}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Iniciar", callback_data="start_advanced_compression")]])
    else:
        info = menus[part]
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=f"{info['prefix']}_{v}") for t, v in info["opts"]]])
        text = info["text"]
    await update_message(client, chat_id, msg_id, text, reply_markup=keyboard)

async def show_conversion_options(client, chat_id, msg_id, text="¿Cómo quieres enviar?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🖼️ Con Miniatura", callback_data="convertopt_withthumb")],
                                [InlineKeyboardButton("🚫 Sin Miniatura", callback_data="convertopt_nothumb")],
                                [InlineKeyboardButton("📂 Enviar como Archivo", callback_data="convertopt_asfile")]])
    await update_message(client, chat_id, msg_id, text, reply_markup=kb)

async def show_rename_options(client, chat_id, msg_id):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Renombrar", callback_data="renameopt_yes")],
                                [InlineKeyboardButton("➡️ Usar original", callback_data="renameopt_no")]])
    await update_message(client, chat_id, msg_id, "¿Quieres renombrar el video?", reply_markup=kb)

def clean_up_process(chat_id):
    info = user_process.pop(chat_id, None)
    if info:
        for k in ['download_path', 'final_path', 'thumbnail_path']:
            if info.get(k) and os.path.exists(info[k]):
                try: os.remove(info[k])
                except: pass

async def start_bot_and_server():
    Thread(target=run_server).start()
    await app.start()
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(start_bot_and_server())
