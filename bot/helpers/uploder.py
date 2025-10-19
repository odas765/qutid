import os
import shutil
import asyncio
import requests
import random
import string

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *


# ============================================================
# 🧩 GOFILE CONFIGURATION
# ============================================================
# Paste your GoFile API token below
GOFILE_TOKEN = "BS6TMlxgJW5z8Pi1t2JHjVLAj5aYkUON"  # <-- 🔹 Replace this with your GoFile token
# ============================================================


# ============================================================
# 🧠 GOFILE UPLOAD UTILITIES
# ============================================================

def random_folder_name():
    """Generate a random GoFile folder name"""
    return "Music_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def create_gofile_folder(parentFolderId=None):
    """Create a new folder in GoFile using API and return folderId and link"""
    token = GOFILE_TOKEN
    name = random_folder_name()
    data = {"token": token, "folderName": name}
    if parentFolderId:
        data["parentFolderId"] = parentFolderId

    res = requests.put("https://api.gofile.io/createFolder", data=data).json()
    if res["status"] == "ok":
        folder_id = res["data"]["id"]
        link = res["data"]["link"]
        return folder_id, link
    else:
        raise Exception(f"Failed to create GoFile folder: {res}")


async def gofile_upload_folder(folder_path: str):
    """
    Upload all files from a folder into a newly created GoFile folder
    and return that GoFile folder's share link.
    """
    token = GOFILE_TOKEN
    if not token or token == "PASTE_YOUR_TOKEN_HERE":
        raise Exception("⚠️ GoFile token missing. Please paste it at the top of the file.")

    # Get upload server
    server = requests.get("https://api.gofile.io/getServer").json()['data']['server']

    # Create random GoFile folder
    folder_id, folder_link = await create_gofile_folder()

    # Loop through all files in local folder and upload
    for root, _, files in os.walk(folder_path):
        for file in files:
            local_file = os.path.join(root, file)
            with open(local_file, 'rb') as f:
                res = requests.post(
                    f"https://{server}.gofile.io/uploadFile",
                    files={'file': f},
                    data={'token': token, 'folderId': folder_id}
                ).json()
                if res["status"] != "ok":
                    print(f"❌ Failed to upload {file}: {res}")

    return folder_link


# ============================================================
# 🧱 TASK HANDLER
# ============================================================

async def track_upload(metadata, user, disable_link=False):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)

    elif bot_set.upload_mode == 'Telegram':
        try:
            # single track uploads
            link = await gofile_upload_folder(os.path.dirname(metadata['filepath']))
            await send_message(user, f"🎵 **Track uploaded to GoFile folder:**\n{link}")
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
            await send_message(user, f"📀 **Album uploaded to GoFile folder:**\n{link}")
        except Exception as e:
            await send_message(user, f"❌ Album upload failed!\n{e}")

    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
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
            await send_message(user, f"🎤 **Artist uploaded to GoFile folder:**\n{link}")
        except Exception as e:
            await send_message(user, f"❌ Artist upload failed!\n{e}")

    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
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
            await send_message(user, f"🎧 **Playlist uploaded to GoFile folder:**\n{link}")
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
                    await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified:
                    pass
            else:
                await post_simple_message(user, metadata, rclone_link, index_link)


# ============================================================
# ⚙️ CORE UPLOAD HELPERS
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
                    shutil.copytree(src_item, dest_item)
            else:
                shutil.copy2(src_item, dest_item)
    else:
        shutil.copytree(to_move, destination)
    
    shutil.rmtree(to_move)
