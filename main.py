import os
import asyncio
import random
import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Cargar las variables de entorno
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("COMMAND_PREFIX", "!")

# Configuración de los Intents necesarios
intents = discord.Intents.default()
intents.message_content = True  # Permite leer el contenido de los mensajes
intents.voice_states = True     # Permite gestionar conexiones a canales de voz

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# Clase de Contexto Personalizada para auto-borrar respuestas
class CleanContext(commands.Context):
    async def send(self, content=None, **kwargs):
        if 'delete_after' not in kwargs:
            kwargs['delete_after'] = 15 # Borrar mensaje del bot en 15 segundos
        return await super().send(content, **kwargs)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    ctx = await bot.get_context(message, cls=CleanContext)
    if ctx.valid:
        await bot.invoke(ctx)

@bot.after_invoke
async def auto_delete_command(ctx):
    try:
        # Borrar el comando del usuario después de 15 segundos
        await ctx.message.delete(delay=15)
    except:
        pass

# Opciones de yt-dlp
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': False,
    'no_warnings': False,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extractor_args': {'youtube': {
        'player_client': ['android', 'ios'],
        'player_skip': ['js'],
    }},
}

# Si hay cookies de YouTube, usarlas (para evitar verificacion de bot en servidores cloud)
_COOKIES_OK = False
if os.path.exists('cookies.txt'):
    print(f"[DIAG] cookies.txt listo, intentando usar...")
    ytdl_format_options['cookiefile'] = 'cookies.txt'
else:
    print("[DIAG] cookies.txt NO existe")

# Escribir cookies desde variable de entorno (HF Secret) si existe
print("[DIAG] Verificando YOUTUBE_COOKIES...")
youtube_cookies = os.getenv('YOUTUBE_COOKIES')
if youtube_cookies:
    try:
        with open('cookies.txt', 'w', encoding='utf-8') as f:
            f.write(youtube_cookies)
        print(f"[DIAG] Cookies de YouTube guardadas ({len(youtube_cookies)} chars, {os.path.getsize('cookies.txt')} bytes)")
    except Exception as e:
        print(f"[DIAG] ERROR al escribir cookies.txt: {e}")
else:
    print("[DIAG] YOUTUBE_COOKIES NO configurado en Secrets")

# Si hay cookies de YouTube, usarlas (para evitar verificacion de bot en servidores cloud)
if os.path.exists('cookies.txt'):
    print(f"[DIAG] cookies.txt listo, se usara en yt-dlp")
    ytdl_format_options['cookiefile'] = 'cookies.txt'
else:
    print("[DIAG] cookies.txt NO existe - YouTube puede pedir verificacion")

# Verificar runtime de JS para el challenge solver
import subprocess as _sp
_ytver = yt_dlp.version.__version__
print(f"[DIAG] yt-dlp version: {_ytver}")
for _js in ['node', 'nodejs']:
    try:
        _r = _sp.run([_js, '--version'], capture_output=True, text=True, timeout=5)
        print(f"[DIAG] {_js}: {_r.stdout.strip()}")
    except Exception:
        pass

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.duration = data.get('duration')

    @classmethod
    async def from_url(cls, search, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        # Buscar en YouTube
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=not stream))

        if 'entries' in data:
            # Si es un resultado de búsqueda, tomamos el primero
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


