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
import subprocess
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
# LÓGICA DE DETECCIÓN AUTOMÁTICA
# =======================================================
def is_gpu_available():
    """Detecta si hay una GPU NVIDIA disponible mediante nvidia-smi."""
    try:
        subprocess.check_output(['nvidia-smi'])
        return True
    except (Exception, FileNotFoundError):
        return False

# Detectar globalmente al inicio
GPU_MODE = is_gpu_available()

# =======================================================
# LÓGICA DE TU BOT (FUSIONADA)
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
    except MessageNotModified: pass
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

    if current_time - last_update_time < 5: return
    user_info['last_update_time'] = current_time

    percentage = (current * 100 / total) if total > 0 else 0
    elapsed_time = current_time - start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    progress_bar = get_progress_bar(percentage)
    action_text_clean = action_text.replace('📥 Descargando', 'DESCARGANDO...').replace('⬆️ Subiendo', 'SUBIENDO...').replace('🗜️ Comprimiendo...', 'COMPRIMIENDO...')

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
    try:
        original_message = await client.get_messages(chat_id, user_info['original_message_id'])
        video_path = await client.download_media(
            message=original_message,
            file_name=os.path.join(DOWNLOAD_DIR, f"{chat_id}_{user_info['video_file_name']}"),
            progress=progress_bar_handler,
            progress_args=(client, status_message, start_time, "📥 Descargando")
        )
        if not video_path or not os.path.exists(video_path): return None
        user_info['download_path'] = video_path
        user_info['final_path'] = video_path
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

        # CAMALEÓN: Estética y Comando según modo
        if is_gpu_available():
            await update_message(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO (GPU)...")
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
            engine_label = "GPU T4"
        else:
            await update_message(client, chat_id, status_message.id, "🗜️ COMPRIMIENDO...")
            cmd = [
                'ffmpeg', '-i', downloaded_path,
                '-vf', f"scale=-2:{opts['resolution']}",
                '-r', '30', '-crf', opts['crf'], '-preset', opts['preset'],
                '-vcodec', 'libx264', '-acodec', 'aac', '-b:a', '64k',
                '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', '-y', output_path
            ]
            engine_label = ""

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        success = await track_ffmpeg_progress(client, chat_id, status_message.id, process, duration, original_size, output_path)

        if not success:
            await update_message(client, chat_id, status_message.id, "❌ Error de compresión.")
            return

        user_info['final_path'] = output_path
        compressed_size = os.path.getsize(output_path)
        reduction = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
        
        # CAMALEÓN: Resumen estético
        summary_title = f"✅ **Compresión Exitosa ({engine_label})**" if engine_label else "✅ **Compresión Exitosa**"
        summary = (f"{summary_title}\n\n"
                    f"**📏 Original:** `{format_size(original_size)}`\n"
                    f"**📂 Comprimido:** `{format_size(compressed_size)}` (`{reduction:.1f}%` menos)\n\n"
                    f"Ahora, ¿cómo quieres continuar?")
        await show_conversion_options(client, chat_id, status_message.id, text=summary)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update_message(client, chat_id, status_message.id, "❌ Error inesperado.")
    finally:
        if downloaded_path and os.path.exists(downloaded_path): os.remove(downloaded_path)

async def track_ffmpeg_progress(client, chat_id, msg_id, process, duration, original_size, output_path):
    last_update = 0
    ffmpeg_data = {}
    is_gpu = is_gpu_available()

    while True:
        if user_data.get(chat_id, {}).get('state') == 'cancelled':
            if process.returncode is None: process.terminate()
            await update_message(client, chat_id, msg_id, "🛑 Operación cancelada.")
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
                ffmpeg_data.clear()
                continue

            current_time = time.time()
            # Diferente intervalo de actualización según modo (1.5s CPU vs 2.0s GPU de tus códigos)
            interval = 2.0 if is_gpu else 1.5
            if current_time - last_update < interval:
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

            # CAMALEÓN: Título progresivo
            header = "COMPRIMIENDO (GPU)..." if is_gpu else "COMPRIMIENDO..."
            text = (
                f"**{header}**\n"
                f"`[{progress_bar}] {percentage:.1f}%`\n\n"
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
    final_path, status_id = user_info['final_path'], user_info['status_message_id']
    status_message = await client.get_messages(chat_id, status_id)
    final_filename = user_info.get('new_name') or os.path.basename(user_info['video_file_name'])
    if not final_filename.endswith(".mp4"): final_filename += ".mp4"

    try:
        probe = ffmpeg.probe(final_path)
        stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), {})
        duration, width, height = int(float(stream.get('duration', 0))), int(stream.get('width', 0)), int(stream.get('height', 0))
        start_time = time.time()
        await update_message(client, chat_id, status_id, "⬆️ SUBIENDO...")

        if user_info.get('send_as_file'):
            await client.send_document(
                chat_id=chat_id, document=final_path, thumb=user_info.get('thumbnail_path'),
                file_name=final_filename, caption=f"`{final_filename}`",
                progress=progress_bar_handler, progress_args=(client, status_message, start_time, "⬆️ Subiendo")
            )
        else:
            await client.send_video(
                chat_id=chat_id, video=final_path, caption=f"`{final_filename}`",
                thumb=user_info.get('thumbnail_path'), duration=duration, width=width, height=height,
                supports_streaming=True, progress=progress_bar_handler, progress_args=(client, status_message, start_time, "⬆️ Subiendo")
            )
        await status_message.delete()
        await client.send_message(chat_id, "✅ ¡Proceso completado!")
    except Exception as e:
        logger.error(f"Error subida: {e}")
        await update_message(client, chat_id, status_id, "❌ Error durante la subida.")
    finally: clean_up(chat_id)

