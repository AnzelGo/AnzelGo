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

# Importaciones para el servidor web de Render
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
# LÓGICA DEL BOT
# =======================================================

nest_asyncio.apply()

# --- Configuración ---
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_VIDEO_SIZE_MB = 4000
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Diccionario para almacenar el estado, datos y PREFERENCIAS por usuario
user_data = {}

app = Client("video_processor_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Funciones de Utilidad ---
def format_size(size_bytes):
    if size_bytes is None: return "0 B"
    for unit in ['Bytes', 'KB', 'MB', 'GB']:
        if size_bytes < 1024: return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

def human_readable_time(seconds: int) -> str:
    if seconds is None: return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

async def update_message(client, chat_id, message_id, text, reply_markup=None):
    try:
        await client.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup)
    except MessageNotModified: pass
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await update_message(client, chat_id, message_id, text, reply_markup)
    except Exception as e:
        logger.error(f"Error al actualizar mensaje: {e}")

def get_progress_bar(percentage):
    completed = int(percentage // 10)
    return '■' * completed + '□' * (10 - completed)

async def progress_bar_handler(current, total, client, message, start_time, action_text):
    chat_id = message.chat.id
    user_info = user_data.get(chat_id, {})
    last_update = user_info.get('last_update_time', 0)
    now = time.time()

    if now - last_update < 5: return
    user_info['last_update_time'] = now

    percentage = (current * 100 / total) if total > 0 else 0
    elapsed = now - start_time
    speed = current / elapsed if elapsed > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    text = (
        f"**{action_text}**\n"
        f"`[{get_progress_bar(percentage)}] {percentage:.1f}%`\n\n"
        f"**Tamaño:** `{format_size(current)} / {format_size(total)}`\n"
        f"**Velocidad:** `{format_size(speed)}/s` | **ETA:** `{human_readable_time(eta)}`"
    )
    await update_message(client, chat_id, message.id, text)

# --- Lógica de Procesamiento ---

async def download_video(client, chat_id, status_message):
    user_info = user_data.get(chat_id)
    user_info['state'] = 'downloading'
    start_time = time.time()
    
    try:
        original_message = await client.get_messages(chat_id, user_info['original_message_id'])
        video_path = await client.download_media(
            message=original_message,
            file_name=os.path.join(DOWNLOAD_DIR, f"{chat_id}_{user_info['video_file_name']}"),
            progress=progress_bar_handler,
            progress_args=(client, status_message, start_time, "📥 DESCARGANDO...")
        )
        if video_path:
            user_info['download_path'] = video_path
            return video_path
    except Exception as e:
        logger.error(f"Error descarga: {e}")
    return None

async def run_compression_flow(client, chat_id, status_message):
    downloaded_path = await download_video(client, chat_id, status_message)
    if not downloaded_path:
        await update_message(client, chat_id, status_message.id, "❌ Error en la descarga.")
        return

    user_info = user_data[chat_id]
    user_info['state'] = 'compressing'
    opts = user_info.get('compression_options', {'crf': '24', 'resolution': '360', 'preset': 'veryfast'})
    engine = user_info.get('engine', 'CPU')
    output_path = os.path.join(DOWNLOAD_DIR, f"compressed_{chat_id}.mp4")

    try:
        probe = ffmpeg.probe(downloaded_path)
        duration = float(probe.get('format', {}).get('duration', 0))
        original_size = os.path.getsize(downloaded_path)

        # --- Selección de Comando según Engine ---
        if engine == "GPU":
            await update_message(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO (GPU T4)...")
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
        else:
            await update_message(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO (CPU)...")
            cmd = [
                'ffmpeg', '-i', downloaded_path,
                '-vf', f"scale=-2:{opts['resolution']}",
                '-r', '30', '-crf', opts['crf'], '-preset', opts['preset'],
                '-vcodec', 'libx264', '-acodec', 'aac', '-b:a', '64k',
                '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', '-y', output_path
            ]

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        success = await track_ffmpeg_progress(client, chat_id, status_message.id, process, duration, original_size, output_path, engine)

        if success:
            user_info['final_path'] = output_path
            compressed_size = os.path.getsize(output_path)
            reduction = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
            summary = (f"✅ **Compresión Exitosa ({engine})**\n\n"
                        f"**📏 Original:** `{format_size(original_size)}`\n"
                        f"**📂 Comprimido:** `{format_size(compressed_size)}` (`{reduction:.1f}%` menos)\n\n"
                        f"¿Cómo quieres continuar?")
            await show_conversion_options(client, chat_id, status_message.id, text=summary)
        else:
            await update_message(client, chat_id, status_message.id, "❌ Error en el proceso de FFmpeg.")

    except Exception as e:
        logger.error(f"Error: {e}")
        await update_message(client, chat_id, status_message.id, "❌ Error inesperado.")
    finally:
        if downloaded_path and os.path.exists(downloaded_path): os.remove(downloaded_path)

async def track_ffmpeg_progress(client, chat_id, msg_id, process, duration, original_size, output_path, engine):
    last_update = 0
    ffmpeg_data = {}
    while True:
        if user_data.get(chat_id, {}).get('state') == 'cancelled':
            if process.returncode is None: process.terminate()
            return False
        
        line = await process.stdout.readline()
        if not line: break
        
        line = line.decode('utf-8').strip()
        match = re.match(r'(\w+)=(.*)', line)
        if match:
            key, value = match.groups()
            ffmpeg_data[key] = value

        if 'progress' in ffmpeg_data and ffmpeg_data['progress'] == 'continue':
            now = time.time()
            if now - last_update < 3: continue
            last_update = now

            raw_time = ffmpeg_data.get('out_time_us', '0')
            current_time_sec = int(raw_time) / 1_000_000 if raw_time.isdigit() else 0
            speed_str = ffmpeg_data.get('speed', '1x').replace('x', '')
            try: speed_mult = float(speed_str)
            except: speed_mult = 1.0

            percentage = min((current_time_sec / duration) * 100, 100) if duration > 0 else 0
            eta = (duration - current_time_sec) / speed_mult if speed_mult > 0 else 0
            current_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            text = (
                f"**COMPRIMIENDO ({engine})...**\n"
                f"`[{get_progress_bar(percentage)}] {percentage:.1f}%`\n\n"
                f"**Tamaño:** `{format_size(current_size)} / {format_size(original_size)}`\n"
                f"**Velocidad:** `{speed_mult:.2f}x` | **ETA:** `{human_readable_time(eta)}`"
            )
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
    final_filename = user_info.get('new_name') or os.path.basename(user_info['video_file_name'])
    if not final_filename.endswith(".mp4"): final_filename += ".mp4"

    try:
        await update_message(client, chat_id, status_id, "⬆️ SUBIENDO...")
        start_time = time.time()
        
        if user_info.get('send_as_file'):
            await client.send_document(
                chat_id=chat_id, document=final_path, file_name=final_filename,
                progress=progress_bar_handler, progress_args=(client, status_message, start_time, "⬆️ SUBIENDO")
            )
        else:
            # Extraer info para streaming
            probe = ffmpeg.probe(final_path)
            v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            await client.send_video(
                chat_id=chat_id, video=final_path, file_name=final_filename,
                duration=int(float(v.get('duration', 0))), width=int(v.get('width', 0)), height=int(v.get('height', 0)),
                supports_streaming=True, progress=progress_bar_handler, progress_args=(client, status_message, start_time, "⬆️ SUBIENDO")
            )
        await status_message.delete()
        await client.send_message(chat_id, "✅ ¡Proceso completado!")
    except Exception as e:
        logger.error(f"Error subida: {e}")
    finally:
        clean_up_files(chat_id)

# --- Handlers ---

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    chat_id = message.chat.id
    # No borramos todo, solo reseteamos estado de archivos pero mantenemos preferencia de motor
    if chat_id not in user_data:
        user_data[chat_id] = {'engine': 'CPU'} # CPU por defecto
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Usar GPU (Kaggle)", callback_data="set_engine_GPU")],
        [InlineKeyboardButton("💻 Usar CPU (Estándar)", callback_data="set_engine_CPU")]
    ])
    engine_actual = user_data[chat_id].get('engine', 'CPU')
    await message.reply(
        f"👋 ¡Hola! Configura tu motor de procesamiento.\n\n"
        f"Motor actual: **{engine_actual}**\n\n"
        f"Una vez seleccionado, solo envíame un video.",
        reply_markup=keyboard
    )

@app.on_message(filters.video & filters.private)
async def video_handler(client, message: Message):
    chat_id = message.chat.id
    # Inicializar si no existe o mantener motor
    if chat_id not in user_data:
        user_data[chat_id] = {'engine': 'CPU'}
    
    # Limpiar archivos de procesos anteriores pero NO la preferencia del motor
    clean_up_files(chat_id, keep_engine=True)

    user_data[chat_id].update({
        'state': 'awaiting_action',
        'original_message_id': message.id,
        'video_file_name': message.video.file_name or f"video_{message.id}.mp4",
        'last_update_time': 0,
    })

    engine = user_data[chat_id]['engine']
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🗜️ Comprimir ({engine})", callback_data="action_compress")],
        [InlineKeyboardButton("⚙️ Solo Enviar/Convertir", callback_data="action_convert_only")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
    ])
    await message.reply_text(f"Video recibido. Motor: **{engine}**\n¿Qué deseas hacer?", reply_markup=keyboard, quote=True)