# Clase para manejar la cola de música en cada Servidor (Guild)
class GuildMusicState:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = []
        self.current = None
        self.voice_client = None

    def play_next(self, error=None):
        if error:
            print(f"[Error en reproductor]: {error}")

        if not self.queue:
            self.current = None
            # Desconexión automática si no hay música en 3 minutos (opcional/removido por simplicidad)
            return

        # Sacar el siguiente elemento
        self.current = self.queue.pop(0)
        
        # Iniciar reproducción
        try:
            self.voice_client.play(
                self.current['source'],
                after=lambda e: self.bot.loop.create_task(self.check_queue_after(e))
            )
            # Enviar mensaje de ahora sonando
            if not self.current.get('hide_embed'):
                channel = self.current['channel']
                embed = discord.Embed(
                    title="🎵 Reproduciendo ahora",
                    description=f"[{self.current['title']}]({self.current['url']})",
                    color=discord.Color.blurple()
                )
                embed.add_field(name="Duración", value=self.format_duration(self.current['duration']))
                embed.set_footer(text=f"Solicitado por {self.current['requester']}")
                asyncio.run_coroutine_threadsafe(channel.send(embed=embed, delete_after=15), self.bot.loop)
        except Exception as ex:
            print(f"[Error al reproducir canción]: {ex}")
            self.play_next()

    async def check_queue_after(self, error):
        # Programar la reproducción de la siguiente canción
        self.play_next(error)

    def format_duration(self, seconds):
        if not seconds:
            return "Desconocido"
        mins, secs = divmod(seconds, 60)
        return f"{mins:02d}:{secs:02d}"


# Diccionario global para los estados de música por Servidor
music_states = {}

def get_music_state(guild_id):
    if guild_id not in music_states:
        music_states[guild_id] = GuildMusicState(bot, guild_id)
    return music_states[guild_id]


@bot.event
async def on_ready():
    print("==================================================")
    print(f" ¡Bot conectado con éxito como {bot.user.name}!")
    print(f" ID del Bot: {bot.user.id}")
    print(f" Prefijo configurado: '{PREFIX}'")
    print("==================================================")
    # Cambiar presencia
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"{PREFIX}help | Música"))


# Comando de ayuda personalizado
@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="🎵 Comandos de Música - Hitoha",
        description="Aquí tienes la lista completa de comandos disponibles para controlar la música en tu servidor.",
        color=discord.Color.from_rgb(46, 204, 113)
    )
    embed.add_field(
        name="🎶 Comandos Básicos",
        value=(
            f"`{PREFIX}join` - Hace que el bot se una a tu canal de voz.\n"
            f"`{PREFIX}play <búsqueda/URL>` - Reproduce música de YouTube o la añade a la cola.\n"
            f"`{PREFIX}leave` - Desconecta al bot del canal de voz."
        ),
        inline=False
    )
    embed.add_field(
        name="🎛️ Control de Reproducción",
        value=(
            f"`{PREFIX}pause` - Pausa la canción actual.\n"
            f"`{PREFIX}resume` - Reanuda la música pausada.\n"
            f"`{PREFIX}skip` - Salta a la siguiente canción en la cola.\n"
            f"`{PREFIX}stop` - Detiene la música y borra toda la cola."
        ),
        inline=False
    )
    embed.add_field(
        name="📋 Cola y Estado",
        value=(
            f"`{PREFIX}queue` (o `cola`) - Muestra la lista de reproducción actual.\n"
            f"`{PREFIX}now` (o `np`) - Muestra la canción que se está reproduciendo ahora."
        ),
        inline=False
    )
    embed.add_field(
        name="🎭 Diversión / Interacción",
        value=(
            f"`{PREFIX}lentes` - Hitoha se ajusta los lentes.\n"
            f"`{PREFIX}esconderse` - Hitoha desaparece en las sombras.\n"
            f"`{PREFIX}say <texto>` - Hitoha repite lo que digas (de mala gana).\n"
            f"`{PREFIX}abrazar @usuario` - Abraza a alguien con un GIF anime.\n"
            f"`{PREFIX}besar @usuario` - Besa a alguien con un GIF anime.\n"
            f"`{PREFIX}golpear @usuario` - Golpea a alguien con un GIF anime.\n"
            f"`{PREFIX}acariciar @usuario` - Acaricia a alguien con un GIF anime."
        ),
        inline=False
    )
    embed.add_field(
        name="🔧 Utilidad",
        value=(
            f"`{PREFIX}ping` - Muestra la latencia del bot.\n"
            f"`{PREFIX}avatar [@usuario]` - Muestra el avatar de un usuario.\n"
            f"`{PREFIX}serverinfo` - Información del servidor.\n"
            f"`{PREFIX}xrp` (o `precio`) - Precio actual de XRP en USD.\n"
            f"`{PREFIX}sfx <efecto>` (o `efecto`) - Reproduce un efecto de sonido.\n"
            f"`{PREFIX}poppy` - Imagen de Hitoha Marui."
        ),
        inline=False
    )
    embed.set_footer(text="Desarrollado con ❤️ para tu servidor.")
    await ctx.send(embed=embed)


