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
    # Koyeb usa la variable PORT, si no existe usamos 8000
    port = int(os.environ.get('PORT', 8000))
    app_flask.run(host='0.0.0.0', port=port)

# =======================================================
# LÓGICA DE TU BOT
# =======================================================

nest_asyncio.apply()

# --- Configuración del Bot ---
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Constantes y Directorios ---
MAX_VIDEO_SIZE_MB = 4000
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

user_data = {}

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
    if percentage >= 100:
        return '■' * 10
    return '■' * completed_blocks + '□' * (10 - completed_blocks)

async def progress_bar_handler(current, total, client, message, start_time, action_text):
    chat_id = message.chat.id
    user_info = user_data.get(chat_id, {})
    last_update_time = user_info.get('last_update_time', 0)
    current_time = time.time()

    if current_time - last_update_time < 5:
        return
    user_info['last_update_time'] = current_time

    percentage = (current * 100 / total) if total > 0 else 0
    elapsed_time = current_time - start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    progress_bar = get_progress_bar(percentage)
    action_text_clean = action_text.replace('📥 Descargando', 'DESCARGANDO...').replace('⬆️ Subiendo', 'SUBIENDO...')

    text = (
        f"**{action_text_clean}**\n"
        f"`[{progress_bar}] {percentage:.1f}%`\n"
        f"\n"
        f"**Tamaño:** `{format_size(current)} / {format_size(total)}`\n"
        f"**Velocidad:** `{format_size(speed)}/s` | **ETA:** `{human_readable_time(eta)}`"
    )
    await update_message(client, chat_id, message.id, text)

# --- Procesamiento ---

async def download_video(client, chat_id, status_message):
    user_info = user_data.get(chat_id)
    if not user_info: return None
    user_info['state'] = 'downloading'
    start_time = time.time()
    original_message = await client.get_messages(chat_id, user_info['original_message_id'])

    try:
        video_path = await client.download_media(
            message=original_message,
            file_name=os.path.join(DOWNLOAD_DIR, f"{chat_id}_{user_info['video_file_name']}"),
            progress=progress_bar_handler,
            progress_args=(client, status_message, start_time, "📥 Descargando")
        )
        user_info['download_path'] = video_path
        return video_path
    except Exception as e:
        logger.error(f"Error al descargar: {e}")
        return None

async def run_compression_flow(client, chat_id, status_message):
    downloaded_path = None
    try:
        downloaded_path = await download_video(client, chat_id, status_message)
        if not downloaded_path: return

        user_info = user_data[chat_id]
        user_info['state'] = 'compressing'
        opts = user_info['compression_options']
        output_path = os.path.join(DOWNLOAD_DIR, f"compressed_{chat_id}.mp4")

        probe = ffmpeg.probe(downloaded_path)
        duration = float(probe.get('format', {}).get('duration', 0))
        original_size = os.path.getsize(downloaded_path)

        cmd = [
            'ffmpeg', '-i', downloaded_path,
            '-vf', f"scale=-2:{opts['resolution']}",
            '-r', '30', '-crf', opts['crf'], '-preset', opts['preset'],
            '-vcodec', 'libx264', '-acodec', 'aac', '-b:a', '64k',
            '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', '-y', output_path
        ]

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        
        success = await track_ffmpeg_progress(client, chat_id, status_message.id, process, duration, original_size, output_path)

        if success:
            user_info['final_path'] = output_path
            compressed_size = os.path.getsize(output_path)
            reduction = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
            summary = (f"✅ **Compresión Exitosa**\n\n"
                        f"**📏 Original:** `{format_size(original_size)}`\n"
                        f"**📂 Comprimido:** `{format_size(compressed_size)}` (`{reduction:.1f}%` menos)")
            await show_conversion_options(client, chat_id, status_message.id, text=summary)
        else:
            await update_message(client, chat_id, status_message.id, "❌ Error en la compresión.")

    except Exception as e:
        logger.error(f"Error en flujo: {e}", exc_info=True)
        await update_message(client, chat_id, status_message.id, "❌ Error inesperado.")
    finally:
        if downloaded_path and os.path.exists(downloaded_path): os.remove(downloaded_path)