@app.on_callback_query()
async def callback_handler(client, cb: CallbackQuery):
    chat_id = cb.message.chat.id
    user_info = user_data.get(chat_id)
    
    if cb.data.startswith("set_engine_"):
        new_engine = cb.data.split("_")[2]
        if chat_id not in user_data: user_data[chat_id] = {}
        user_data[chat_id]['engine'] = new_engine
        await cb.answer(f"Motor cambiado a {new_engine}", show_alert=True)
        await cb.message.edit(f"✅ Motor configurado: **{new_engine}**\nYa puedes enviarme videos.")
        return

    if not user_info: return
    action = cb.data
    user_info['status_message_id'] = cb.message.id

    if action == "cancel":
        user_info['state'] = 'cancelled'
        await cb.message.edit("Operación cancelada.")
        clean_up_files(chat_id, keep_engine=True)

    elif action == "action_compress":
        user_info['compression_options'] = {'crf': '24', 'resolution': '360', 'preset': 'veryfast'}
        engine = user_info.get('engine', 'CPU')
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Usar {engine} (Default)", callback_data="compressopt_default")],
            [InlineKeyboardButton("⚙️ Ajustes Personalizados", callback_data="compressopt_advanced")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
        ])
        await cb.message.edit(f"Configuración de compresión para **{engine}**:", reply_markup=keyboard)

    elif action == "compressopt_default":
        await run_compression_flow(client, chat_id, cb.message)

    elif action == "action_convert_only":
        await cb.message.edit("Iniciando descarga...")
        if await download_video(client, chat_id, cb.message):
            await show_conversion_options(client, chat_id, cb.message.id)

    elif action == "compressopt_advanced":
        await show_advanced_menu(client, chat_id, cb.message.id, "crf")

    elif action.startswith("adv_"):
        part, val = action.split("_")[1], action.split("_")[2]
        user_info.setdefault('compression_options', {})[part] = val
        next_step = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(part)
        await show_advanced_menu(client, chat_id, cb.message.id, next_step, user_info['compression_options'])

    elif action == "start_advanced_compression":
        await run_compression_flow(client, chat_id, cb.message)

    elif action == "convertopt_asfile":
        user_info['send_as_file'] = True
        await show_rename_options(client, chat_id, cb.message.id)
    
    elif action == "renameopt_no":
        user_info['state'] = 'uploading'
        await upload_final_video(client, chat_id)