@bot.command(name="xrp", aliases=["precio"])
async def xrp_price(ctx):
    url = "https://api.binance.com/api/v3/ticker/price?symbol=XRPUSDT"
    async with ctx.typing():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = float(data['price'])
                        
                        embed = discord.Embed(
                            title="💎 Precio de XRP",
                            description=f"El precio actual de **XRP** es de **${price:.4f} USD**",
                            color=discord.Color.from_rgb(35, 41, 47)
                        )
                        embed.set_thumbnail(url="https://cryptologos.cc/logos/xrp-xrp-logo.png")
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("❌ No pude obtener el precio en este momento.")
        except Exception as e:
            await ctx.send("❌ Hubo un error al conectar con el servidor de precios.")


@bot.command(name="poppy")
async def poppy(ctx):
    embed = discord.Embed(
        title="✿ Hitoha Marui ✿",
        description="*...¿Qué están mirando?* (╥﹏╥)",
        color=discord.Color.from_rgb(138, 43, 226)
    )
    embed.set_image(url="https://images3.alphacoders.com/885/thumb-1920-885724.jpg")
    embed.set_footer(text="Mitsudomoe ♡")
    await ctx.send(embed=embed)


# --- DIVERSIÓN / INTERACCIÓN ---

ANIME_GIFS = {
    "abrazar": [
        "https://media1.tenor.com/m/0PIj7X4QoB4AAAAC/anime-hug.gif",
        "https://media1.tenor.com/m/JITj_LQ3fY0AAAAC/anime-hug-love.gif",
        "https://media1.tenor.com/m/D6pIzi3Ko98AAAAC/anime-hug.gif",
    ],
    "besar": [
        "https://media1.tenor.com/m/wDJDJU0xw_cAAAAC/anime-kiss.gif",
        "https://media1.tenor.com/m/fRgCfP1BkRcAAAAC/anime-kiss.gif",
        "https://media1.tenor.com/m/jrDTm37hEn4AAAAC/anime-kiss-couple.gif",
    ],
    "golpear": [
        "https://media1.tenor.com/m/bo4eJNBX2ogAAAAC/anime-slap.gif",
        "https://media1.tenor.com/m/Xi8UqQb5b4oAAAAC/anime-slap.gif",
        "https://media1.tenor.com/m/9eYq2Hw8pHYAAAAC/anime-slap.gif",
    ],
    "acariciar": [
        "https://media1.tenor.com/m/Ew3R8Q6nYh4AAAAC/anime-head-pat.gif",
        "https://media1.tenor.com/m/H1UvR0Q0XpIAAAAC/anime-pat.gif",
        "https://media1.tenor.com/m/sYvoTu76ML0AAAAC/anime-pat.gif",
    ],
}


@bot.command(name="lentes")
async def lentes(ctx):
    frases = [
        "👓 *Hitoha se ajusta los lentes con un gesto dramático...* el brillo oculta sus ojos.",
        "🔍 *Un destello cruza sus lentes mientras observa en silencio...* ¿qué estará pensando?",
        "👓 *Se empuja los lentes hacia arriba con el dedo medio...* un clásico. (￣ー￣)",
        "✨ *El reflejo de la pantalla rebota en sus gafas...* Hmph, no es como si me importara.",
        "👓 (；￣Д￣) *Hitoha se ajusta los lentes incómodamente...* ¿Q-qué miran?",
    ]
    embed = discord.Embed(
        description=random.choice(frases),
        color=discord.Color.from_rgb(100, 100, 200)
    )
    await ctx.send(embed=embed)


