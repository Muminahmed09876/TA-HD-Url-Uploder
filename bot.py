import os
import requests
from urllib.parse import urlparse, parse_qs
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)
from aiohttp import web
import asyncio
import time

TOKEN = os.getenv("TOKEN")
PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # তোমার https URL + বট টোকেনসহ (যেমন: https://yourdomain.com/<token>)

WAITING_FOR_URL, WAITING_FOR_CHOICE = range(2)
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
    await update.message.reply_text("ফাইলের URL দিন (Google Drive বা ডিরেক্ট লিংক)।")
    return WAITING_FOR_URL


async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    context.user_data['download_url'] = url

    keyboard = [
        [
            InlineKeyboardButton("ভিডিও হিসেবে পাঠাও", callback_data='send_video'),
            InlineKeyboardButton("ডকুমেন্ট হিসেবে পাঠাও", callback_data='send_document'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("কিভাবে পাঠাতে চান?", reply_markup=reply_markup)
    return WAITING_FOR_CHOICE


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    choice = query.data  # 'send_video' or 'send_document'
    url = context.user_data.get('download_url')

    if not url:
        await query.edit_message_text("URL পাওয়া যায়নি, দয়া করে /start দিয়ে আবার শুরু করুন।")
        return ConversationHandler.END

    filename = os.path.basename(urlparse(url).path) or "downloaded_file"
    destination_path = os.path.join(DOWNLOAD_FOLDER, filename)
    file_id = extract_file_id(url)

    try:
        if file_id:
            await download_with_progress(url, destination_path, update, context, is_gdrive=True, file_id=file_id)
        else:
            await download_with_progress(url, destination_path, update, context, is_gdrive=False)

        size_in_mb = os.path.getsize(destination_path) / (1024 * 1024)

        with open(destination_path, "rb") as file:
            if choice == 'send_video' and filename.lower().endswith((".mp4", ".mkv", ".avi", ".mov")) and size_in_mb < 50:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=file,
                    caption="আপনার ভিডিও"
                )
            else:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=file,
                    caption="আপনার ফাইল"
                )

        await query.edit_message_text("📤 ফাইল সফলভাবে পাঠানো হয়েছে।")

    except Exception as e:
        await query.edit_message_text(f"❌ সমস্যা হয়েছে: {e}")

    finally:
        if os.path.exists(destination_path):
            os.remove(destination_path)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("বট বন্ধ করা হলো। /start দিয়ে আবার শুরু করুন।")
    return ConversationHandler.END


async def handle_webhook(request):
    # Telegram থেকে POST করা আপডেট পড়বে
    if request.match_info.get('token') != TOKEN:
        return web.Response(status=403)

    data = await request.json()
    update = Update.de_json(data, bot)
    await application.update_queue.put(update)
    return web.Response(status=200)


async def on_startup(app):
    webhook_url = WEBHOOK_URL
    await bot.set_webhook(webhook_url)


async def on_shutdown(app):
    await bot.delete_webhook()


if __name__ == "__main__":
    bot = Bot(token=TOKEN)
    application = ApplicationBuilder().bot(bot).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)],
            WAITING_FOR_CHOICE: [CallbackQueryHandler(button_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # aiohttp ওয়েব সার্ভার সেটআপ
    app = web.Application()
    app.router.add_post(f"/{TOKEN}", handle_webhook)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # Render এ PORT এ লিসেন করবে
    web.run_app(app, port=PORT)
