import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import random
from discord import app_commands
from discord.ui import View, Button

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
processing_queue = {}  # Fila assíncrona para processar playlists em background

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
    'options': '-vn -af "loudnorm"',
}

# Configuração do Spotify
client_id = 'SPOTIFY_CLIENT_ID'
client_secret = 'SPOTIFY_CLIENT_SECRET'
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

# Função de processamento em background
async def background_processor(guild_id):
    while True:
        if guild_id not in processing_queue:
            await asyncio.sleep(1)
            continue

        try:
            task = await processing_queue[guild_id].get()
            track = task['track']
            ctx = task['ctx']

            nome_musica = track['name']
            artista = track['artists'][0]['name']
            album = track['album']['name']
            duracao = track['duration_ms'] / 1000

            video_url = await asyncio.to_thread(obter_url_youtube, nome_musica, artista, album, duracao)
            if video_url:
                queue[guild_id].append((video_url, nome_musica))
                voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
                if voice_client and not voice_client.is_playing():
                    await play_next_song(ctx)

        except Exception as e:
            print(f"Erro no processamento da fila: {e}")

        await asyncio.sleep(0)

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
    guild_id = ctx.guild.id
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if guild_id in queue and queue[guild_id]:
        url, title = queue[guild_id].pop(0)

        # Baixa informações do YouTube para obter o link de áudio
        with youtube_dl.YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info['url']  # Obtém o link do áudio real

        def after_playback(error):
            if error:
                print(f"Erro ao tocar música: {error}")
            asyncio.run_coroutine_threadsafe(play_next_song(ctx), bot.loop)

        # Toca a música com FFmpeg
        voice_client.play(discord.FFmpegPCMAudio(audio_url, **ffmpeg_opts), after=after_playback)

        # Mensagem no chat
        await ctx.send(f'Tocando agora: {title}')

    else:
        await ctx.send("Fila vazia, saindo do canal.")
        await voice_client.disconnect()

    bot.loop.create_task(check_voice_channel(ctx))

# Comando para sair do canal de voz
@bot.command()
async def leave(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client:
        await voice_client.disconnect()
        await ctx.send("Sai do canal de voz.")
    else:
        await ctx.send("Não estou em um canal de voz.")

#Comando para embaralhar a lista
@bot.command()
async def shuffle(ctx):
    if ctx.guild.id in queue and len (queue[ctx.guild.id]) > 1:
        random.shuffle(queue[ctx.guild.id])
        await ctx.send ("Fila embaralhada")

    else: 
        await ctx.send ("Fila vazia")

@bot.command()
async def tracklist(ctx):
    guild_id = ctx.guild.id

    # Verifica se há uma fila para o servidor e se ela não está vazia
    if guild_id not in queue or not queue[guild_id]:
        await ctx.send("A fila está vazia.")
        return

    # Extrai apenas os títulos das músicas da fila
    fila = [title for _, title in queue[guild_id]]
    
    # Define o número de músicas por página 
    por_pagina = 10
    paginas = [fila[i:i+por_pagina] for i in range(0, len(fila), por_pagina)]

    # Classe que define os botões e o comportamento da paginação
    class Paginador(View):
        def __init__(self):
            super().__init__(timeout=60)  
            self.pagina_atual = 0 

        # Atualiza a mensagem com o conteúdo da página atual
        async def update(self, interaction):
            conteudo = "\n".join(
                f"{i + 1 + self.pagina_atual * por_pagina}. {musica}" 
                for i, musica in enumerate(paginas[self.pagina_atual])
            )
            embed = discord.Embed(
                title=f"Fila atual (Página {self.pagina_atual + 1}/{len(paginas)})",
                description=conteudo,
                color=discord.Color.blurple()
            )
            # Edita a mensagem original com nova mensagem e mantém os botões
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="⬅️ Anterior", style=discord.ButtonStyle.secondary)
        async def anterior(self, interaction: discord.Interaction, button: Button):
            if self.pagina_atual > 0:
                self.pagina_atual -= 1
                await self.update(interaction)

        @discord.ui.button(label="Próxima ➡️", style=discord.ButtonStyle.secondary)
        async def proxima(self, interaction: discord.Interaction, button: Button):
            if self.pagina_atual + 1 < len(paginas):
                self.pagina_atual += 1
                await self.update(interaction)

        # Desativa os botões 
        async def on_timeout(self):
            for item in self.children:
                item.disabled = True

    # Cria mensagem incial
    view = Paginador()
    conteudo = "\n".join(f"{i + 1}. {musica}" for i, musica in enumerate(paginas[0]))
    embed = discord.Embed(
        title=f"Fila atual (Página 1/{len(paginas)})",
        description=conteudo,
        color=discord.Color.blurple()
    )

    await ctx.send(embed=embed, view=view)


#Comando para tocar uma playlist
@bot.command()
async def playlist(ctx, url: str):
    try:
        guild_id = ctx.guild.id
        if guild_id not in queue:
            queue[guild_id] = []

        if guild_id not in processing_queue:
            processing_queue[guild_id] = asyncio.Queue()
            asyncio.create_task(background_processor(guild_id))

        if "spotify.com/playlist" in url:
            playlist_id = url.split('/')[-1].split('?')[0]
            playlist = sp.playlist(playlist_id)
            tracks = playlist['tracks']['items'][:50]

            for item in tracks:
                await processing_queue[guild_id].put({'track': item['track'], 'ctx': ctx})

            await ctx.send(f"Playlist adicionada à fila! {len(tracks)}")

        else:
            await ctx.send("Forneça um link válido de playlist do Spotify.")
            return

        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if voice_client is None:
            if ctx.author.voice and ctx.author.voice.channel:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("Você precisa estar em um canal de voz.")
                return

    except Exception as e:
        await ctx.send(f'Erro ao adicionar playlist: {str(e)}')

#Comando para tocar a proxima musica
@bot.command()
async def next(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if voice_client and voice_client.is_playing():
        voice_client.stop()  # Para a música atual, chamando after_playback automaticamente
        await ctx.send("Tocando a próxima...")
    else:
        await ctx.send("Não há nenhuma música tocando no momento.")

#Funcao para auto desconectar
async def check_voice_channel(ctx):
    await asyncio.sleep(300)  # Espera 30 segundos antes de verificar
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if voice_client and len(voice_client.channel.members) == 1:  # Apenas o bot no canal
        await voice_client.disconnect()
        await ctx.send("Nenhum usuário no canal de voz. Desconectando...")   

music_commands = """
*Comandos do Bot de Música*
```!play <url> - Toca uma música  
!playlist <url> - Toca uma playlist 
!shuffle - Embaralha a fila de musica 
!tracklist - Mostra a fila de musica 
!leave - O bot sai do canal de voz ```
"""

@bot.event
async def on_message(message):
    # Verifica se a mensagem é apenas "!"
    if message.content.strip() == "!":
        await message.channel.send(music_commands)

    # Para permitir que outros comandos do bot funcionem
    await bot.process_commands(message)

# Iniciar o bot
bot.run(token)



