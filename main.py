import os
import requests
import time
from urllib.parse import urlparse, parse_qs

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("TOKEN")  # Environment variable হিসেবে TOKEN সেট করতে হবে

WAITING_FOR_CHOICE, WAITING_FOR_URL = range(2)
DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


def extract_file_id(drive_url: str) -> str | None:
    parsed = urlparse(drive_url)
    if "drive.google.com" not in parsed.netloc:
        return None
    if "/file/d/" in parsed.path:
        parts = parsed.path.split('/')
        try:
            return parts[3]
        except IndexError:
            return None
    if "id=" in parsed.query:
        qs = parse_qs(parsed.query)
        return qs.get("id", [None])[0]
    return None


def get_confirm_token(response: requests.Response) -> str | None:
    for key, value in response.cookies.items():
        if key.startswith('download_warning'):
            return value
    return None


def format_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


async def download_with_progress(
    url: str,
    destination: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    is_gdrive: bool = False,
    file_id: str | None = None
):
    session = requests.Session()
    if is_gdrive and file_id:
        base_url = "https://docs.google.com/uc?export=download"
        response = session.get(base_url, params={'id': file_id}, stream=True)
        token = get_confirm_token(response)
        if token:
            params = {'id': file_id, 'confirm': token}
            response = session.get(base_url, params=params, stream=True)
    else:
        response = session.get(url, stream=True)

    total_size = int(response.headers.get('Content-Length', 0))
    downloaded = 0
    chunk_size = 32768
    start_time = time.time()

    progress_msg = await update.message.reply_text(
        f"📥 ডাউনলোড শুরু হয়েছে...\nফাইল সাইজ: {format_size(total_size)}\nProgress: 0%"
    )

    chunk_count = 0
    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                chunk_count += 1

                if chunk_count % 10 == 0 or downloaded == total_size:
                    elapsed_time = time.time() - start_time
                    speed = downloaded / elapsed_time if elapsed_time > 0 else 0
                    percent = (downloaded / total_size) * 100 if total_size else 0

                    bar_length = 20
                    filled_length = int(bar_length * percent // 100)
                    bar = "█" * filled_length + "-" * (bar_length - filled_length)

                    try:
                        await context.bot.edit_message_text(
                            chat_id=progress_msg.chat_id,
                            message_id=progress_msg.message_id,
                            text=(
                                f"📥 ডাউনলোড হচ্ছে...\n"
                                f"ফাইল সাইজ: {format_size(total_size)}\n"
                                f"প্রগতি: [{bar}] {percent:.2f}%\n"
                                f"ডাউনলোড হয়েছে: {format_size(downloaded)}\n"
                                f"গতি: {format_size(speed)}/সেকেন্ড"
                            )
                        )
                    except Exception:
                        pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reply_keyboard = [["Send as Video", "Send as Document"]]
    await update.message.reply_text(
        "ফাইল কিভাবে পাঠাতে চান?\n\nSend as Video বা Send as Document বাটন থেকে সিলেক্ট করুন।",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return WAITING_FOR_CHOICE


async def receive_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    if choice not in ["Send as Video", "Send as Document"]:
        await update.message.reply_text("সঠিক অপশন সিলেক্ট করুন।")
        return WAITING_FOR_CHOICE
    context.user_data['send_as_video'] = (choice == "Send as Video")
    await update.message.reply_text("এখন ফাইলের URL দিন:", reply_markup=ReplyKeyboardRemove())
    return WAITING_FOR_URL


async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    file_id = extract_file_id(url)
    filename = os.path.basename(urlparse(url).path) or "downloaded_file"
    destination_path = os.path.join(DOWNLOAD_FOLDER, filename)

    try:
        if file_id:
            await download_with_progress(url, destination_path, update, context, is_gdrive=True, file_id=file_id)
        else:
            await download_with_progress(url, destination_path, update, context, is_gdrive=False)

        await update.message.reply_text("✅ ডাউনলোড সম্পন্ন হয়েছে, Telegram-এ পাঠানো হচ্ছে...")

        size_in_mb = os.path.getsize(destination_path) / (1024 * 1024)
        send_as_video = context.user_data.get('send_as_video', False)

        with open(destination_path, "rb") as file:
            if send_as_video and filename.lower().endswith((".mp4", ".mkv", ".avi", ".mov")) and size_in_mb < 50:
                await context.bot.send_video(
                    chat_id=update.message.chat_id,
                    video=file,
                    caption="আপনার ভিডিও"
                )
            else:
                await context.bot.send_document(
                    chat_id=update.message.chat_id,
                    document=file,
                    caption="আপনার ফাইল"
                )

        await update.message.reply_text("📤 ফাইল সফলভাবে পাঠানো হয়েছে।")

    except Exception as e:
        await update.message.reply_text(f"❌ সমস্যা হয়েছে: {e}")

    finally:
        if os.path.exists(destination_path):
            os.remove(destination_path)

    # ইউজারকে আবার অপশন দিতে চাইলে নিচের লাইন
    return WAITING_FOR_CHOICE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("বট বন্ধ করা হলো। /start দিয়ে আবার শুরু করুন।")
    return ConversationHandler.END


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_CHOICE: [MessageHandler(filters.Regex("^(Send as Video|Send as Document)$"), receive_choice)],
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