@bot.command(name="esconderse")
async def esconderse(ctx):
    embed_out = discord.Embed(
        description="🌑 *Hitoha se ajusta los lentes y se desvanece lentamente en las sombras...*",
        color=discord.Color.dark_purple()
    )
    await ctx.send(embed=embed_out)
    await asyncio.sleep(4)
    embed_in = discord.Embed(
        description="👓 *...Hitoha reaparece de entre las sombras, ajustándose los lentes.* Ya estoy de vuelta. No es como si me importara... baka.",
        color=discord.Color.purple()
    )
    await ctx.send(embed=embed_in)


@bot.command(name="say")
async def say(ctx, *, texto: str):
    prefijos = [
        "*Ajusta sus lentes...* Hmph, está bien... ",
        "(￣ε￣) *Suspira profundamente...* No es como si quisiera decirlo, pero... ",
        "📖 *Cierra su manga...* Si insistes... ",
        "(；一_一) *Resopla con desdén...* Lo diré, pero solo porque me obligas: ",
        "😤 ¡N-no es que quiera decirlo! ...pero bueno. ",
    ]
    await ctx.send(f"{random.choice(prefijos)}{texto}")


@bot.command(name="serverinfo", aliases=["server", "info"])
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(
        title=f"📊 {guild.name}",
        color=discord.Color.from_rgb(138, 43, 226)
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="🆔 ID del Servidor", value=guild.id, inline=True)
    embed.add_field(name="👑 Dueño", value=str(guild.owner), inline=True)
    embed.add_field(name="👥 Miembros", value=guild.member_count, inline=True)
    embed.add_field(name="📅 Creado el", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="💬 Canales", value=f"📝 Texto: {len(guild.text_channels)} | 🔊 Voz: {len(guild.voice_channels)}", inline=True)
    embed.add_field(name="🎭 Roles", value=len(guild.roles), inline=True)
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    await ctx.send(embed=embed)


@bot.command(name="ping")
async def ping(ctx):
    latencia = round(bot.latency * 1000)
    embed = discord.Embed(
        description=f"🏓 Pong! Latencia: **{latencia}ms**",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)


@bot.command(name="avatar", aliases=["foto"])
async def avatar(ctx, *, usuario: discord.User = None):
    user = usuario or ctx.author
    embed = discord.Embed(
        title=f"🖼️ Avatar de {user.display_name}",
        color=discord.Color.from_rgb(138, 43, 226)
    )
    embed.set_image(url=user.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="abrazar", aliases=["abrazo", "hug"])
