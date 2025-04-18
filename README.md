# AI Assistant Telegram Bot

A Telegram bot that combines voice transcription and calendar management features. The bot can transcribe voice messages in multiple languages and help manage your Google Calendar events.

## Features

- 🎙️ Voice Message Transcription
  - Support for multiple languages (English, Spanish, French, German)
  - Offline processing using Vosk
  - Rate limiting to prevent abuse

- 📅 Calendar Management
  - Create new events
  - List upcoming events
  - Interactive event creation process
  - Google Calendar integration

## Prerequisites

1. Python 3.11 or higher
2. FFmpeg (installed automatically during deployment)
3. Telegram Bot Token (from @BotFather)
4. Google Calendar API credentials

## Project Structure

```
telegram-bot/
├── cloud_bot.py           # Main bot file
├── calendar_manager.py    # Calendar integration
├── download_models.py     # Script to download Vosk models
├── requirements.txt       # Python dependencies
├── Procfile              # Railway deployment config
├── .env.example          # Example environment variables
└── README.md             # This file
```

## Environment Variables

Create a `.env` file with the following:

```bash
# Required
TELEGRAM_TOKEN=your_bot_token_here
PORT=8000

# Google Calendar (required for calendar features)
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret

# Optional Proxy Configuration
PROXY_URL_1=your_proxy_url
```

## Local Development

1. Clone the repository
2. Install FFmpeg:
   ```bash
   # Ubuntu/Debian
   sudo apt-get update && sudo apt-get install -y ffmpeg
   
   # Windows
   # Download from https://ffmpeg.org/download.html
   ```

3. Create and activate virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Download Vosk models:
   ```bash
   python download_models.py
   ```

6. Run the bot:
   ```bash
   python cloud_bot.py
   ```

## Railway Deployment

1. Fork this repository

2. Create new project on [Railway](https://railway.app/)

3. Connect your GitHub repository

4. Add environment variables:
   - `TELEGRAM_TOKEN`
   - `PORT`
   - Google Calendar credentials (if using calendar features)

5. Deploy!

The deployment process will automatically:
- Install FFmpeg
- Download required Vosk models
- Start the bot

## Available Commands

- `/start` - Start the bot
- `/help` - Show help message
- `/language` - Set transcription language
- `/calendar_add` - Add new calendar event
- `/calendar_list` - View upcoming events
- `/calendar_help` - Show calendar features help

## Language Support

Currently supported languages:
- English (en)
- Spanish (es)
- French (fr)
- German (de)

More languages can be added by updating the `MODELS` dictionary in `download_models.py`.

## Contributing

1. Fork the repository
2. Create a new branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 