# --- Handlers ---

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    clean_up(message.chat.id)
    await message.reply("¡Hola! 👋 Soy tu bot para procesar videos.\n\nPuedo **comprimir** y **convertir** tus videos. **Envíame un video para empezar.**")

@app.on_message(filters.video & filters.private)
async def video_handler(client, message: Message):
    chat_id = message.chat.id
    if user_data.get(chat_id): clean_up(chat_id)
    if message.video.file_size > MAX_VIDEO_SIZE_MB * 1024 * 1024:
        await message.reply(f"❌ El video supera el límite de {MAX_VIDEO_SIZE_MB} MB.")
        return
    user_data[chat_id] = {'state': 'awaiting_action', 'original_message_id': message.id, 'video_file_name': message.video.file_name or f"video_{message.id}.mp4", 'last_update_time': 0}
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗜️ Comprimir Video", callback_data="action_compress")], [InlineKeyboardButton("⚙️ Solo Enviar/Convertir", callback_data="action_convert_only")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await message.reply_text("Video recibido. ¿Qué quieres hacer?", reply_markup=keyboard, quote=True)

@app.on_callback_query()
async def callback_handler(client, cb: CallbackQuery):
    chat_id, user_info = cb.message.chat.id, user_data.get(cb.message.chat.id)
    if not user_info:
        await cb.answer("Esta operación ha expirado.", show_alert=True)
        return
    action = cb.data
    user_info['status_message_id'] = cb.message.id
    await cb.answer()

    if action == "cancel":
        user_info['state'] = 'cancelled'
        await cb.message.edit("Operación cancelada.")
        clean_up(chat_id)
    elif action == "action_compress":
        # CAMALEÓN: Diferentes CRF por defecto según modo (GPU: 24, CPU: 22)
        default_crf = '24' if is_gpu_available() else '22'
        user_info['compression_options'] = {'crf': default_crf, 'resolution': '360', 'preset': 'veryfast'}
        await show_compression_options(client, chat_id, cb.message.id)
    elif action == "compressopt_default":
        await cb.message.edit(f"Iniciando compresión {'GPU' if is_gpu_available() else ''} por defecto...")
        await run_compression_flow(client, chat_id, cb.message)
    elif action == "compressopt_advanced":
        await show_advanced_menu(client, chat_id, cb.message.id, "crf")
    elif action.startswith("adv_"):
        part, value = action.split("_")[1], action.split("_")[2]
        user_info.setdefault('compression_options', {})[part] = value
        next_step = {"crf": "resolution", "resolution": "preset", "preset": "confirm"}.get(part)
        if next_step: await show_advanced_menu(client, chat_id, cb.message.id, next_step, user_info['compression_options'])
    elif action == "start_advanced_compression":
        await cb.message.edit(f"Opciones guardadas. Iniciando compresión {'GPU' if is_gpu_available() else ''}...")
        await run_compression_flow(client, chat_id, cb.message)
    elif action == "action_convert_only":
        await cb.message.edit("Iniciando descarga...")
        if await download_video(client, chat_id, cb.message):
            await show_conversion_options(client, chat_id, cb.message.id, text="Descarga completa. ¿Cómo quieres continuar?")
    elif action == "convertopt_withthumb":
        user_info['state'] = 'waiting_for_thumbnail'
        await cb.message.edit("Por favor, envía la imagen para la miniatura.")
    elif action == "convertopt_nothumb":
        user_info['thumbnail_path'] = None
        await show_rename_options(client, chat_id, cb.message.id)
    elif action == "convertopt_asfile":
        user_info['send_as_file'] = True
        await show_rename_options(client, chat_id, cb.message.id)
    elif action == "renameopt_yes":
        user_info['state'] = 'waiting_for_new_name'
        await cb.message.edit("Ok, envíame el nuevo nombre (sin extensión).")
    elif action == "renameopt_no":
        user_info['new_name'] = None
        user_info['state'] = 'uploading'
        await cb.message.edit("Entendido. Preparando para subir...")
        await upload_final_video(client, chat_id)

@app.on_message(filters.photo & filters.private)
async def thumbnail_handler(client, message: Message):
    chat_id, user_info = message.chat.id, user_data.get(message.chat.id)
    if not user_info or user_info.get('state') != 'waiting_for_thumbnail': return
    status_id = user_info['status_message_id']
    await update_message(client, chat_id, status_id, "🖼️ Descargando miniatura...")
    try:
        user_info['thumbnail_path'] = await client.download_media(message=message, file_name=os.path.join(DOWNLOAD_DIR, f"thumb_{chat_id}.jpg"))
        await show_rename_options(client, chat_id, status_id, "Miniatura guardada. ¿Quieres renombrar el video?")
    except: await update_message(client, chat_id, status_id, "❌ Error al descargar la miniatura.")

