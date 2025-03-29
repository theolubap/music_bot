import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re

# Carregar variáveis de ambiente
load_dotenv()
token = os.getenv("DISCORD_TOKEN")

if token is None:
    print("Erro: DISCORD_TOKEN não encontrado. Verifique seu arquivo .env.")
    exit(1)

# Configuração do bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

queue = {}

# Configurações de extração de URL
ytdl_opts = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioquality': 1,
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'quiet': True,
    'logtostderr': False,
    'source_address': None,
}

ffmpeg_opts = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# Configuração do Spotify
client_id = 'd64c7d5416894e2597bdd9fe9234c737'
client_secret = 'a3ec92ec43fd4984a87ebe5c53323666'
client_credentials_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# Função para obter a URL do YouTube a partir do Spotify
def obter_url_youtube(nome_musica, artista, album, duracao):
    pesquisa = f"{nome_musica} {artista} {album}"
    
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
    }
    
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        resultado = ydl.extract_info(f"ytsearch:{pesquisa}", download=False)
        
        if not resultado or 'entries' not in resultado or len(resultado['entries']) == 0:
            return None
        
        video_id = resultado['entries'][0]['id']
        return f"https://www.youtube.com/watch?v={video_id}"

# Comando play@bot.command()
@bot.command()
async def play(ctx, url: str):
    try:
        # Verifica se é um link do YouTube
        if "youtube.com" in url or "youtu.be" in url:
            video_url = url
        else:
            # Extrair ID da música do Spotify
            track_id = url.split('/')[-1].split('?')[0]
            track = sp.track(track_id)
            nome_musica = track['name']
            artista = track['artists'][0]['name']
            album = track['album']['name']
            duracao = track['duration_ms'] / 1000

            # Buscar vídeo no YouTube
            video_url = obter_url_youtube(nome_musica, artista, album, duracao)
            if not video_url:
                await ctx.send("Nenhum vídeo correspondente encontrado no YouTube.")
                return

        # Conectar no canal de voz
        channel = ctx.author.voice.channel
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if voice_client is None or voice_client.channel != channel:
            voice_client = await channel.connect()

        # Baixar informações do YouTube
        with youtube_dl.YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            URL = info['url']
            title = info['title']

        # Adicionar à fila
        if ctx.guild.id not in queue:
            queue[ctx.guild.id] = []
        queue[ctx.guild.id].append((URL, title))

        # Se não houver áudio tocando, inicie a reprodução
        if not voice_client.is_playing():
            await play_next_song(ctx)

        await ctx.send(f'Adicionado à fila: {title}')

    except Exception as e:
        await ctx.send(f'Erro: {str(e)}')
        print(f"Erro: {str(e)}")

# Função para tocar a próxima música
async def play_next_song(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if ctx.guild.id in queue and queue[ctx.guild.id]:
        url, title = queue[ctx.guild.id].pop(0)
        
        def after_playback(error):
            fut = asyncio.run_coroutine_threadsafe(play_next_song(ctx), bot.loop)
            try:
                fut.result()
            except Exception as e:
                print(f"Erro ao tocar próxima música: {e}")
        
        voice_client.play(discord.FFmpegPCMAudio(url, **ffmpeg_opts), after=after_playback)
        await ctx.send(f'Tocando agora: {title}')

# Comando para sair do canal de voz
@bot.command()
async def leave(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client:
        await voice_client.disconnect()
        await ctx.send("Sai do canal de voz.")
    else:
        await ctx.send("Não estou em um canal de voz.")

# Iniciar o bot
bot.run(token)



