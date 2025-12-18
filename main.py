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

# Importaciones para el servidor web
from threading import Thread
from flask import Flask

# =======================================================
# CÓDIGO PARA EL SERVIDOR WEB
# =======================================================
app_flask = Flask(__name__)

@app_flask.route('/')
def hello_world():
    return 'Bot is alive!'

def run_server():
    # Koyeb usa la variable PORT dinámicamente
    port = int(os.environ.get('PORT', 8000))
    app_flask.run(host='0.0.0.0', port=port)

# =======================================================
# LÓGICA DE TU BOT (ESTRUCTURA ORIGINAL)
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
    if percentage >= 100: return '■' * 10
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
        f"`[{progress_bar}] {percentage:.1f}%`\n\n"
        f"**Tamaño:** `{format_size(current)} / {format_size(total)}`\n"
        f"**Velocidad:** `{format_size(speed)}/s` | **ETA:** `{human_readable_time(eta)}`"
    )
    await update_message(client, chat_id, message.id, text)

# --- Lógica de Procesamiento ---

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
        logger.error(f"Error descarga: {e}")
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

        if not success:
            await update_message(client, chat_id, status_message.id, "❌ Error de compresión.")
            return

        user_info['final_path'] = output_path
        compressed_size = os.path.getsize(output_path)
        reduction = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
        summary = (f"✅ **Compresión Exitosa**\n\n"
                    f"**📏 Original:** `{format_size(original_size)}`\n"
                    f"**📂 Comprimido:** `{format_size(compressed_size)}` (`{reduction:.1f}%` ahorro)\n\n"
                    f"¿Cómo quieres continuar?")
        await show_conversion_options(client, chat_id, status_message.id, text=summary)

    except Exception as e:
        logger.error(f"Error compresión: {e}")
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

        if ffmpeg_data.get('progress') == 'continue':
            # --- CORRECCIÓN DEL ERROR N/A ---
            raw_time = ffmpeg_data.get('out_time_us', '0')
            cur_us = int(raw_time) if str(raw_time).isdigit() else 0
            # --------------------------------
            if cur_us == 0 or time.time() - last_update < 2: continue
            last_update = time.time()

            cur_sec = cur_us / 1_000_000
            perc = min((cur_sec / duration) * 100, 100) if duration > 0 else 0
            speed_str = ffmpeg_data.get('speed', '0x').replace('x', '')
            try: s_mult = float(speed_str)
            except: s_mult = 0
            
            eta = (duration - cur_sec) / s_mult if s_mult > 0 else 0
            progress_bar = get_progress_bar(perc)
            cur_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            text = (f"**🗜️ COMPRIMIENDO...**\n`[{progress_bar}] {perc:.1f}%`\n\n"
                    f"**Tamaño:** `{format_size(cur_size)} / {format_size(original_size)}`\n"
                    f"**Velocidad:** `{s_mult:.2f}x` | **ETA:** `{human_readable_time(eta)}`")
            await update_message(client, chat_id, msg_id, text)
            ffmpeg_data.clear()
    await process.wait()
    return process.returncode == 0

async def upload_final_video(client, chat_id):
    user_info = user_data.get(chat_id)
    if not user_info or not user_info.get('final_path'): return
    final_path = user_info['final_path']
    status_id = user_info['status_message_id']
    status_message = await client.get_messages(chat_id, status_id)

    try:
        probe = ffmpeg.probe(final_path)
        stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), {})
        w, h = int(stream.get('width', 0)), int(stream.get('height', 0))
        dur = int(float(stream.get('duration', 0)))
        
        await update_message(client, chat_id, status_id, "⬆️ SUBIENDO...")
        if user_info.get('send_as_file'):
            await client.send_document(chat_id, final_path, file_name=user_info.get('new_name') or "video.mp4",
                                      progress=progress_bar_handler, progress_args=(client, status_message, time.time(), "⬆️ Subiendo"))
        else:
            await client.send_video(chat_id, final_path, supports_streaming=True, width=w, height=h, duration=dur,
                                   thumb=user_info.get('thumbnail_path'),
                                   progress=progress_bar_handler, progress_args=(client, status_message, time.time(), "⬆️ Subiendo"))
        await status_message.delete()
    except Exception as e: logger.error(e)
    finally: clean_up(chat_id)

# --- Handlers Originales ---

@app.on_message(filters.command("start") & filters.private)
async def start_command(c, m):
    clean_up(m.chat.id)
    await m.reply("¡Hola! Envíame un video para empezar.")

@app.on_message(filters.video & filters.private)
async def video_handler(c, m):
    chat_id = m.chat.id
    user_data[chat_id] = {'original_message_id': m.id, 'video_file_name': m.video.file_name or "video.mp4"}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")],
        [InlineKeyboardButton("⚙️ Solo Enviar/Convertir", callback_data="action_convert_only")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
    ])
    await m.reply_text("Video recibido. ¿Qué quieres hacer?", reply_markup=kb, quote=True)