async def track_ffmpeg_progress(client, chat_id, msg_id, process, duration, original_size, output_path):
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
            # --- SOLUCIÓN AL ERROR ValueError: N/A ---
            raw_time = ffmpeg_data.get('out_time_us', '0')
            if str(raw_time).isdigit():
                current_time_us = int(raw_time)
            else:
                current_time_us = 0
            # ----------------------------------------

            if current_time_us == 0:
                ffmpeg_data.clear()
                continue

            current_time = time.time()
            if current_time - last_update < 2.0:
                ffmpeg_data.clear()
                continue
            last_update = current_time

            current_time_sec = current_time_us / 1_000_000
            speed_str = ffmpeg_data.get('speed', '0x').replace('x', '')
            try: speed_mult = float(speed_str)
            except: speed_mult = 0

            percentage = min((current_time_sec / duration) * 100, 100) if duration > 0 else 0
            eta = (duration - current_time_sec) / speed_mult if speed_mult > 0 else 0
            progress_bar = get_progress_bar(percentage)
            current_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            text = (
                f"**COMPRIMIENDO...**\n"
                f"`[{progress_bar}] {percentage:.1f}%`\n"
                f"\n"
                f"**Tamaño:** `{format_size(current_size)} / {format_size(original_size)}`\n"
                f"**Velocidad:** `{speed_mult:.2f}x` | **ETA:** `{human_readable_time(eta)}`"
            )
            await update_message(client, chat_id, msg_id, text)
            ffmpeg_data.clear()

    await process.wait()
    return process.returncode == 0

async def upload_final_video(client, chat_id):
    user_info = user_data.get(chat_id)
    if not user_info: return
    final_path = user_info['final_path']
    status_id = user_info['status_message_id']
    status_message = await client.get_messages(chat_id, status_id)

    try:
        start_time = time.time()
        await update_message(client, chat_id, status_id, "⬆️ SUBIENDO...")
        await client.send_video(
            chat_id=chat_id, video=final_path, supports_streaming=True,
            progress=progress_bar_handler, progress_args=(client, status_message, start_time, "⬆️ Subiendo")
        )
        await status_message.delete()
        await client.send_message(chat_id, "✅ ¡Listo!")
    except Exception as e:
        logger.error(f"Error subida: {e}")
    finally:
        clean_up(chat_id)

# --- Handlers ---

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    clean_up(message.chat.id)
    await message.reply("¡Hola! Envíame un video para comprimir.")

@app.on_message(filters.video & filters.private)
async def video_handler(client, message: Message):
    chat_id = message.chat.id
    user_data[chat_id] = {
        'state': 'awaiting_action', 'original_message_id': message.id,
        'video_file_name': message.video.file_name or "video.mp4", 'last_update_time': 0
    }
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir", callback_data="action_compress")]])
    await message.reply_text("¿Quieres comprimir este video?", reply_markup=keyboard, quote=True)

@app.on_callback_query()
async def callback_handler(client, cb: CallbackQuery):
    chat_id = cb.message.chat.id
    user_info = user_data.get(chat_id)
    if not user_info: return
    
    user_info['status_message_id'] = cb.message.id
    if cb.data == "action_compress":
        user_info['compression_options'] = {'crf': '24', 'resolution': '480', 'preset': 'ultrafast'}
        await cb.message.edit("Iniciando proceso...")
        await run_compression_flow(client, chat_id, cb.message)
    elif cb.data == "convertopt_nothumb":
        await upload_final_video(client, chat_id)

async def show_conversion_options(client, chat_id, msg_id, text):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Enviar Ahora", callback_data="convertopt_nothumb")]])
    await update_message(client, chat_id, msg_id, text, reply_markup=keyboard)

def clean_up(chat_id):
    user_info = user_data.pop(chat_id, None)
    if user_info:
        for key in ['download_path', 'final_path']:
            path = user_info.get(key)
            if path and os.path.exists(path): os.remove(path)

async def start_bot_and_server():
    Thread(target=run_server, daemon=True).start()
    await app.start()
    logger.info("Bot y Servidor Web iniciados.")
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(start_bot_and_server())
