# Paso 1: Instalación de las bibliotecas necesarias
# !pip install pyrogram tgcrypto ffmpeg-python nest_asyncio psutil python-dotenv

# Paso 2: Importar bibliotecas necesarias
import os
import ffmpeg
from pyrogram.types import Message
import nest_asyncio
import asyncio
from pyrogram import Client, filters
import psutil
import time
import sys
import re
import threading
from pyrogram import Client
from dotenv import load_dotenv # Importación para seguridad

# Cargar variables de entorno (solo funciona en entornos con .env file)
load_dotenv()
nest_asyncio.apply()

# Paso 3: Definir tu API ID y Hash de forma segura
# Cargamos desde las variables de entorno para que no queden expuestas
API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
BOT_TOKEN = os.environ.get('BOT_TOKEN')


# Paso 4: Crear una instancia del bot
if not all([API_ID, API_HASH, BOT_TOKEN]):
    print("Error: Las variables API_ID, API_HASH o BOT_TOKEN no están definidas en el entorno.")
    # Si quieres que funcione en MyBinder, necesitarás que el entorno donde se ejecute las defina.
    # En este punto, si no están, el bot no iniciará.
    # sys.exit(1) # Descomenta esto si quieres que el bot se detenga si faltan las variables

app = Client("video_compressor_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


async def mostrar_barra_progreso(client, chat_id, mensaje_id, completado, total, velocidad, peso_original, peso_comprimido, texto_anterior):
    porcentaje = min(completado / total * 100, 100) if total else 0
    num_barras = int(porcentaje / 10)
    barra = '■ ' * num_barras + '▣' * (10 - num_barras)

    message_text = (f"╔𓊈{barra}𓊉 {porcentaje:.2f}%\n"
                    f"╠➤𝗩𝗲𝗹𝗼𝗰𝗶𝗱𝗮𝗱: {velocidad:.2f} kbs\n"
                    f"╠➤𝗣𝗲𝘀𝗼 𝗼𝗿𝗶𝗴𝗶𝗻𝗮𝗹: {peso_original:.2f} MB\n"
                    f"╚➤𝗣𝗲𝗻𝗿𝗮𝗴𝗼 𝗰𝗼𝗺𝗽𝗿𝗶𝗺𝗶𝗱𝗼: {peso_comprimido:.2f} MB")

    if message_text != texto_anterior:
        await client.edit_message_text(chat_id=chat_id, message_id=mensaje_id, text=message_text)
        return message_text
    return texto_anterior

async def comprimir_video(client, archivo_entrada, chat_id):
    nombre_original = os.path.basename(archivo_entrada)
    nombre_salida = f"{os.path.splitext(nombre_original)[0]}_A-Tv Movie.mp4"

    if not os.path.exists(archivo_entrada):
        print("El video no se descargó correctamente.")
        return None

    peso_original = os.path.getsize(archivo_entrada) / (1024 * 1024)

    start_time = time.time()
    last_update_time = start_time

    total_frames = None
    velocidad_kbps = 0

    try:
        probe = ffmpeg.probe(archivo_entrada)
        total_frames = int(probe['streams'][0]['nb_frames']) if 'nb_frames' in probe['streams'][0] else None
    except Exception as e:
        print(f"No se pudieron obtener los frames del video: {e}")

    process = (
        ffmpeg
        .input(archivo_entrada)
        .output(nombre_salida, vf="scale=-2:360,fps=30", crf=22, vcodec='libx264', audio_bitrate='192k', preset='veryfast')
        .overwrite_output()
        .global_args('-progress', 'pipe:1', '-nostats')
        .run_async(pipe_stdout=True, pipe_stderr=True)
    )

    message = await client.send_message(chat_id=chat_id, text="Compresión en progreso...")
    mensaje_id = message.id
    texto_anterior = "Compresión en progreso..."

    frames_completados = 0

    while True:
        output = process.stdout.readline()
        if output == b"" and process.poll() is not None:
            break
        if output:
            try:
                line = output.decode('utf-8').strip()
                if line.startswith('frame='):
                    frames_completados = int(line.split('=')[1].strip())

                    peso_comprimido = os.path.getsize(nombre_salida) / (1024 * 1024)
                    completado = frames_completados if total_frames is None else min(frames_completados, total_frames)
                    velocidad_kbps = (peso_comprimido * 1024) / (time.time() - start_time) if (time.time() - start_time) > 0 else 0

                    current_time = time.time()
                    if current_time - last_update_time > 10:
                        last_update_time = current_time
                        texto_anterior = await mostrar_barra_progreso(
                            client, chat_id, mensaje_id, completado, total_frames, velocidad_kbps, peso_original, peso_comprimido, texto_anterior
                        )
            except Exception as e:
                print(f"Error al procesar la salida de ffmpeg: {e}")

    process.wait()
    await mostrar_barra_progreso(
        client, chat_id, mensaje_id, frames_completados, total_frames, velocidad_kbps, peso_original, peso_comprimido, texto_anterior
    )

    total_time = time.time() - start_time
    print(f"\nCompresión completada en {total_time:.2f} segundos.")

    await client.edit_message_text(chat_id=chat_id, message_id=mensaje_id, text="Compresión completada.")

    return nombre_salida

@app.on_message(filters.video)
async def handle_video(client, message: Message):
    progress_message = await client.send_message(chat_id=message.chat.id, text="📥•𝐃𝐄𝐒𝐂𝐀𝐑𝐆𝐀𝐍𝐃𝐎 𝐕𝐈𝐃𝐄𝐎•📥")

    start_time = time.time()
    video_path = await message.download()
    await client.edit_message_text(chat_id=message.chat.id, message_id=progress_message.id, text="⚙️•𝐂𝐎𝐌𝐏𝐑𝐄𝐒𝐈𝐎𝐍 𝐄𝐍 𝐏𝐑𝐎𝐂𝐄𝐒𝐎•⚙️")

    original_size = os.path.getsize(video_path)

    print("Descarga completada. Iniciando la compresión del video...")
    video_comprimido = await comprimir_video(client, video_path, message.chat.id)
    if video_comprimido is None:
        print("No se pudo comprimir el video.")
        await client.send_message(chat_id=message.chat.id, text="❌ No se pudo comprimir el video.")
        await client.delete_messages(chat_id=message.chat.id, message_ids=[progress_message.id])
        return

    compressed_size = os.path.getsize(video_comprimido)
    elapsed_time = time.time() - start_time


    resultado_text = (f"✅¡𝗖𝗢𝗠𝗣𝗥𝗘𝗦𝗜𝗢𝗡 𝗘𝗫𝗜𝗧𝗢𝗦𝗔!✅\n\n"
                      f"╔➤Tiempo Total: {elapsed_time:.2f} segundos\n"
                      f"╠➤Tamaño Original: {original_size / (1024 * 1024):.2f} MB\n"
                      f"╚➤Tamaño Comprimido: {compressed_size / (1024 * 1024):.2f} MB\n\n"
                      f"¡𝗖𝗢𝗠𝗣𝗥𝗘𝗦𝗦𝗘𝗗 𝗕𝗬! ➤ Anzel_Tech")

    await client.send_document(chat_id=message.chat.id, document=video_comprimido, caption=resultado_text)

    await client.delete_messages(chat_id=message.chat.id, message_ids=[progress_message.id])

    os.remove(video_path)
    os.remove(video_comprimido)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply("¡Hola! Soy un bot para comprimir videos. Por favor, envíame un video para comenzar.")

async def main():
    async with app:
        print("✅•𝐁𝐎𝐓 𝐂𝐎𝐍𝐄𝐂𝐓𝐀𝐃𝐎 𝐄𝐗𝐈𝐓𝐎𝐒𝐀𝐌𝐄𝐍𝐓𝐄•✅")
        await asyncio.sleep(float("inf"))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("El programa se detuvo de forma segura.")
