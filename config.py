import os
import subprocess
import shutil
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIG ---
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
BEATPORTDL_DIR = "/path/to/your/beatportdl"  # path to your beatportdl CLI
DOWNLOADS_DIR = os.path.join(BEATPORTDL_DIR, "downloads")

# --- HELPERS ---

def run_beatportdl(link: str):
    """Run the BeatportDL CLI command"""
    cmd = ["go", "run", "./cmd/beatportdl", link]
    subprocess.run(cmd, cwd=BEATPORTDL_DIR, check=True)

def cleanup_path(path: str):
    """Delete a file or folder"""
    if os.path.isfile(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)

# --- BOT HANDLER ---

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /download <beatport-link>")
        return

    link = context.args[0]
    await update.message.reply_text("🎧 Download started... please wait.")

    try:
        # Run your CLI downloader
        run_beatportdl(link)

        # Determine release ID and path
        release_id = link.rstrip("/").split("/")[-1]
        release_path = os.path.join(DOWNLOADS_DIR, release_id)

        if not os.path.exists(release_path):
            await update.message.reply_text("⚠️ Download folder not found.")
            return

        sent_files = 0

        # --- Case 1: Single Track (file directly inside release folder) ---
        single_files = [f for f in os.listdir(release_path) if f.endswith(('.flac', '.mp3'))]
        if single_files:
            await update.message.reply_text(f"🎵 Sending {len(single_files)} track(s)...")
            for f in single_files:
                file_path = os.path.join(release_path, f)
                await update.message.reply_document(open(file_path, "rb"))
                sent_files += 1

        # --- Case 2: Album (subfolder inside release folder) ---
        else:
            for subdir in os.listdir(release_path):
                subfolder = os.path.join(release_path, subdir)
                if os.path.isdir(subfolder):
                    files = [f for f in os.listdir(subfolder) if f.endswith(('.flac', '.mp3'))]
                    await update.message.reply_text(f"🎶 Sending {len(files)} album track(s)...")
                    for f in files:
                        file_path = os.path.join(subfolder, f)
                        await update.message.reply_document(open(file_path, "rb"))
                        sent_files += 1

        # --- Cleanup after sending ---
        if sent_files > 0:
            cleanup_path(release_path)
            await update.message.reply_text(f"✅ Sent {sent_files} file(s) and cleaned up.")
        else:
            await update.message.reply_text("⚠️ No audio files found after download.")

    except subprocess.CalledProcessError:
        await update.message.reply_text("❌ CLI download failed. Check BeatportDL output.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

# --- MAIN ---

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("download", download_command))
    print("🤖 BeatportDL Telegram bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
