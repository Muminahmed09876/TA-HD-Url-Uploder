# TA HD URL Uploader Bot

## Features
- Upload from direct URL or Google Drive link.
- Auto-convert any video format to mp4.
- Rename files.
- Set custom thumbnail.
- Only Admins can use the bot.

## Setup

1. Create bot token from [BotFather](https://t.me/BotFather).
2. Get API_ID and API_HASH from [my.telegram.org](https://my.telegram.org).
3. Find your Telegram user ID from [@userinfobot](https://t.me/userinfobot).
4. Fill `.env` file or set environment variables in Render.

## Deploy on Render

1. Fork or upload this repo to GitHub.
2. Create a new Web Service on Render with this repo.
3. Set environment variables: `BOT_TOKEN`, `API_ID`, `API_HASH`, `ADMIN_IDS`.
4. Use default build and start commands.
5. Deploy and run.

---

## Commands

- `/start` - Show welcome message.
- `/rename newfilename.ext` - Rename next upload.
- `/setthumb` - Reply to an image to set thumbnail.

---

## License

MIT
