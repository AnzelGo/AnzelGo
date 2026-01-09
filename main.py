# ==========================================

# 1. IMPORTACIONES GLOBALES

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



# ==========================================

# CONFIGURACIÓN GLOBAL Y CONTROLADOR (BOT 4)

# ==========================================



# Archivo persistente para usuarios autorizados

DB_PATH = "authorized_users.json"



def load_authorized():

    if os.path.exists(DB_PATH):

        try:

            with open(DB_PATH, "r") as f: return json.load(f)

        except: return {}

    return {}



def save_authorized(users):

    with open(DB_PATH, "w") as f: json.dump(users, f)



# --- CREDENCIALES ---

API_ID = int(os.getenv("API_ID"))

API_HASH = os.getenv("API_HASH")

BOT1_TOKEN = os.getenv("BOT1_TOKEN")

BOT2_TOKEN = os.getenv("BOT2_TOKEN")

BOT3_TOKEN = os.getenv("BOT3_TOKEN")

BOT4_TOKEN = os.getenv("BOT4_TOKEN")

ADMIN_ID = int(os.getenv("ADMIN_ID")) 



# --- ESTADOS ---

BOT_STATUS = {1: False, 2: False, 3: False}

ONLY_ADMIN_MODE = False

AUTHORIZED_USERS = load_authorized() # Ahora es un diccionario {str(id): "Nombre"}

WAITING_FOR_ID = False 



# --- CLIENTES ---

app1 = Client("bot_uploader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT1_TOKEN)

app2 = Client("bot_video_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT2_TOKEN)

app3 = Client("bot_limpieza", api_id=API_ID, api_hash=API_HASH, bot_token=BOT3_TOKEN)

app4 = Client("bot_master", api_id=API_ID, api_hash=API_HASH, bot_token=BOT4_TOKEN)



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)



# ==========================================

# ⚡ SISTEMA DE SEGURIDAD Y ACCESO PRIVADO ⚡

# ==========================================

from pyrogram import StopPropagation

from pyrogram.types import CallbackQuery, Message

from pyrogram.handlers import MessageHandler, CallbackQueryHandler



def create_power_guard(bot_id):

    async def power_guard(client, update):

        user_id = update.from_user.id if update.from_user else 0

        

        # 1. FILTRO APAGADO

        if not BOT_STATUS.get(bot_id, False):

            msg_off = (

                "🛠 **SISTEMA EN MANTENIMIENTO** 🛠\n\n"

                "Estimado usuario, este módulo se encuentra actualmente en "

                "labores de optimización. Por favor, inténtelo más tarde.\n\n"

                "*Disculpe las molestias.*"

            )

            if isinstance(update, CallbackQuery):

                try: await update.answer("⚠️ Este sistema está APAGADO por mantenimiento.", show_alert=True)

                except: pass

            elif isinstance(update, Message) and update.chat.type.value == "private":

                try: await update.reply_text(msg_off)

                except: pass

            raise StopPropagation



        # 2. FILTRO MODO PRIVADO

        if ONLY_ADMIN_MODE:

            if user_id != ADMIN_ID and str(user_id) not in AUTHORIZED_USERS:

                msg_priv = (

                    "🔒 **ACCESO RESTRINGIDO** 🔒\n\n"

                    "Este bot ha sido puesto en **Modo Privado** por el administrador. "

                    "Actualmente solo usuarios autorizados pueden interactuar, contacta con el administrador para obtener el acceso. ADM: @AnzZGTv1\n\n"

                    f"👤 **Tu ID:** `{user_id}`"

                )

                if isinstance(update, CallbackQuery):

                    try: await update.answer("🔒 Modo Privado Activo. Acceso denegado.", show_alert=True)

                    except: pass

                elif isinstance(update, Message) and update.chat.type.value == "private":

                    try: await update.reply_text(msg_priv)

                    except: pass

                raise StopPropagation

            

    return power_guard



for bid, app in [(1, app1), (2, app2), (3, app3)]:

    guard = create_power_guard(bid)

    app.add_handler(MessageHandler(guard), group=-1)

    app.add_handler(CallbackQueryHandler(guard), group=-1)



# ==========================================

# LÓGICA PANEL DE CONTROL (BOT 4)

# ==========================================



def get_main_menu():

    s = lambda x: "🟢" if BOT_STATUS[x] else "🔴"

    adm_btn = "🔐 PRIVADO: ON" if ONLY_ADMIN_MODE else "🔓 PRIVADO: OFF"

    

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(f"{s(1)} UPLOADER", callback_data="t_1"),

            InlineKeyboardButton(f"{s(2)} ANZEL PRO", callback_data="t_2")

        ],

        [

            InlineKeyboardButton(f"{s(3)} DOWNLOADS", callback_data="t_3"),

            InlineKeyboardButton("🔄 REFRESH", callback_data="refresh")

        ],

        [

            InlineKeyboardButton(f"{adm_btn}", callback_data="toggle_admin"),

            InlineKeyboardButton("🧹 PURGE", callback_data="clean_all")

        ],

        [

            InlineKeyboardButton("➕ AGREGAR ID", callback_data="add_user"),

            InlineKeyboardButton("👥 LISTA", callback_data="view_users")

        ],

        [

            InlineKeyboardButton("⚡ POWER ON", callback_data="all_on"),

            InlineKeyboardButton("❄️ STANDBY", callback_data="all_off")

        ]

    ])