async def abrazar(ctx, *, usuario: discord.User):
    if usuario == ctx.author:
        return await ctx.send("😳 *Hitoha se ajusta los lentes nerviosamente...* N-no puedes abrazarte a ti mismo, baka.")
    gif = random.choice(ANIME_GIFS["abrazar"])
    embed = discord.Embed(
        description=f"🤗 **{ctx.author.display_name}** abraza a **{usuario.display_name}**",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_image(url=gif)
    await ctx.send(embed=embed)


@bot.command(name="besar", aliases=["beso", "kiss"])
async def besar(ctx, *, usuario: discord.User):
    if usuario == ctx.author:
        return await ctx.send("💢 *Hitoha te mira fijamente...* ¿En serio intentas besarte a ti mismo? Qué vergüenza ajena...")
    gif = random.choice(ANIME_GIFS["besar"])
    embed = discord.Embed(
        description=f"💋 **{ctx.author.display_name}** besa a **{usuario.display_name}**",
        color=discord.Color.from_rgb(255, 80, 80)
    )
    embed.set_image(url=gif)
    await ctx.send(embed=embed)


@bot.command(name="golpear", aliases=["golpe", "slap", "pegar"])
async def golpear(ctx, *, usuario: discord.User):
    if usuario == ctx.author:
        return await ctx.send("😨 *Hitoha retrocede lentamente...* Golpearte a ti mismo... eso es nuevo incluso para mí.")
    gif = random.choice(ANIME_GIFS["golpear"])
    embed = discord.Embed(
        description=f"👊 **{ctx.author.display_name}** golpea a **{usuario.display_name}**",
        color=discord.Color.from_rgb(200, 50, 50)
    )
    embed.set_image(url=gif)
    await ctx.send(embed=embed)


@bot.command(name="acariciar", aliases=["caricia", "pat", "mimir"])
async def acariciar(ctx, *, usuario: discord.User):
    if usuario == ctx.author:
        return await ctx.send("🤔 *Hitoba bizquea los ojos...* ¿Acariciarte a ti mismo? ...hay algo raro en ti.")
    gif = random.choice(ANIME_GIFS["acariciar"])
    embed = discord.Embed(
        description=f"💆 **{ctx.author.display_name}** acaricia a **{usuario.display_name}**",
        color=discord.Color.from_rgb(255, 200, 100)
    )
    embed.set_image(url=gif)
    await ctx.send(embed=embed)


@bot.command(name="sfx", aliases=["efecto"])
async def sfx(ctx, effect_name: str):
    if not ctx.author.voice:
        return await ctx.send("❌ ¡Debes estar conectado a un canal de voz!")
    
    # Crear carpeta si no existe
    if not os.path.exists("sfx"):
        os.makedirs("sfx")
        return await ctx.send("⚠️ No existía la carpeta `sfx`. Acabo de crearla. Por favor, añade archivos de audio (.mp3, .wav) allí y vuelve a intentar.")
        
    # Buscar el archivo en la carpeta sfx/
    file_path = None
    for ext in [".mp3", ".wav", ".ogg", ".m4a"]:
        if os.path.exists(f"sfx/{effect_name}{ext}"):
            file_path = f"sfx/{effect_name}{ext}"
            break
            
    if not file_path:
        return await ctx.send(f"❌ No encontré el efecto de sonido `{effect_name}` en la carpeta `sfx/`.")
        
    state = get_music_state(ctx.guild.id)
    if not ctx.voice_client:
        state.voice_client = await ctx.author.voice.channel.connect()
        await _play_greeting(state, ctx)
    else:
        state.voice_client = ctx.voice_client

    # Reproducir archivo local
    source = discord.FFmpegPCMAudio(file_path)
    source = discord.PCMVolumeTransformer(source, volume=1.0)

    song = {
        'source': source,
        'title': f"Efecto de Sonido: {effect_name}",
        'url': "",
        'duration': 0,
        'channel': ctx.channel,
        'requester': ctx.author.mention,
        'hide_embed': True
    }

    if state.voice_client.is_playing() or state.voice_client.is_paused():
        state.queue.append(song)
        embed = discord.Embed(
            title="🔊 Efecto añadido a la cola",
            description=f"El efecto `{effect_name}` sonará pronto.",
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)
    else:
        state.queue.append(song)
        state.play_next()

async def _play_greeting(state, ctx):
    if os.path.exists("sfx/hola.mp3"):
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio("sfx/hola.mp3"))
        song = {
            'source': source,
            'title': "¡Hola!",
            'url': "",
            'duration': 0,
            'channel': ctx.channel,
            'requester': bot.user.mention,
            'hide_embed': True
        }
        state.queue.insert(0, song)
        if not state.voice_client.is_playing():
            state.play_next()


@bot.command(name="join")
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.send("❌ ¡Debes estar conectado a un canal de voz para usar este comando!")
    
    channel = ctx.author.voice.channel
    state = get_music_state(ctx.guild.id)
    
    if ctx.voice_client:
        if ctx.voice_client.channel != channel:
            await ctx.voice_client.move_to(channel)
            state.voice_client = ctx.voice_client
            await ctx.send(f"➡️ Me he movido al canal: **{channel.name}**")
    else:
        state.voice_client = await channel.connect()
        await _play_greeting(state, ctx)
        await ctx.send(f"🔊 ¡Conectado al canal: **{channel.name}**!")


