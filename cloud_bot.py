import os
import logging
import requests
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from notion_client import Client
import google_auth_oauthlib.flow
import tempfile
import pytz
import nltk
from nltk.tokenize import word_tokenize
from nltk.tag import pos_tag
import re
from dateutil import parser as date_parser
from vosk import Model, KaldiRecognizer
import wave
import io
from aiohttp_socks import ProxyConnector
from pydub import AudioSegment
import subprocess

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Notion setup
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# Google Calendar setup
GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE')
CALENDAR_ID = os.getenv('CALENDAR_ID')  # Get from environment variables
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Define conversation states
TASK_NAME, TASK_DATE, TASK_TIME, TASK_DURATION, TASK_ATTENDEES = range(5)
EVENT_NAME, EVENT_DATE, EVENT_TIME, EVENT_DURATION, EVENT_ATTENDEES = range(5)

# Store temporary data
user_data = {}

# Initialize Notion client
notion = Client(auth=NOTION_TOKEN)

def get_google_calendar_service():
    """Create and return Google Calendar service using service account."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except Exception as e:
        logger.error(f"Error creating Google Calendar service: {str(e)}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 Hello! I am your Assistant Bot.\n\n'
        'I can help you with:\n'
        '• Creating tasks in Notion (/task)\n'
        '• Creating calendar events (/calendar)\n'
        '• Managing your tasks and events\n'
        '• Responding to messages\n\n'
        'Try: /task Add meeting notes\n'
        'Or: /calendar Team meeting\n'
        'Check integrations: /status'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Available Commands:\n\n'
        '/start - Start the bot\n'
        '/help - Show this message\n'
        '/task - Create a task\n'
        '/calendar - Create a calendar event\n'
        '/status - Check the status of integrations\n'
    )

# Task creation conversation handlers
async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the task creation conversation."""
    await update.message.reply_text(
        "Let's create a task! Please enter the task name:"
    )
    return TASK_NAME