def get_status_text():

    cpu = psutil.cpu_percent()

    ram = psutil.virtual_memory()

    disco = shutil.disk_usage("/")

    

    def mini_bar(pct, total=5):

        filled = int(pct / 100 * total)

        return "▰" * filled + "▱" * (total - filled)



    status_icon = "📡" if any(BOT_STATUS.values()) else "💤"

    adm_tag = "⚠️ <b>MODO PRIVADO ACTIVO</b>\n" if ONLY_ADMIN_MODE else ""

    

    return (

        f"<b>{status_icon} SYSTEM CORE DASHBOARD</b>\n"

        f"{adm_tag}"

        f"<code>──────────────────────</code>\n"

        f"<b>MODULOS DE SERVICIO:</b>\n"

        f"  ├ <b>Uploader</b>   ▸ {'<code>ON</code>' if BOT_STATUS[1] else '<code>OFF</code>'}\n"

        f"  ├ <b>Anzel Pro</b>  ▸ {'<code>ON</code>' if BOT_STATUS[2] else '<code>OFF</code>'}\n"

        f"  └ <b>Downloader</b> ▸ {'<code>ON</code>' if BOT_STATUS[3] else '<code>OFF</code>'}\n"

        f"<code>──────────────────────</code>\n"

        f"<b>RECURSOS ACTUALES DEL NÚCLEO:</b>\n"

        f"  <b>📟 CPU:</b> <code>{cpu}%</code> {mini_bar(cpu)}\n"

        f"  <b>🧠 RAM:</b> <code>{ram.percent}%</code> {mini_bar(ram.percent)}\n"

        f"  <b>💽 DSK:</b> <code>{disco.used // (2**30)}G / {disco.total // (2**30)}G</code>\n"

        f"<code>──────────────────────</code>"

    )



@app4.on_callback_query(filters.user(ADMIN_ID))

async def manager_callbacks(c, q):

    global ONLY_ADMIN_MODE, WAITING_FOR_ID, AUTHORIZED_USERS

    data = q.data

    

    if data.startswith("t_"):

        bid = int(data.split("_")[1])

        BOT_STATUS[bid] = not BOT_STATUS[bid]

        

    elif data == "toggle_admin":

        ONLY_ADMIN_MODE = not ONLY_ADMIN_MODE

        await q.answer(f"Privacidad: {'ACTIVADA' if ONLY_ADMIN_MODE else 'DESACTIVADA'}", show_alert=True)



    elif data == "add_user":

        WAITING_FOR_ID = True

        await q.answer("Envíame el ID del usuario...", show_alert=True)

        return



    elif data == "view_users":

        if not AUTHORIZED_USERS:

            await q.answer("No hay usuarios invitados.", show_alert=True)

            return

        btns = []

        for uid, name in AUTHORIZED_USERS.items():

            btns.append([

                InlineKeyboardButton(f"👤 {name} ({uid})", callback_data="none"),

                InlineKeyboardButton(f"❌ Borrar", callback_data=f"del_{uid}")

            ])

        btns.append([InlineKeyboardButton("🔙 Volver al Panel", callback_data="refresh")])

        await q.message.edit_text("📋 **LISTA DE ACCESO PRIVADO:**", reply_markup=InlineKeyboardMarkup(btns))

        return



    elif data.startswith("del_"):

        uid_to_del = data.split("_")[1]

        if uid_to_del in AUTHORIZED_USERS:

            del AUTHORIZED_USERS[uid_to_del]

            save_authorized(AUTHORIZED_USERS)

            await q.answer("Usuario eliminado.")

            return await manager_callbacks(c, q._replace(data="view_users"))



    elif data == "all_on":

        for k in BOT_STATUS: BOT_STATUS[k] = True

    elif data == "all_off":

        for k in BOT_STATUS: BOT_STATUS[k] = False

    elif data == "refresh":

        WAITING_FOR_ID = False



    try:

        await q.message.edit_text(get_status_text(), reply_markup=get_main_menu())

    except MessageNotModified: pass