@bot.command(name="play", aliases=["p"])
async def play(ctx, *, search: str):
    # Asegurar que el usuario esté en un canal de voz
    if not ctx.author.voice:
        return await ctx.send("❌ ¡Debes estar conectado a un canal de voz!")

    state = get_music_state(ctx.guild.id)

    # Conectar al canal si no lo está
    if not ctx.voice_client:
        state.voice_client = await ctx.author.voice.channel.connect()
        await _play_greeting(state, ctx)
    else:
        state.voice_client = ctx.voice_client

    async with ctx.typing():
        try:
            # Buscar y crear la fuente
            player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
        except Exception as e:
            return await ctx.send(f"❌ Ocurrió un error al buscar la canción: `{e}`")

        song = {
            'source': player,
            'title': player.title,
            'url': player.url,
            'duration': player.duration,
            'channel': ctx.channel,
            'requester': ctx.author.mention
        }

        # Comprobar si hay algo reproduciéndose
        if state.voice_client.is_playing() or state.voice_client.is_paused():
            state.queue.append(song)
            embed = discord.Embed(
                title="📝 Añadido a la cola",
                description=f"[{song['title']}]({song['url']})",
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"Posición en la cola: #{len(state.queue)}")
            await ctx.send(embed=embed)
        else:
            state.queue.append(song)
            state.play_next()


