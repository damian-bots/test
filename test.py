import os
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from telegram.ext import Updater, CommandHandler

# Set up Spotify API credentials
client_id = '95f4f5c6df5744698035a0948e801ad9'
client_secret = '4b03167b38c943c3857333b3f5ea95ea'

# Set up the Spotipy client
client_credentials_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = Spotify(client_credentials_manager=client_credentials_manager)

# Function to search for songs on Spotify
def search_song(update, context):
    query = ' '.join(context.args)
    if query:
        results = sp.search(query, limit=1, type='track')
        if results['tracks']['items']:
            track = results['tracks']['items'][0]
            track_name = track['name']
            artist_name = track['artists'][0]['name']
            track_url = track['external_urls']['spotify']
            
            message = f"Song: {track_name}\nArtist: {artist_name}\nLink: {track_url}"
        else:
            message = "Sorry, no results found!"
    else:
        message = "Please provide a song name or artist."
    
    update.message.reply_text(message)

# Set up the Telegram bot
def main():
    # Your bot's token
    TELEGRAM_TOKEN = '7741293072:AAEiWZSyFz1V39uQYbHEk10BTUoPYiUxyS4'
    
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Add the search command handler
    dp.add_handler(CommandHandler("search", search_song))

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