@app4.on_message(filters.user(ADMIN_ID) & filters.private)

async def admin_input_handler(client, m):

    global WAITING_FOR_ID, AUTHORIZED_USERS

    if WAITING_FOR_ID and m.text:

        try:

            target_id = m.text.strip()

            if target_id.isdigit():

                if target_id not in AUTHORIZED_USERS:

                    # Intentamos obtener el nombre real del usuario

                    try:

                        user_info = await client.get_users(int(target_id))

                        name = user_info.first_name or "Desconocido"

                    except:

                        name = "Desconocido"

                    

                    AUTHORIZED_USERS[target_id] = name

                    save_authorized(AUTHORIZED_USERS)

                    await m.reply_text(f"✅ **{name}** (`{target_id}`) autorizado.")

                else:

                    await m.reply_text("⚠️ Este ID ya tiene acceso.")

                WAITING_FOR_ID = False

                await m.reply_text(get_status_text(), reply_markup=get_main_menu())

        except Exception as e:

            await m.reply_text(f"❌ Error: {str(e)}")



@app4.on_message(filters.command("st# ==========================================

# CONFIGURACIÓN GLOBAL Y CONTROLADOR (BOT 4)

# ==========================================



# Archivo persistente para usuarios autorizados

DB_PATH = "authorized_users.json"



def load_authorized():

    if os.path.exists(DB_PATH):

        try:

            with open(DB_PATH, "r") as f: return json.load(f)

        except: return {}

    return {}



def save_authorized(users):

    with open(DB_PATH, "w") as f: json.dump(users, f)



# --- CREDENCIALES ---

API_ID = int(os.getenv("API_ID"))

API_HASH = os.getenv("API_HASH")

BOT1_TOKEN = os.getenv("BOT1_TOKEN")

BOT2_TOKEN = os.getenv("BOT2_TOKEN")

BOT3_TOKEN = os.getenv("BOT3_TOKEN")

BOT4_TOKEN = os.getenv("BOT4_TOKEN")

ADMIN_ID = int(os.getenv("ADMIN_ID")) 

ADMIN_USERNAME = "AnzZGTv1" # Tu usuario sin el @



# --- ESTADOS ---

BOT_STATUS = {1: False, 2: False, 3: False}

ONLY_ADMIN_MODE = False

AUTHORIZED_USERS = load_authorized() 

WAITING_FOR_ID = False 



# --- CLIENTES ---

app1 = Client("bot_uploader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT1_TOKEN)

app2 = Client("bot_video_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT2_TOKEN)

app3 = Client("bot_limpieza", api_id=API_ID, api_hash=API_HASH, bot_token=BOT3_TOKEN)

app4 = Client("bot_master", api_id=API_ID, api_hash=API_HASH, bot_token=BOT4_TOKEN)



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)



# ==========================================

# ⚡ SISTEMA DE SEGURIDAD Y ACCESO PRIVADO ⚡

# ==========================================

from pyrogram import StopPropagation

from pyrogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from pyrogram.handlers import MessageHandler, CallbackQueryHandler



def create_power_guard(bot_id):

    async def power_guard(client, update):

        user_id = update.from_user.id if update.from_user else 0

        

        # 1. FILTRO APAGADO

        if not BOT_STATUS.get(bot_id, False):

            msg_off = (

                "🛠 **SISTEMA EN MANTENIMIENTO** 🛠\n\n"

                "Estimado usuario, este módulo se encuentra actualmente en "

                "labores de optimización. Por favor, inténtelo más tarde.\n\n"

                "*Disculpe las molestias.*"

            )

            if isinstance(update, CallbackQuery):

                try: await update.answer("⚠️ Este sistema está APAGADO por mantenimiento.", show_alert=True)

                except: pass

            elif isinstance(update, Message) and update.chat.type.value == "private":

                try: await update.reply_text(msg_off)

                except: pass

            raise StopPropagation



        # 2. FILTRO MODO PRIVADO

        if ONLY_ADMIN_MODE:

            if user_id != ADMIN_ID and str(user_id) not in AUTHORIZED_USERS:

                msg_priv = (

                    "🔒 **ACCESO RESTRINGIDO** 🔒\n\n"

                    "Este bot ha sido puesto en **Modo Privado** por el administrador. "

                    "Actualmente solo usuarios autorizados pueden interactuar.\n\n"

                    "Pulsa el botón de abajo para solicitar tu acceso."

                )

                # Creamos el botón que redirige a tu chat con su ID listo para enviar

                request_kb = InlineKeyboardMarkup([[

                    InlineKeyboardButton("📩 PEDIR ACCESO", url=f"https://t.me/{ADMIN_USERNAME}?text=Hola,%20solicito%20acceso.%20Mi%20ID:%20{user_id}")

                ]])



                if isinstance(update, CallbackQuery):

                    try: await update.answer("🔒 Modo Privado Activo. Acceso denegado.", show_alert=True)

                    except: pass

                elif isinstance(update, Message) and update.chat.type.value == "private":

                    try: await update.reply_text(msg_priv, reply_markup=request_kb)

                    except: pass

                raise StopPropagation

            

    return power_guard



for bid, app in [(1, app1), (2, app2), (3, app3)]:

    guard = create_power_guard(bid)

    app.add_handler(MessageHandler(guard), group=-1)

    app.add_handler(CallbackQueryHandler(guard), group=-1)



# ==========================================

# LÓGICA PANEL DE CONTROL (BOT 4)

# ==========================================



def get_main_menu():

    s = lambda x: "🟢" if BOT_STATUS[x] else "🔴"

    adm_btn = "🔐 PRIVADO: ON" if ONLY_ADMIN_MODE else "🔓 PRIVADO: OFF"

    

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(f"{s(1)} UPLOADER", callback_data="t_1"),

            InlineKeyboardButton(f"{s(2)} ANZEL PRO", callback_data="t_2")

        ],

        [

            InlineKeyboardButton(f"{s(3)} DOWNLOADS", callback_data="t_3"),

            InlineKeyboardButton("🔄 REFRESH", callback_data="refresh")

        ],

        [

            InlineKeyboardButton(f"{adm_btn}", callback_data="toggle_admin"),

            InlineKeyboardButton("🧹 PURGE", callback_data="clean_all")

        ],

        [

            InlineKeyboardButton("➕ AGREGAR ID", callback_data="add_user"),

            InlineKeyboardButton("👥 LISTA", callback_data="view_users")

        ],

        [

            InlineKeyboardButton("⚡ POWER ON", callback_data="all_on"),

            InlineKeyboardButton("❄️ STANDBY", callback_data="all_off")

        ]

    ])