@bot.command(name="pause")
async def pause(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("❌ No se está reproduciendo música actualmente.")
    
    ctx.voice_client.pause()
    await ctx.send("⏸️ Música pausada.")


@bot.command(name="resume")
async def resume(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_paused():
        return await ctx.send("❌ La música no está pausada.")
    
    ctx.voice_client.resume()
    await ctx.send("▶️ Música reanudada.")


@bot.command(name="skip", aliases=["s"])
async def skip(ctx):
    if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        return await ctx.send("❌ No hay nada reproduciéndose para poder saltar.")
    
    ctx.voice_client.stop()
    await ctx.send("⏭️ Canción saltada.")


@bot.command(name="stop")
async def stop(ctx):
    state = get_music_state(ctx.guild.id)
    state.queue.clear()
    
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.send("⏹️ Reproducción detenida y cola vaciada.")
    else:
        await ctx.send("❌ No estoy conectado a ningún canal de voz.")


@bot.command(name="leave", aliases=["disconnect", "dc"])
async def leave(ctx):
    state = get_music_state(ctx.guild.id)
    state.queue.clear()
    
    if ctx.voice_client:
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            ctx.voice_client.stop()
            
        if os.path.exists("sfx/adios.mp3"):
            try:
                source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio("sfx/adios.mp3"))
                ctx.voice_client.play(source)
                while ctx.voice_client.is_playing():
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[Error despidiendose]: {e}")

        await ctx.voice_client.disconnect()
        # Limpiar estado
        if ctx.guild.id in music_states:
            del music_states[ctx.guild.id]
        despedidas = [
            "💀 *...No es como si quisiera quedarme... baka.* ¡Adiós!",
            "(；￣Д￣) *Hitoha se ajusta los lentes y desaparece en las sombras...* Sayonara.",
            "📖 *Tengo cosas más importantes que hacer... como leer Gachi Rangers.* Bye.",
            "(￣ε￣) *No me miren así... ya me voy.* Mata ne.",
            "🌙 *La oscuridad me llama... nos vemos, mortales.*",
            "(╥﹏╥) *Si me extrañan... no se lo diré a nadie.* Adiós.",
            "📚 *Volveré cuando terminen de hacer ruido...* Hmph.",
            "(ノ_<。) *No lloren por mí... sería molesto.* Sayonara.",
            "😤 *¡N-no es que me importe despedirme! Solo... adiós!*",
            "(⊙_⊙;) *Me retiro a las sombras... donde pertenezco.* Mata ne.",
            "📖 *El capítulo de hoy terminó. Continuará...* tal vez.",
            "(⁄ ⁄•⁄ω⁄•⁄ ⁄) *Hitoha hace una reverencia incómoda...* A-adiós...",
            "(；一_一) *...Me voy. No pregunten cuándo vuelvo.*",
            "🖤 *Hmph... esto no es un adiós, es una retirada estratégica.* ψ(｀∇´)ψ",
        ]
        await ctx.send(random.choice(despedidas))
    else:
        await ctx.send("❌ No estoy en ningún canal de voz.")


@bot.command(name="queue", aliases=["cola", "q"])
async def queue_info(ctx):
    state = get_music_state(ctx.guild.id)
    
    if not state.current and not state.queue:
        return await ctx.send("📭 La cola está vacía.")

    embed = discord.Embed(
        title="📋 Cola de Reproducción",
        color=discord.Color.blue()
    )

    if state.current:
        embed.add_field(
            name="Now Playing (Sonando ahora):",
            value=f"🎵 [{state.current['title']}]({state.current['url']}) | Solicitado por {state.current['requester']}",
            inline=False
        )

    if state.queue:
        queue_list = ""
        for i, song in enumerate(state.queue[:10], start=1):
            queue_list += f"`{i}.` [{song['title']}]({song['url']}) | Solicitado por {song['requester']}\n"
        
        if len(state.queue) > 10:
            queue_list += f"\n*Y {len(state.queue) - 10} canciones más en la lista...*"

        embed.add_field(name="Siguientes canciones:", value=queue_list, inline=False)
    else:
        embed.add_field(name="Siguientes canciones:", value="No hay más canciones en cola. ¡Añade algunas con `!play`!", inline=False)

    await ctx.send(embed=embed)


@bot.command(name="now", aliases=["np"])
async def now_playing(ctx):
    state = get_music_state(ctx.guild.id)
    if not state.current:
        return await ctx.send("❌ No hay nada sonando ahora mismo.")
    
    embed = discord.Embed(
        title="🎵 Sonando ahora",
        description=f"[{state.current['title']}]({state.current['url']})",
        color=discord.Color.green()
    )
    embed.add_field(name="Duración", value=state.format_duration(state.current['duration']))
    embed.add_field(name="Solicitado por", value=state.current['requester'])
    await ctx.send(embed=embed)


# Manejo de errores globales simples
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Ignorar comandos no encontrados
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Falta un argumento requerido. Uso correcto: `{PREFIX}{ctx.command.name} {ctx.command.signature}`")
    else:
        print(f"[Error de Comando]: {error}")
        await ctx.send(f"⚠️ Ocurrió un error al procesar el comando: `{error}`")


# Servidor HTTP de salud para Hugging Face Spaces / Render (requiere puerto abierto)
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

HEALTH_PORT = int(os.getenv('PORT', 7860))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def start_health():
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    server.serve_forever()

threading.Thread(target=start_health, daemon=True).start()
print(f"🩺 Health server iniciado en puerto {HEALTH_PORT}")

# Ejecutar el Bot
if not TOKEN or TOKEN == "TU_TOKEN_AQUI":
    print("[Error] ¡El token del bot no está configurado!")
    print("Configura la variable de entorno DISCORD_TOKEN (en HF: Settings > Secrets).")
    import time
    while True:
        time.sleep(60)
else:
    # Verificar conectividad antes de arrancar
    import subprocess, sys
    print("Verificando conectividad a Discord...")
    try:
        result = subprocess.run(
            ["python", "-c", "import socket; s=socket.socket(socket.AF_INET); s.settimeout(10); s.connect(('discord.com', 443)); print('OK'); s.close()"],
            capture_output=True, text=True, timeout=15
        )
        print(f"Test de conexion: {result.stdout.strip() or result.stderr.strip()}")
    except Exception as e:
        print(f"Test de conexion fallo: {e}")
    
    print("Iniciando bot...")
    bot.run(TOKEN)