# --- Menús Adicionales ---
async def show_advanced_menu(client, chat_id, msg_id, part, opts=None):
    if part == "confirm":
        engine = user_data[chat_id]['engine']
        text = (f"Confirmar {engine}:\n- Calidad: `{opts['crf']}`\n- Res: `{opts['resolution']}p`\n- Preset: `{opts['preset']}`")
        btns = [[InlineKeyboardButton("🚀 Empezar", callback_data="start_advanced_compression")]]
    else:
        menus = {
            "crf": ("Calidad (CRF/CQ)", [("Alta", "20"), ("Media", "24"), ("Baja", "28")], "adv_crf"),
            "resolution": ("Resolución", [("720p", "720"), ("480p", "480"), ("360p", "360")], "adv_resolution"),
            "preset": ("Velocidad", [("Rápido", "ultrafast"), ("Medio", "medium"), ("Lento", "slow")], "adv_preset")
        }
        title, options, prefix = menus[part]
        text = f"Selecciona {title}:"
        btns = [[InlineKeyboardButton(t, callback_data=f"{prefix}_{v}") for t, v in options]]
    
    await update_message(client, chat_id, msg_id, text, reply_markup=InlineKeyboardMarkup(btns))

async def show_conversion_options(client, chat_id, msg_id, text="¿Cómo quieres el video?"):
    btns = [[InlineKeyboardButton("🎞️ Video (Streaming)", callback_data="renameopt_no")],
            [InlineKeyboardButton("📂 Archivo (Documento)", callback_data="convertopt_asfile")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]]
    await update_message(client, chat_id, msg_id, text, reply_markup=InlineKeyboardMarkup(btns))

async def show_rename_options(client, chat_id, msg_id):
    # Simplificado para brevedad, puedes añadir la lógica de renombrar si la usas mucho
    user_info = user_data.get(chat_id)
    user_info['state'] = 'uploading'
    await upload_final_video(client, chat_id)

def clean_up_files(chat_id, keep_engine=False):
    user_info = user_data.get(chat_id)
    if not user_info: return
    for key in ['download_path', 'final_path', 'thumbnail_path']:
        path = user_info.get(key)
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
    
    engine = user_info.get('engine', 'CPU')
    user_data[chat_id] = {'engine': engine} if keep_engine else {}

# --- Arranque ---
async def start_bot_and_server():
    Thread(target=run_server, daemon=True).start()
    await app.start()
    logger.info("Bot Online")
    await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(start_bot_and_server())
    except:
        logger.info("Bot apagado.")