@app.on_message(filters.photo & filters.private)
async def thumbnail_handler(c, m):
    user_info = user_data.get(m.chat.id)
    if user_info and user_info.get('state') == 'waiting_for_thumbnail':
        path = await c.download_media(m, file_name=os.path.join(DOWNLOAD_DIR, f"thumb_{m.chat.id}.jpg"))
        user_info['thumbnail_path'] = path
        await show_rename_options(c, m.chat.id, user_info['status_message_id'], "Miniatura guardada. ¿Renombrar?")

@app.on_message(filters.text & filters.private)
async def rename_handler(c, m):
    user_info = user_data.get(m.chat.id)
    if user_info and user_info.get('state') == 'waiting_for_new_name':
        user_info['new_name'] = m.text.strip()
        await m.delete()
        await upload_final_video(c, m.chat.id)

@app.on_callback_query()
async def callback_handler(client, cb: CallbackQuery):
    chat_id = cb.message.chat.id
    user_info = user_data.get(chat_id)
    if not user_info: return
    user_info['status_message_id'] = cb.message.id
    data = cb.data
    await cb.answer()

    if data == "cancel": clean_up(chat_id); await cb.message.edit("Cancelado.")
    elif data == "action_compress": await show_compression_options(client, chat_id, cb.message.id)
    elif data == "compressopt_default":
        user_info['compression_options'] = {'crf': '24', 'resolution': '480', 'preset': 'ultrafast'}
        await run_compression_flow(client, chat_id, cb.message)
    elif data == "compressopt_advanced": await show_advanced_menu(client, chat_id, cb.message.id, "crf")
    elif data.startswith("adv_"):
        p, v = data.split("_")[1], data.split("_")[2]
        user_info.setdefault('compression_options', {})[p] = v
        nxt = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(p)
        await show_advanced_menu(client, chat_id, cb.message.id, nxt, user_info['compression_options'])
    elif data == "start_advanced_compression": await run_compression_flow(client, chat_id, cb.message)
    elif data == "action_convert_only": 
        user_info['final_path'] = await download_video(client, chat_id, cb.message)
        await show_conversion_options(client, chat_id, cb.message.id)
    elif data == "convertopt_withthumb": user_info['state'] = 'waiting_for_thumbnail'; await cb.message.edit("Envía la foto.")
    elif data == "convertopt_nothumb": await show_rename_options(client, chat_id, cb.message.id)
    elif data == "renameopt_yes": user_info['state'] = 'waiting_for_new_name'; await cb.message.edit("Envía el nombre.")
    elif data == "renameopt_no": await upload_final_video(client, chat_id)

# --- Menús Originales ---
async def show_compression_options(c, cid, mid):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Recomendado", callback_data="compressopt_default")],
        [InlineKeyboardButton("⚙️ Avanzado", callback_data="compressopt_advanced")]
    ])
    await update_message(c, cid, mid, "Opciones de compresión:", reply_markup=kb)

async def show_advanced_menu(c, cid, mid, part, opts=None):
    if part == "confirm":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Iniciar", callback_data="start_advanced_compression")]])
        text = f"Confirmar: CRF {opts['crf']}, Res {opts['resolution']}p, Preset {opts['preset']}"
    else:
        menus = {
            "crf": [("18", "18"), ("22", "22"), ("28", "28")],
            "resolution": [("360p", "360"), ("480p", "480"), ("720p", "720")],
            "preset": [("Ultra", "ultrafast"), ("Fast", "fast"), ("Medium", "medium")]
        }
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(tx, callback_data=f"adv_{part}_{v}") for tx, v in menus[part]]])
        text = f"Selecciona {part}:"
    await update_message(c, cid, mid, text, reply_markup=kb)

async def show_conversion_options(c, cid, mid, text="¿Opciones de envío?"):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Con Miniatura", callback_data="convertopt_withthumb")],
        [InlineKeyboardButton("🚫 Sin Miniatura", callback_data="convertopt_nothumb")]
    ])
    await update_message(c, cid, mid, text, reply_markup=kb)

async def show_rename_options(c, cid, mid, text="¿Renombrar?"):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Sí", callback_data="renameopt_yes"), InlineKeyboardButton("No", callback_data="renameopt_no")]])
    await update_message(c, cid, mid, text, reply_markup=kb)

def clean_up(chat_id):
    info = user_data.pop(chat_id, None)
    if info:
        for k in ['download_path', 'thumbnail_path', 'final_path']:
            if info.get(k) and os.path.exists(info[k]): os.remove(info[k])

if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    app.run()