async def task_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the task name input."""
    context.user_data['task_name'] = update.message.text
    
    # Create a custom keyboard for due date selection
    keyboard = [
        ["Today", "Tomorrow"],
        ["Next Week", "Custom Date"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    await update.message.reply_text(
        "When is this task due?",
        reply_markup=reply_markup
    )
    return TASK_DATE

async def task_date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the task date input."""
    date_text = update.message.text
    today = datetime.now()
    
    if date_text == "Today":
        due_date = today
    elif date_text == "Tomorrow":
        due_date = today + timedelta(days=1)
    elif date_text == "Next Week":
        due_date = today + timedelta(days=7)
    else:
        # Handle custom date input
        try:
            due_date = datetime.strptime(date_text, "%Y-%m-%d")
        except ValueError:
            await update.message.reply_text(
                "Please enter the date in YYYY-MM-DD format:"
            )
            return TASK_DATE
    
    context.user_data['due_date'] = due_date.strftime("%Y-%m-%d")
    
    # Create a custom keyboard for priority selection
    keyboard = [
        ["High", "Medium", "Low"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    await update.message.reply_text(
        "What is the priority of this task?",
        reply_markup=reply_markup
    )
    return TASK_TIME

async def task_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the task time input."""
    time_text = update.message.text
    
    if time_text == "Custom Time":
        await update.message.reply_text(
            "Please enter the time in HH:MM format (24-hour):"
        )
        return TASK_TIME
    
    try:
        event_time = datetime.strptime(time_text, "%I:%M %p").time()
        context.user_data['event_time'] = event_time
        
        # Create a custom keyboard for duration selection
        keyboard = [
            ["15 minutes", "30 minutes", "1 hour"],
            ["2 hours", "Custom duration"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await update.message.reply_text(
            "How long should the event be?",
            reply_markup=reply_markup
        )
        return TASK_DURATION
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid time in HH:MM format (24-hour):"
        )
        return TASK_TIME

async def task_duration_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the task duration input."""
    duration_text = update.message.text
    
    # Convert duration text to minutes
    if duration_text == "15 minutes":
        duration_minutes = 15
    elif duration_text == "30 minutes":
        duration_minutes = 30
    elif duration_text == "1 hour":
        duration_minutes = 60
    elif duration_text == "2 hours":
        duration_minutes = 120
    elif duration_text == "Custom duration":
        await update.message.reply_text(
            "Please enter the duration in minutes:"
        )
        return TASK_DURATION
    else:
        try:
            duration_minutes = int(duration_text)
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid number of minutes:"
            )
            return TASK_DURATION
    
    context.user_data['duration_minutes'] = duration_minutes
    
    await update.message.reply_text(
        "Would you like to add attendees? (Optional)\n"
        "Enter email addresses separated by commas, or type 'skip' to continue without attendees:"
    )
    return TASK_ATTENDEES

async def task_attendees_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the task attendees input and create the task."""
    attendees_text = update.message.text
    
    # Get task details from context
    task_name = context.user_data['task_name']
    due_date = context.user_data['due_date']
    event_time = context.user_data['event_time']
    duration_minutes = context.user_data['duration_minutes']
    
    # Combine date and time
    event_start = datetime.combine(datetime.strptime(due_date, "%Y-%m-%d").date(), event_time)
    event_end = event_start + timedelta(minutes=duration_minutes)
    
    # Process attendees - we'll just store them for information purposes
    attendees = []
    if attendees_text.lower() != 'skip':
        attendees = [email.strip() for email in attendees_text.split(',')]
    
    # Create the task
    try:
        # Create task with correct schema
        new_page = {
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {
                "Title": {
                    "title": [{"text": {"content": task_name}}]
                },
                "Status": {
                    "status": {
                        "name": "Not started"
                    }
                },
                "Priority": {
                    "select": {
                        "name": "Medium"  # Assuming a default priority
                    }
                },
                "Due Date": {
                    "date": {
                        "start": due_date
                    }
                },
                "notes": {
                    "rich_text": [{"text": {"content": "Created via Telegram bot"}}]
                }
            }
        }
        
        # Create the page
        response = notion.pages.create(**new_page)
        page_url = response.get('url', 'No link available')
        
        await update.message.reply_text(
            f"✅ Task created successfully!\n\n"
            f"📝 Task: {task_name}\n"
            f"📅 Due: {due_date}\n"
            f"🕒 Time: {event_start.strftime('%Y-%m-%d %H:%M')}\n"
            f"⏱ Duration: {duration_minutes} minutes\n"
            f"🔗 View it here: {page_url}",
            reply_markup=ReplyKeyboardRemove()
        )
        logger.info(f"Notion task created: {page_url}")
        
    except Exception as e:
        logger.error(f"Error creating Notion task: {str(e)}")
        await update.message.reply_text(
            f"❌ Error creating task: {str(e)}",
            reply_markup=ReplyKeyboardRemove()
        )
    
    return ConversationHandler.END

# Calendar event creation conversation handlers
async def calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the calendar event creation conversation."""
    await update.message.reply_text(
        "Let's create a calendar event! Please enter the event name:"
    )
    return EVENT_NAME

async def event_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the event name input."""
    context.user_data['event_name'] = update.message.text
    
    # Create a custom keyboard for date selection
    keyboard = [
        ["Today", "Tomorrow"],
        ["Next Week", "Custom Date"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    await update.message.reply_text(
        "When would you like to schedule the event?",
        reply_markup=reply_markup
    )
    return EVENT_DATE

async def event_date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the event date input."""
    date_text = update.message.text
    today = datetime.now()
    
    if date_text == "Today":
        event_date = today
    elif date_text == "Tomorrow":
        event_date = today + timedelta(days=1)
    elif date_text == "Next Week":
        event_date = today + timedelta(days=7)
    else:
        # Handle custom date input
        try:
            event_date = datetime.strptime(date_text, "%Y-%m-%d")
        except ValueError:
            await update.message.reply_text(
                "Please enter the date in YYYY-MM-DD format:"
            )
            return EVENT_DATE
    
    context.user_data['event_date'] = event_date
    
    # Create a custom keyboard for time selection
    keyboard = [
        ["9:00 AM", "10:00 AM", "11:00 AM"],
        ["12:00 PM", "1:00 PM", "2:00 PM"],
        ["3:00 PM", "4:00 PM", "5:00 PM"],
        ["Custom Time"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    await update.message.reply_text(
        "What time would you like to schedule the event?",
        reply_markup=reply_markup
    )
    return EVENT_TIME

async def event_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the event time input."""
    time_text = update.message.text
    
    if time_text == "Custom Time":
        await update.message.reply_text(
            "Please enter the time in HH:MM format (24-hour):"
        )
        return EVENT_TIME
    
    try:
        event_time = datetime.strptime(time_text, "%I:%M %p").time()
        context.user_data['event_time'] = event_time
        
        # Create a custom keyboard for duration selection
        keyboard = [
            ["15 minutes", "30 minutes", "1 hour"],
            ["2 hours", "Custom duration"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await update.message.reply_text(
            "How long should the event be?",
            reply_markup=reply_markup
        )
        return EVENT_DURATION
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid time in HH:MM format (24-hour):"
        )
        return EVENT_TIME

async def event_duration_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the event duration input."""
    duration_text = update.message.text
    
    # Convert duration text to minutes
    if duration_text == "15 minutes":
        duration_minutes = 15
    elif duration_text == "30 minutes":
        duration_minutes = 30
    elif duration_text == "1 hour":
        duration_minutes = 60
    elif duration_text == "2 hours":
        duration_minutes = 120
    elif duration_text == "Custom duration":
        await update.message.reply_text(
            "Please enter the duration in minutes:"
        )
        return EVENT_DURATION
    else:
        try:
            duration_minutes = int(duration_text)
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid number of minutes:"
            )
            return EVENT_DURATION
    
    context.user_data['duration_minutes'] = duration_minutes
    
    await update.message.reply_text(
        "Would you like to add attendees? (Optional)\n"
        "Enter email addresses separated by commas, or type 'skip' to continue without attendees:"
    )
    return EVENT_ATTENDEES

async def event_attendees_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the event attendees input and create the calendar event."""
    attendees_text = update.message.text
    
    # Get event details from context
    event_name = context.user_data['event_name']
    event_date = context.user_data['event_date']
    event_time = context.user_data['event_time']
    duration_minutes = context.user_data['duration_minutes']
    
    # Combine date and time
    event_start = datetime.combine(event_date.date(), event_time)
    event_end = event_start + timedelta(minutes=duration_minutes)
    
    # Process attendees - we'll just store them for information purposes
    attendees = []
    if attendees_text.lower() != 'skip':
        attendees = [email.strip() for email in attendees_text.split(',')]
    
    # Create the calendar event
    try:
        service = get_google_calendar_service()
        event = {
            'summary': event_name,
            'description': 'Event created via Telegram bot',
            'start': {
                'dateTime': event_start.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': event_end.isoformat(),
                'timeZone': 'UTC',
            },
            'colorId': '1',  # Telegram blue color
        }
        
        # We're not adding attendees to the event at all to avoid the 403 error
        
        event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()
        
        # Create a message about attendees
        attendee_message = ""
        if attendees:
            attendee_message = (
                f"\n\n👥 Attendees to invite manually: {', '.join(attendees)}\n"
                f"⚠️ Due to service account limitations, you'll need to manually share the event link with these attendees."
            )
        
        await update.message.reply_text(
            f"✅ Event created successfully!\n\n"
            f"📅 Event: {event_name}\n"
            f"🕒 Time: {event_start.strftime('%Y-%m-%d %H:%M')}\n"
            f"⏱ Duration: {duration_minutes} minutes\n"
            f"🔗 Event link: {event.get('htmlLink')}{attendee_message}",
            reply_markup=ReplyKeyboardRemove()
        )
        logger.info(f"Calendar event created: {event.get('htmlLink')}")
    except Exception as e:
        logger.error(f"Error creating calendar event: {str(e)}")
        await update.message.reply_text(
            f"❌ Error creating event: {str(e)}",
            reply_markup=ReplyKeyboardRemove()
        )
    
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages."""
    try:
        # Get the message text
        text = update.message.text
        
        # Process the text message
        await process_text_message(update, context, text)
        
    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        await update.message.reply_text(
            "Sorry, I couldn't process your message. Please try using /task or /calendar commands instead."
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_message = "🔍 Integration Status:\n\n"
    
    # Check Notion
    if NOTION_TOKEN and NOTION_DATABASE_ID:
        try:
            url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
            response = requests.get(url, headers=NOTION_HEADERS)
            if response.status_code == 200:
                status_message += "✅ Notion: Connected\n"
            else:
                status_message += f"❌ Notion: Error (Status code: {response.status_code})\n"
        except Exception as e:
            status_message += f"❌ Notion: Error ({str(e)})\n"
    else:
        status_message += "❌ Notion: Not configured\n"
    
    # Check Google Calendar
    try:
        service = get_google_calendar_service()
        if service:
            # Try to list calendars as a test
            calendar_list = service.calendarList().list().execute()
            status_message += "✅ Google Calendar: Connected\n"
        else:
            status_message += "❌ Google Calendar: Failed to connect\n"
    except Exception as e:
        status_message += f"❌ Google Calendar: Error ({str(e)})\n"
    
    await update.message.reply_text(status_message)

# Voice note processing functions
async def download_voice_note(file_id, context):
    """Download voice note from Telegram."""
    file = await context.bot.get_file(file_id)
    file_content = await file.download_as_bytearray()
    return file_content

async def convert_audio_to_wav(audio_data):
    """Convert audio data to WAV format using ffmpeg"""
    with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as input_file:
        input_file.write(audio_data)
        input_path = input_file.name

    output_path = input_path.replace('.ogg', '.wav')

    try:
        # Convert audio using ffmpeg
        subprocess.run([
            'ffmpeg',
            '-i', input_path,
            '-acodec', 'pcm_s16le',
            '-ac', '1',
            '-ar', '16k',
            '-y',  # Overwrite output file if it exists
            output_path
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr.decode()}")
        raise
    finally:
        # Clean up input file
        os.unlink(input_path)

    return output_path

async def transcribe_voice_note(audio_data):
    """Transcribe voice note using Vosk."""
    try:
        # Convert audio to WAV format
        wav_path = await convert_audio_to_wav(audio_data)
        
        # Check if model exists, if not, return an error message
        model_path = os.path.join("models", "vosk-model-small-en-us-0.15")
        if not os.path.exists(model_path):
            logger.error(f"Vosk model not found at {model_path}")
            return "Error: Speech recognition model not available. Please contact the administrator."
        
        # Open the WAV file
        wf = wave.open(wav_path, "rb")
        
        # Create recognizer with timeout
        try:
            model = Model(model_path)
            rec = KaldiRecognizer(model, wf.getframerate())
            rec.SetWords(True)
        except Exception as e:
            logger.error(f"Error initializing Vosk model: {str(e)}")
            return f"Error initializing speech recognition: {str(e)}"
        
        # Process audio
        results = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                part = json.loads(rec.Result())
                results.append(part.get("text", ""))
        
        # Get final result
        part = json.loads(rec.FinalResult())
        results.append(part.get("text", ""))
        
        # Clean up
        wf.close()
        os.unlink(wav_path)
        
        # Combine all results
        text = " ".join(filter(None, results))
        return text.strip()
        
    except Exception as e:
        logger.error(f"Error transcribing voice note: {str(e)}")
        return f"Error transcribing voice note: {str(e)}"

def parse_event_details(text):
    """Parse event details from transcribed text using NLTK and regex."""
    # Tokenize and tag parts of speech
    tokens = word_tokenize(text.lower())
    tagged = pos_tag(tokens)
    
    # Initialize event details
    event_details = {
        'title': '',
        'datetime': None,
        'duration': 30,  # Default duration in minutes
        'attendees': []
    }
    
    # Extract date and time using dateutil
    try:
        # Look for time expressions in the text
        time_pattern = r'\b(tomorrow|today|next week|next month)\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b'
        time_matches = re.finditer(time_pattern, text.lower())
        
        for match in time_matches:
            try:
                parsed_date = date_parser.parse(match.group(), fuzzy=True)
                if parsed_date:
                    event_details['datetime'] = parsed_date
                    break
            except:
                continue
    except:
        pass
    
    # Extract email addresses for attendees
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    event_details['attendees'] = re.findall(email_pattern, text)
    
    # Extract duration if specified
    duration_pattern = r'(\d+)\s*(hour|minute|min|hr)'
    duration_match = re.search(duration_pattern, text.lower())
    if duration_match:
        amount = int(duration_match.group(1))
        unit = duration_match.group(2)
        if unit in ['hour', 'hr']:
            event_details['duration'] = amount * 60
        else:
            event_details['duration'] = amount
    
    # Extract event title
    # Remove time expressions and email addresses from text
    title_text = re.sub(time_pattern, '', text.lower())
    title_text = re.sub(email_pattern, '', title_text)
    title_text = re.sub(r'\b(for|at|on|to)\b', '', title_text)
    title_text = ' '.join(title_text.split())
    
    event_details['title'] = title_text.strip()
    
    return event_details

async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Process text from voice notes or direct messages."""
    try:
        # Log the text
        logger.info(f"Processing text: {text}")
        
        # Parse event details
        event_details = parse_event_details(text)
        
        if not event_details['datetime']:
            await update.message.reply_text(
                "I couldn't determine when the event should be scheduled.\n"
                "Please use /task or /calendar to create an event with specific date and time."
            )
            return
        
        if not event_details['title']:
            await update.message.reply_text(
                "I couldn't determine what the event is about.\n"
                "Please use /task or /calendar to create an event with a specific title."
            )
            return
        
        # Create calendar event
        service = get_google_calendar_service()
        event = {
            'summary': event_details['title'],
            'description': 'Event created via voice note',
            'start': {
                'dateTime': event_details['datetime'].isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': (event_details['datetime'] + timedelta(minutes=event_details['duration'])).isoformat(),
                'timeZone': 'UTC',
            },
        }
        
        # Add attendees if any
        if event_details['attendees']:
            event['attendees'] = [{'email': email} for email in event_details['attendees']]
        
        # Insert event
        event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()
        
        # Create response message
        attendee_message = ""
        if event_details['attendees']:
            attendee_message = f"\n👥 Attendees: {', '.join(event_details['attendees'])}"
        
        await update.message.reply_text(
            f"✅ Event created successfully!\n\n"
            f"📅 Event: {event_details['title']}\n"
            f"🕒 Time: {event_details['datetime'].strftime('%Y-%m-%d %H:%M')}\n"
            f"⏱ Duration: {event_details['duration']} minutes{attendee_message}\n"
            f"🔗 Event link: {event.get('htmlLink')}"
        )
        
    except Exception as e:
        logger.error(f"Error processing text message: {str(e)}")
        await update.message.reply_text(
            "Sorry, I couldn't process your request. Please try using /task or /calendar commands instead."
        )

async def handle_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice notes by transcribing them and processing the text."""
    try:
        # Get the voice note file
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        
        # Download the voice note
        audio_data = await file.download_as_bytearray()
        
        # Send a processing message
        processing_message = await update.message.reply_text("Processing your voice note...")
        
        try:
            # Transcribe voice note
            transcribed_text = await transcribe_voice_note(audio_data)
            
            # Check if we got an error message
            if transcribed_text.startswith("Error") or transcribed_text.startswith("Could not"):
                await processing_message.edit_text(transcribed_text)
                return
            
            # Process the transcribed text
            await process_text_message(update, context, transcribed_text)
            
            # Delete the processing message
            await processing_message.delete()
            
        except Exception as e:
            logger.error(f"Error processing voice note: {str(e)}")
            await processing_message.edit_text("Sorry, I couldn't process your voice note. Please try typing your request instead.")
            
    except Exception as e:
        logger.error(f"Error in handle_voice_note: {str(e)}")
        await update.message.reply_text("Sorry, I couldn't process your voice note. Please try typing your request instead.")

def check_environment_variables():
    """Check if all required environment variables are set"""
    required_vars = {
        "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN"),
        "NOTION_TOKEN": os.getenv("NOTION_TOKEN"),
        "NOTION_DATABASE_ID": os.getenv("NOTION_DATABASE_ID"),
        "GOOGLE_CREDENTIALS_FILE": os.getenv("GOOGLE_CREDENTIALS_FILE")
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    
    if missing_vars:
        logger.warning(f"Missing environment variables: {', '.join(missing_vars)}")
        return False
    
    logger.info("All required environment variables are set")
    return True

def main():
    """Start the bot."""
    try:
        # Check environment variables
        check_environment_variables()
        
        # Ensure Vosk model is downloaded
        try:
            from download_vosk import download_vosk_model
            model_path = download_vosk_model()
            logger.info(f"Vosk model path: {model_path}")
        except Exception as e:
            logger.warning(f"Could not download Vosk model: {str(e)}")
            logger.warning("Voice note transcription will not be available.")
        
        # Get token from environment
        token = os.getenv("TELEGRAM_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_TOKEN not found in environment variables")
        
        # Initialize bot with proper configuration
        application = Application.builder().token(token).build()
        
        # Add conversation handler for task creation
        task_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('task', task_command)],
            states={
                TASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_name_handler)],
                TASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_date_handler)],
                TASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_time_handler)],
                TASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_duration_handler)],
                TASK_ATTENDEES: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_attendees_handler)],
            },
            fallbacks=[],
        )
        
        # Add conversation handler for calendar event creation
        calendar_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('calendar', calendar_command)],
            states={
                EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_name_handler)],
                EVENT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_date_handler)],
                EVENT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_time_handler)],
                EVENT_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_duration_handler)],
                EVENT_ATTENDEES: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_attendees_handler)],
            },
            fallbacks=[],
        )
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(task_conv_handler)
        application.add_handler(calendar_conv_handler)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Add voice note handler
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_note))
        
        # Start the bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        raise

if __name__ == "__main__":
    main() 