def get_status_text():

    cpu = psutil.cpu_percent()

    ram = psutil.virtual_memory()

    disco = shutil.disk_usage("/")

    

    def mini_bar(pct, total=5):

        filled = int(pct / 100 * total)

        return "▰" * filled + "▱" * (total - filled)



    status_icon = "📡" if any(BOT_STATUS.values()) else "💤"

    adm_tag = "⚠️ <b>MODO PRIVADO ACTIVO</b>\n" if ONLY_ADMIN_MODE else ""

    

    return (

        f"<b>{status_icon} SYSTEM CORE DASHBOARD</b>\n"

        f"{adm_tag}"

        f"<code>──────────────────────</code>\n"

        f"<b>MODULOS DE SERVICIO:</b>\n"

        f"  ├ <b>Uploader</b>   ▸ {'<code>ON</code>' if BOT_STATUS[1] else '<code>OFF</code>'}\n"

        f"  ├ <b>Anzel Pro</b>  ▸ {'<code>ON</code>' if BOT_STATUS[2] else '<code>OFF</code>'}\n"

        f"  └ <b>Downloader</b> ▸ {'<code>ON</code>' if BOT_STATUS[3] else '<code>OFF</code>'}\n"

        f"<code>──────────────────────</code>\n"

        f"<b>RECURSOS ACTUALES DEL NÚCLEO:</b>\n"

        f"  <b>📟 CPU:</b> <code>{cpu}%</code> {mini_bar(cpu)}\n"

        f"  <b>🧠 RAM:</b> <code>{ram.percent}%</code> {mini_bar(ram.percent)}\n"

        f"  <b>💽 DSK:</b> <code>{disco.used // (2**30)}G / {disco.total // (2**30)}G</code>\n"

        f"<code>──────────────────────</code>"

    )



