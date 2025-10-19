import os
import shutil
import asyncio
import requests

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *

# ============================================================
# 🔹 GoFile Configuration
# ============================================================
GOFILE_TOKEN = "dM3oQGFPvzXGURpzFn5OtlZXO6rKo0vj"  # <-- Replace this with your GoFile token
FIXED_GOFILE_FOLDER_NAME = "MyMusic"    # <-- All uploads go here
# ============================================================


# ============================================================
# 🧩 GoFile Utilities
# ============================================================

def get_account_id():
    headers = {"Authorization": f"Bearer {GOFILE_TOKEN}"}
    r = requests.get("https://api.gofile.io/accounts/getid", headers=headers)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise Exception(f"❌ Failed to get account ID: {data}")
    return data["data"]["id"]


def get_root_folder(account_id):
    headers = {"Authorization": f"Bearer {GOFILE_TOKEN}"}
    r = requests.get(f"https://api.gofile.io/accounts/{account_id}", headers=headers)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise Exception(f"❌ Failed to get root folder: {data}")
    return data["data"]["rootFolder"]


def create_folder(parent_id, name=None):
    headers = {
        "Authorization": f"Bearer {GOFILE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"parentFolderId": parent_id}
    if name:
        payload["folderName"] = name
    r = requests.post("https://api.gofile.io/contents/createFolder", headers=headers, json=payload)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise Exception(f"❌ Failed to create folder: {data}")
    return data["data"]["id"]


def get_or_create_fixed_folder():
    """Get the fixed folder or create if it doesn't exist"""
    account_id = get_account_id()
    root_folder = get_root_folder(account_id)
    
    headers = {"Authorization": f"Bearer {GOFILE_TOKEN}"}
    r = requests.get(f"https://api.gofile.io/contents/{root_folder}", headers=headers)
    r.raise_for_status()
    data = r.json()

    # Check if the folder exists
    for item in data["data"]["contents"]:
        if item["name"] == FIXED_GOFILE_FOLDER_NAME and item["type"] == "folder":
            return item["id"]
    
    # Folder not found → create it
    return create_folder(root_folder, FIXED_GOFILE_FOLDER_NAME)


def upload_file(file_path, folder_id):
    headers = {"Authorization": f"Bearer {GOFILE_TOKEN}"}
    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {"folderId": folder_id}
        r = requests.post("https://upload.gofile.io/uploadfile", headers=headers, files=files, data=data)
    try:
        res_json = r.json()
    except Exception:
        raise Exception(f"⚠️ Upload error: {r.text}")
    if res_json.get("status") != "ok":
        raise Exception(f"❌ Failed to upload {os.path.basename(file_path)}: {res_json}")


def get_folder_link(folder_id):
    """Return the GoFile folder link (no ZIP needed)"""
    return f"https://gofile.io/d/{folder_id}"


async def gofile_upload_folder(folder_path):
    """
    Upload all files in a folder to GoFile fixed folder and return the folder link.
    """
    if not GOFILE_TOKEN or GOFILE_TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise Exception("⚠️ Missing GoFile token. Paste it at the top.")

    upload_folder_id = get_or_create_fixed_folder()

    for file in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file)
        if os.path.isfile(file_path):
            upload_file(file_path, upload_folder_id)

    return get_folder_link(upload_folder_id)


# ============================================================
# 🧱 Upload Handlers
# ============================================================

async def track_upload(metadata, user, disable_link=False):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        try:
            folder = os.path.dirname(metadata['filepath'])
            link = await gofile_upload_folder(folder)
            await send_message(user, link, 'text', caption="🎵 Track uploaded to GoFile folder")
        except Exception as e:
            await send_message(user, f"❌ Track upload failed!\n{e}")
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
        if not disable_link:
            await post_simple_message(user, metadata, rclone_link, index_link)

    try:
        os.remove(metadata['filepath'])
    except FileNotFoundError:
        pass


async def album_upload(metadata, user):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        try:
            link = await gofile_upload_folder(metadata['folderpath'])
            await send_message(user, link, 'text', caption="📀 Album uploaded to GoFile folder")
        except Exception as e:
            await send_message(user, f"❌ Album upload failed!\n{e}")
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link,
                                       await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata)


async def artist_upload(metadata, user):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        try:
            link = await gofile_upload_folder(metadata['folderpath'])
            await send_message(user, link, 'text', caption="🎤 Artist uploaded to GoFile folder")
        except Exception as e:
            await send_message(user, f"❌ Artist upload failed!\n{e}")
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link,
                                       await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata)


async def playlist_upload(metadata, user):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        try:
            link = await gofile_upload_folder(metadata['folderpath'])
            await send_message(user, link, 'text', caption="🎧 Playlist uploaded to GoFile folder")
        except Exception as e:
            await send_message(user, f"❌ Playlist upload failed!\n{e}")
    else:
        if bot_set.playlist_sort and not bot_set.playlist_zip:
            if bot_set.disable_sort_link:
                await rclone_upload(user, f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            else:
                for track in metadata['tracks']:
                    try:
                        rclone_link, index_link = await rclone_upload(user, track['filepath'])
                        if not bot_set.disable_sort_link:
                            await post_simple_message(user, track, rclone_link, index_link)
                    except ValueError:
                        pass
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
            if metadata['poster_msg']:
                try:
                    await edit_art_poster(metadata, user, rclone_link, index_link,
                                           await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified:
                    pass
            else:
                await post_simple_message(user, metadata, rclone_link, index_link)


# ============================================================
# ⚙️ Existing Local & Rclone Uploads
# ============================================================

async def rclone_upload(user, realpath):
    path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    cmd = f'rclone copy --config ./rclone.conf "{path}" "{Config.RCLONE_DEST}"'
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
    r_link, i_link = await create_link(realpath, Config.DOWNLOAD_BASE_DIR + f"/{user['r_id']}/")
    return r_link, i_link


async def local_upload(metadata, user):
    to_move = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
    destination = os.path.join(Config.LOCAL_STORAGE, os.path.basename(to_move))

    if os.path.exists(destination):
        for item in os.listdir(to_move):
            src_item = os.path.join(to_move, item)
            dest_item = os.path.join(destination, item)
            if os.path.isdir(src_item):
                if not os.path.exists(dest_item):
                    shutil.copy
