
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, filters
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import requests
import os
import time
import uuid
import logging
from dotenv import load_dotenv
import asyncio
import aiohttp
from io import BytesIO

load_dotenv()

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API Setup ---
# Spotify API
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
spotify_credentials_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
sp = spotipy.Spotify(client_credentials_manager=spotify_credentials_manager)

# Telegram Bot API
BOT_TOKEN = os.getenv("BOT_TOKEN")
updater = Updater(BOT_TOKEN)
dispatcher = updater.dispatcher

# --- Download Logic ---
async def download_file(url: str) -> BytesIO:
  """Asynchronously downloads a file from a URL and returns it as BytesIO"""
  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(url) as response:
        response.raise_for_status()
        content = await response.read()
        return BytesIO(content)
    except Exception as e:
      logger.error(f"Error downloading file from {url}: {e}")
      return None

# --- Search Logic ---
def jiosaavn_search(query):
    try:
        url = f"https://www.jiosaavn.com/api.php?_format=json&__call=search.getResults&q={query}&p=1&n=5&_marker=0"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except requests.exceptions.RequestException as e:
        logger.error(f"Error searching JioSaavn: {e}")
        time.sleep(1)
        return None
    except json.JSONDecodeError as e:
      logger.error(f"Error decoding JSON from JioSaavn: {e}")
      return None


def spotify_search(query):
    try:
        results = sp.search(q=query, type="track", limit=5)
        if not results['tracks']['items']:
            return None
        return results['tracks']['items']
    except spotipy.exceptions.SpotifyException as e:
      logger.error(f"Error searching Spotify: {e}")
      time.sleep(1)
      return None


def send_search_results(update: Update, context: CallbackContext, jiosaavn_results, spotify_results):
    keyboard = []
    counter = 1

    if jiosaavn_results:
      for item in jiosaavn_results:
          track_name = item['title']
          artist_name = item['more_info']['singers']
          button_text = f"{counter}. (JioSaavn) {track_name} - {artist_name}"
          keyboard.append([InlineKeyboardButton(button_text, callback_data=f"jiosaavn_{counter-1}"))
          counter += 1

    if spotify_results:
      for item in spotify_results:
        track_name = item['name']
        artist_name = item['artists'][0]['name']
        button_text = f"{counter}. (Spotify) {track_name} - {artist_name}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"spotify_{counter-1}"))
        counter += 1

    if not keyboard:
        update.message.reply_text("No results found.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Search Results:", reply_markup=reply_markup)

# --- Playback Logic ---
async def play_track_jiosaavn(update: Update, context: CallbackContext, track_item):
    try:
        audio_url = track_item['more_info']['vlink']
        if not audio_url:
            update.callback_query.message.reply_text("Could not play track")
            return
        update.callback_query.message.reply_text("Downloading song...")
        audio_file = await download_file(audio_url)
        if not audio_file:
            update.callback_query.message.reply_text("Could not download song.")
            return
        audio_file.seek(0)
        await context.bot.send_audio(
            chat_id=update.callback_query.message.chat.id,
            audio=audio_file,
            title=track_item['title'],
            performer=track_item['more_info']['singers']
        )
    except Exception as e:
        logger.error(f"Error playing JioSaavn track: {e}")
        update.callback_query.message.reply_text("Could not play track")


async def play_track_spotify(update: Update, context: CallbackContext, track_item):
    try:
      audio_url = track_item['preview_url']
      if not audio_url:
        update.callback_query.message.reply_text("Could not play track")
        return
      update.callback_query.message.reply_text("Downloading song...")
      audio_file = await download_file(audio_url)
      if not audio_file:
            update.callback_query.message.reply_text("Could not download song")
            return
      audio_file.seek(0)
      await context.bot.send_audio(
            chat_id=update.callback_query.message.chat.id,
            audio=audio_file,
            title=track_item['name'],
            performer=track_item['artists'][0]['name']
            )
    except Exception as e:
        logger.error(f"Error playing Spotify track: {e}")
        update.callback_query.message.reply_text("Could not play track")

# --- Callback Query Handler ---
async def handle_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data

    if data.startswith("jiosaavn_"):
        index = int(data.split("_")[1])
        track = context.user_data['current_search']['jiosaavn'][index]
        await play_track_jiosaavn(update, context, track)

    elif data.startswith("spotify_"):
        index = int(data.split("_")[1])
        track = context.user_data['current_search']['spotify'][index]
        await play_track_spotify(update, context, track)

# --- Queue Logic ---
def add_to_queue(update: Update, context: CallbackContext, track_data, source):
  chat_id = update.message.chat.id
  if 'queue' not in context.user_data:
      context.user_data['queue'] = {}
  if chat_id not in context.user_data['queue']:
      context.user_data['queue'][chat_id] = []
  context.user_data['queue'][chat_id].append({"track": track_data, "source" : source})
  update.message.reply_text("Track added to queue")

async def play_queue(update: Update, context: CallbackContext):
  chat_id = update.message.chat.id
  if 'queue' not in context.user_data or chat_id not in context.user_data['queue'] or not context.user_data['queue'][chat_id]:
        update.message.reply_text("The queue is empty")
        return
  queue = context.user_data['queue'][chat_id]
  while queue:
        current_track = queue.pop(0)
        if current_track['source'] == "jiosaavn":
          await play_track_jiosaavn(update, context, current_track['track'])
        elif current_track['source'] == "spotify":
          await play_track_spotify(update, context, current_track['track'])


# --- Command Handler ---
def search_command(update: Update, context: CallbackContext):
    query = " ".join(context.args)
    if not query:
        update.message.reply_text("Please enter a song name to search")
        return
    jiosaavn_results = jiosaavn_search(query)
    spotify_results = spotify_search(query)

    if jiosaavn_results or spotify_results:
      context.user_data['current_search'] = { "jiosaavn" : jiosaavn_results, "spotify" : spotify_results}
      send_search_results(update, context, jiosaavn_results, spotify_results)
    else:
      update.message.reply_text("No results found.")

async def queue_command(update: Update, context: CallbackContext):
    query = " ".join(context.args)
    if not query:
        update.message.reply_text("Please enter a song name to search and add to queue")
        return
    jiosaavn_results = jiosaavn_search(query)
    spotify_results = spotify_search(query)
    if jiosaavn_results:
      add_to_queue(update, context, jiosaavn_results[0], "jiosaavn")
    elif spotify_results:
      add_to_queue(update, context, spotify_results[0], "spotify")
    else:
        update.message.reply_text("No results found.")

async def playqueue_command(update: Update, context: CallbackContext):
    await play_queue(update, context)



# --- Dispatcher and Bot Start ---
dispatcher.add_handler(CommandHandler('search', search_command))
dispatcher.add_handler(CommandHandler('queue', queue_command))
dispatcher.add_handler(CommandHandler('playqueue', playqueue_command))
dispatcher.add_handler(CallbackQueryHandler(handle_callback_query))

updater.start_polling()
updater.idle()
