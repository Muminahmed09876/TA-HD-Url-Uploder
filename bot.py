import os
import asyncio
import aiohttp
import tempfile
import shutil
import subprocess

from pyrogram import Client, filters
from pyrogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())

if not BOT_TOKEN or not API_ID or not API_HASH or not ADMIN_IDS:
    print("Error: BOT_TOKEN, API_ID, API_HASH or ADMIN_IDS environment variables missing!")
    exit(1)

app = Client("ta_hd_uploader_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# Helper function to download file from url
async def download_file(url: str, file_path: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return False
            with open(file_path, "wb") as f:
                while True:
                    chunk = await resp.content.read(1024*1024)
                    if not chunk:
                        break
                    f.write(chunk)
    return True

# Check if file is a video (by extension)
def is_video(filename):
    video_ext = ['.mp4', '.mkv', '.mov', '.avi', '.flv', '.wmv', '.webm']
    return any(filename.lower().endswith(ext) for ext in video_ext)

# Convert video to mp4 using ffmpeg
def convert_to_mp4(input_path, output_path):
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        "-movflags", "+faststart",
        "-y",
        output_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0

# Admin only filter decorator
def admin_only(func):
    async def wrapper(client, message):
        user_id = message.from_user.id if message.from_user else None
        if user_id not in ADMIN_IDS:
            await message.reply("❌ You are not authorized to use this bot.")
            return
        await func(client, message)
    return wrapper

# Store rename and thumbnail info per user in memory
user_data = {}

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    await message.reply_text(
        "👋 TA HD URL Uploader Bot\n\n"
        "Send me a direct file URL or Google Drive link and I'll upload it for you.\n\n"
        "Commands:\n"
        "/rename newfilename.ext - Rename next upload\n"
        "/setthumb - Reply to an image to set thumbnail\n\n"
        "Only admins can use this bot."
    )

@app.on_message(filters.command("rename") & filters.private)
@admin_only
async def rename_handler(client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /rename newfilename.ext")
        return
    newname = message.text.split(None,1)[1].strip()
    user_data[message.from_user.id] = user_data.get(message.from_user.id, {})
    user_data[message.from_user.id]['rename'] = newname
    await message.reply(f"✅ Next uploaded file will be renamed to: {newname}")

@app.on_message(filters.command("setthumb") & filters.private)
@admin_only
async def setthumb_handler(client, message: Message):
    if message.reply_to_message and message.reply_to_message.photo:
        photo = message.reply_to_message.photo
        thumb_path = f"thumb_{message.from_user.id}.jpg"
        await client.download_media(photo.file_id, file_name=thumb_path)
        user_data[message.from_user.id] = user_data.get(message.from_user.id, {})
        user_data[message.from_user.id]['thumb'] = thumb_path
        await message.reply("✅ Thumbnail image set successfully!")
    else:
        await message.reply("Please reply to a photo to set thumbnail.")

@app.on_message(filters.private & filters.text & ~filters.command())
@admin_only
async def url_handler(client, message: Message):
    url = message.text.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        await message.reply("❌ Please send a valid URL.")
        return

    await message.reply("⏳ Downloading file... Please wait.")

    tmpdir = tempfile.mkdtemp()
    try:
        filename = url.split("/")[-1].split("?")[0]
        if not filename:
            filename = "file"

        download_path = os.path.join(tmpdir, filename)
        success = await download_file(url, download_path)
        if not success:
            await message.reply("❌ Failed to download the file.")
            return

        # Rename if requested
        rename_name = user_data.get(message.from_user.id, {}).pop('rename', None)
        if rename_name:
            filename = rename_name
            download_path_renamed = os.path.join(tmpdir, filename)
            shutil.move(download_path, download_path_renamed)
            download_path = download_path_renamed

        # Video check & convert
        if is_video(filename):
            if not filename.lower().endswith(".mp4"):
                converted_path = os.path.join(tmpdir, "converted.mp4")
                await message.reply("🔄 Converting video to mp4 format...")
                converted = await asyncio.get_event_loop().run_in_executor(None, convert_to_mp4, download_path, converted_path)
                if converted:
                    download_path = converted_path
                    filename = os.path.splitext(filename)[0] + ".mp4"
                else:
                    await message.reply("❌ Video conversion failed, uploading original file.")

        thumb_path = user_data.get(message.from_user.id, {}).get('thumb')
        if thumb_path and not os.path.exists(thumb_path):
            thumb_path = None

        await message.reply("📤 Uploading file to Telegram...")
        await client.send_document(
            chat_id=message.chat.id,
            document=download_path,
            thumb=thumb_path,
            file_name=filename,
            disable_notification=True,
        )
        await message.reply("✅ Upload complete!")

    except Exception as e:
        await message.reply(f"❌ Error: {e}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