@app4.on_callback_query(filters.user(ADMIN_ID))

async def manager_callbacks(c, q):

    global ONLY_ADMIN_MODE, WAITING_FOR_ID, AUTHORIZED_USERS

    data = q.data

    

    if data.startswith("t_"):

        bid = int(data.split("_")[1])

        BOT_STATUS[bid] = not BOT_STATUS[bid]

        

    elif data == "toggle_admin":

        ONLY_ADMIN_MODE = not ONLY_ADMIN_MODE

        await q.answer(f"Privacidad: {'ACTIVADA' if ONLY_ADMIN_MODE else 'DESACTIVADA'}", show_alert=True)



    elif data == "add_user":

        WAITING_FOR_ID = True

        await q.answer("Envíame el ID del usuario...", show_alert=True)

        return



    elif data == "view_users":

        if not AUTHORIZED_USERS:

            await q.answer("No hay usuarios invitados.", show_alert=True)

            return

        btns = []

        for uid, name in AUTHORIZED_USERS.items():

            btns.append([

                InlineKeyboardButton(f"👤 {name} ({uid})", callback_data="none"),

                InlineKeyboardButton(f"❌ Borrar", callback_data=f"del_{uid}")

            ])

        btns.append([InlineKeyboardButton("🔙 Volver al Panel", callback_data="refresh")])

        await q.message.edit_text("📋 **LISTA DE ACCESO PRIVADO:**", reply_markup=InlineKeyboardMarkup(btns))

        return



    elif data.startswith("del_"):

        uid_to_del = data.split("_")[1]

        if uid_to_del in AUTHORIZED_USERS:

            del AUTHORIZED_USERS[uid_to_del]

            save_authorized(AUTHORIZED_USERS)

            await q.answer("Usuario eliminado.")

            return await manager_callbacks(c, q._replace(data="view_users"))



    elif data == "clean_all":

        # Purga mejorada de directorios

        target_dirs = ["downloads", "/kaggle/working/downloads"]

        cleaned_count = 0

        for d in target_dirs:

            if os.path.exists(d):

                try:

                    shutil.rmtree(d)

                    os.makedirs(d)

                    cleaned_count += 1

                except: pass

        await q.answer(f"🧹 Purga Completa: {cleaned_count} directorios reseteados", show_alert=True)



    elif data == "all_on":

        for k in BOT_STATUS: BOT_STATUS[k] = True

    elif data == "all_off":

        for k in BOT_STATUS: BOT_STATUS[k] = False

    elif data == "refresh":

        WAITING_FOR_ID = False



    try:

        await q.message.edit_text(get_status_text(), reply_markup=get_main_menu())

    except MessageNotModified: pass



@app4.on_message(filters.user(ADMIN_ID) & filters.private)

async def admin_input_handler(client, m):

    global WAITING_FOR_ID, AUTHORIZED_USERS

    if WAITING_FOR_ID and m.text:

        # Extraer ID por si el admin reenvía el mensaje que le llega del usuario

        ids_found = re.findall(r'\d+', m.text)

        if ids_found:

            target_id = ids_found[-1] # Toma el último número encontrado (el ID)

            if target_id not in AUTHORIZED_USERS:

                try:

                    user_info = await client.get_users(int(target_id))

                    name = user_info.first_name or "Desconocido"

                except:

                    name = "Desconocido"

                

                AUTHORIZED_USERS[target_id] = name

                save_authorized(AUTHORIZED_USERS)

                await m.reply_text(f"✅ **{name}** (`{target_id}`) autorizado.")

            else:

                await m.reply_text("⚠️ Este ID ya tiene acceso.")

            WAITING_FOR_ID = False

            await m.reply_text(get_status_text(), reply_markup=get_main_menu())

        else:

            await m.reply_text("❌ No encontré un ID válido en el mensaje.")



@app4.on_message(filters.command("start") & filters.user(ADMIN_ID))

async def start_controller(_, m):

    await m.reply_text(get_status_text(), reply_markup=get_main_menu())



# ==========================================

# FIN DE CONFIGURACIÓN

# ==========================================

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



        use
