from pyrogram import Client
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
import json
import subprocess
import ffmpeg
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped, AudioVideoPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio, MediumQualityVideo
from pytgcalls.types.stream import StreamAudioEnded

load_dotenv()

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API Setup ---
# Spotify API
SPOTIFY_CLIENT_ID = "95f4f5c6df5744698035a0948e801ad9"
SPOTIFY_CLIENT_SECRET = "4b03167b38c943c3857333b3f5ea95ea"
spotify_credentials_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
sp = spotipy.Spotify(client_credentials_manager=spotify_credentials_manager)

# Telegram Bot API
BOT_TOKEN = "7741293072:AAEiWZSyFz1V39uQYbHEk10BTUoPYiUxyS4"
updater = Updater(BOT_TOKEN)
dispatcher = updater.dispatcher

# Telegram User Client
API_ID = 24620300
API_HASH = "9a098f01aa56c836f2e34aee4b7ef963"
SESSION = "BQGC-ccAWwiLhsvQpd7jdiZmReOM8zqPb-Ra9Je4THqbS0mq6jYnFQS-K9LDpz-YHqQUMsLOuLqgHdD1edUMQmQhPyjF38VcurIT2b4LYZVeFSzfjXoUKwOUsGIFzlvfo6bUrzM7ouhcP86quH4IR2LfueSXWJdDnvu8qS3Gm5-d7W2M13vebJ5NfEymsUAJW6zjR9IusQ8f5Nei7UzUZsl1ww6cI8T_gcu6wiSP1LfWjOVQ97G6ab3-2jxJ-nPlA3cGi8q5dHhIB81LRZymSq03oSXEMJihIOXPfj2pI0XGlI-Y85nC60hSwXuV5Y02_VmAZ_j157Co39b2r77gjfXzvfMcjgAAAAG0-mQtAA"
pytgcalls = PyTgCalls(
          Client(
        "assistant",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=SESSION,
       ))


# --- Download Logic ---
async def download_file(url: str, update: Update, context: CallbackContext) -> BytesIO:
    """Asynchronously downloads a file from a URL and returns it as BytesIO"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded_size = 0

                with BytesIO() as buffer:
                    async for chunk in response.content.iter_chunked(1024):
                        buffer.write(chunk)
                        downloaded_size += len(chunk)
                        progress = downloaded_size / total_size if total_size > 0 else 1
                        progress_percent = int(progress * 100)

                        await context.bot.edit_message_text(
                            chat_id=update.callback_query.message.chat.id,
                            message_id=update.callback_query.message.message_id,
                            text=f"Downloading... {progress_percent}%"
                        )
                    return buffer
    except Exception as e:
        logger.error(f"Error downloading file from {url}: {e}")
        await context.bot.edit_message_text(
                            chat_id=update.callback_query.message.chat.id,
                            message_id=update.callback_query.message.message_id,
                            text="Download failed"
                        )
        return None

def convert_to_pcm(audio_file: BytesIO) -> BytesIO:
  """Converts an audio file to raw PCM using ffmpeg"""
  try:
    process = (
      ffmpeg
      .input("pipe:", format="mp4" if "mp4" in str(audio_file) else "mp3")
      .output("pipe:", format="s16le", acodec="pcm_s16le", ac=2, ar=48000)
      .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
    )
    output, errors = process.communicate(input=audio_file.getvalue())
    if errors:
        logger.error(f"FFmpeg Error : {errors.decode()}")
        return None
    return BytesIO(output)
  except Exception as e:
    logger.error(f"FFmpeg Conversion Error: {e}")
    return None


async def stream_audio(chat_id: int, audio_file: BytesIO):
    """Streams audio into a Telegram voice chat"""
    try:
      pcm_audio = convert_to_pcm(audio_file)
      if not pcm_audio:
        return
      await pytgcalls.join_group_call(
          chat_id,
          InputAudioStream(
              pcm_audio,
            ),
          )
    except Exception as e:
        logger.error(f"Error streaming audio: {e}")


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
          track_name = item.get['title']
          artist_name = item.get['more_info']['singers']
          button_text = f"{counter}. (JioSaavn) {track_name} - {artist_name}"
          keyboard.append([InlineKeyboardButton(button_text, callback_data=f"jiosaavn_{counter-1}")])
          counter += 1

    if spotify_results:
      for item in spotify_results:
        track_name = item['name']
        artist_name = item['artists'][0]['name']
        button_text = f"{counter}. (Spotify) {track_name} - {artist_name}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"spotify_{counter-1}")])
        counter += 1

    if not keyboard:
        update.message.reply_text("No results found.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Search Results:", reply_markup=reply_markup)


# --- Playback Logic ---
async def play_track_jiosaavn(update: Update, context: CallbackContext, track_item, chat_id: int):
    try:
        audio_url = track_item['more_info']['vlink']
        if not audio_url:
            await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Could not play track.")
            return
        await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Downloading song...")
        audio_file = await download_file(audio_url, update, context)
        if not audio_file:
            await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Download failed")
            return
        audio_file.seek(0)
        await stream_audio(chat_id, audio_file)
    except Exception as e:
        logger.error(f"Error playing JioSaavn track: {e}")
        await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Could not play track.")


async def play_track_spotify(update: Update, context: CallbackContext, track_item, chat_id: int):
    try:
      audio_url = track_item['preview_url']
      if not audio_url:
            await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Could not play track.")
            return
      await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Downloading song...")
      audio_file = await download_file(audio_url, update, context)
      if not audio_file:
            await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Download failed")
            return
      audio_file.seek(0)
      await stream_audio(chat_id, audio_file)
    except Exception as e:
        logger.error(f"Error playing Spotify track: {e}")
        await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text="Could not play track.")

# --- Callback Query Handler ---
async def handle_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    chat_id = update.callback_query.message.chat.id

    if data.startswith("jiosaavn_"):
        index = int(data.split("_")[1])
        track = context.user_data['current_search']['jiosaavn'][index]
        await play_track_jiosaavn(update, context, track, chat_id)

    elif data.startswith("spotify_"):
        index = int(data.split("_")[1])
        track = context.user_data['current_search']['spotify'][index]
        await play_track_spotify(update, context, track, chat_id)

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
              await play_track_jiosaavn(update, context, current_track['track'], chat_id)
            elif current_track['source'] == "spotify":
              await play_track_spotify(update, context, current_track['track'], chat_id)
    update.message.reply_text("Queue finished.")


async def stop_stream(update: Update, context: CallbackContext):
        chat_id = update.message.chat.id
        try:
           await pytgcalls.leave_group_call(chat_id)
           update.message.reply_text("Stopped current stream.")
        except Exception as e:
          update.message.reply_text("Could not stop the stream.")
          logger.error(f"Error stopping the stream: {e}")



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

async def stream_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat.id
    await pytgcalls.join_group_call(chat_id, AudioQuality.HIGH)
    update.message.reply_text("Started streaming.")

async def stopstream_command(update: Update, context: CallbackContext):
  await stop_stream(update, context)

# --- Dispatcher and Bot Start ---
dispatcher.add_handler(CommandHandler('search', search_command))
dispatcher.add_handler(CommandHandler('queue', queue_command))
dispatcher.add_handler(CommandHandler('playqueue', playqueue_command))
dispatcher.add_handler(CommandHandler('stream', stream_command))
dispatcher.add_handler(CommandHandler('stopstream', stopstream_command))
dispatcher.add_handler(CallbackQueryHandler(handle_callback_query))

async def start_bot():
    await pytgcalls.start()
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    asyncio.run(start_bot())