@app.on_message(filters.text & filters.private)
async def rename_handler(client, message: Message):
    chat_id, user_info = message.chat.id, user_data.get(message.chat.id)
    if not user_info or user_info.get('state') != 'waiting_for_new_name': return
    user_info['new_name'] = message.text.strip()
    await message.delete()
    await update_message(client, chat_id, user_info['status_message_id'], f"✅ Nombre guardado. Preparando para subir...")
    user_info['state'] = 'uploading'
    await upload_final_video(client, chat_id)

# --- Funciones de Menús (FUSIONADAS) ---
async def show_compression_options(client, chat_id, msg_id):
    # CAMALEÓN: Textos según modo
    if is_gpu_available():
        text, btn_rec = "Elige cómo quieres comprimir:", "✅ Usar GPU (Recomendado)"
    else:
        text, btn_rec = "Elige cómo quieres comprimir:", "✅ Usar Opciones Recomendadas"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(btn_rec, callback_data="compressopt_default")], [InlineKeyboardButton("⚙️ Configurar Opciones Avanzadas", callback_data="compressopt_advanced")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await update_message(client, chat_id, msg_id, text, reply_markup=keyboard)

async def show_advanced_menu(client, chat_id, msg_id, part, opts=None):
    is_gpu = is_gpu_available()
    # CAMALEÓN: Opciones de CRF y títulos según modo
    if is_gpu:
        crf_opts = [("Alta", "20"), ("Media", "24"), ("Económica", "28"), ("Baja", "32")]
        crf_title = "1/3: Calidad GPU (CQ)"
    else:
        crf_opts = [("18", "18"), ("20", "20"), ("22", "22"), ("25", "25"), ("28", "28")]
        crf_title = "1/3: Calidad (CRF)"

    menus = {
        "crf": {"text": crf_title, "opts": crf_opts, "prefix": "adv_crf"},
        "resolution": {"text": "2/3: Resolución", "opts": [("1080p", "1080"), ("720p", "720"), ("480p", "480"), ("360p", "360"), ("240p", "240")], "prefix": "adv_resolution"},
        "preset": {"text": f"3/3: Velocidad {'GPU' if is_gpu else ''}", "opts": [("Máxima", "ultrafast"), ("Equilibrada", "medium"), ("Calidad", "slow")], "prefix": "adv_preset"}
    }
    
    if part == "confirm":
        # CAMALEÓN: Resumen de confirmación
        label = " (CQ)" if is_gpu else " (CRF)"
        text = (f"Confirmar opciones {'GPU' if is_gpu else ''}:\n"
                f"- Calidad{label}: `{opts.get('crf', 'N/A')}`\n"
                f"- Resolución: `{opts.get('resolution', 'N/A')}p`\n"
                f"- Preset: `{opts.get('preset', 'N/A')}`")
        btn_text = "🚀 Iniciar Compresión GPU" if is_gpu else "✅ Iniciar Compresión"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, callback_data="start_advanced_compression")]])
    else:
        info = menus[part]
        buttons = [InlineKeyboardButton(t, callback_data=f"{info['prefix']}_{v}") for t, v in info["opts"]]
        # Dividir botones en filas de 2 o 3 para estética
        keyboard = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
        text = info["text"]
    await update_message(client, chat_id, msg_id, text, reply_markup=keyboard)

async def show_conversion_options(client, chat_id, msg_id, text="¿Cómo quieres enviar el video?"):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🖼️ Con Miniatura", callback_data="convertopt_withthumb")], [InlineKeyboardButton("🚫 Sin Miniatura", callback_data="convertopt_nothumb")], [InlineKeyboardButton("📂 Enviar como Archivo", callback_data="convertopt_asfile")], [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
    await update_message(client, chat_id, msg_id, text, reply_markup=keyboard)

async def show_rename_options(client, chat_id, msg_id, text="¿Quieres renombrar el archivo?"):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Sí, renombrar", callback_data="renameopt_yes")], [InlineKeyboardButton("➡️ No, usar original", callback_data="renameopt_no")]])
    await update_message(client, chat_id, msg_id, text, reply_markup=keyboard)

def clean_up(chat_id):
    user_info = user_data.pop(chat_id, None)
    if not user_info: return
    for key in ['download_path', 'thumbnail_path', 'final_path']:
        path = user_info.get(key)
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass

async def start_bot_and_server():
    Thread(target=run_server).start()
    for proc in psutil.process_iter(['pid', 'name']):
        if 'ffmpeg' in proc.info['name'].lower():
            try: proc.terminate()
            except: pass
    await app.start()
    me = await app.get_me()
    mode = "GPU T4 🚀" if is_gpu_available() else "CPU 💻"
    logger.info(f"Bot @{me.username} online en modo {mode}")
    await asyncio.Future()

if __name__ == "__main__":
    try: asyncio.run(start_bot_and_server())
    except: logger.info("Bot detenido.")
