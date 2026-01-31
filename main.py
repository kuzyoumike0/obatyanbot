import os
import re
import uuid
import random
import asyncio
import shutil
import subprocess
import discord
from discord.ext import commands

# =====================
# 起動時診断（超重要）
# =====================
def boot_diagnostics():
    print("=== BOOT DIAGNOSTICS ===")

    # ffmpeg
    print("[diag] ffmpeg path:", shutil.which("ffmpeg"))
    try:
        v = subprocess.check_output(["ffmpeg", "-version"]).decode().splitlines()[0]
        print("[diag]", v)
    except Exception as e:
        print("[diag] ffmpeg check failed:", e)

    # opus
    try:
        if not discord.opus.is_loaded():
            discord.opus.load_opus("libopus.so.0")
        print("[diag] opus loaded:", discord.opus.is_loaded())
    except Exception as e:
        print("[diag] opus load failed:", e)

    print("========================")

boot_diagnostics()

# =====================
# ENV
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_LOG = os.getenv("DEBUG_LOG", "1") == "1"

# 関西おばちゃん声（調整可）
TTS_VOICE  = os.getenv("TTS_VOICE", "ja-JP-NanamiNeural")
TTS_RATE   = os.getenv("TTS_RATE", "+15%")
TTS_PITCH  = os.getenv("TTS_PITCH", "+2Hz")
TTS_VOLUME = os.getenv("TTS_VOLUME", "+10%")

VC_EVENT_COOLDOWN_SEC = int(os.getenv("VC_EVENT_COOLDOWN_SEC", "10"))

# =====================
# Intents
# =====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# 状態管理
# =====================
STAY_VC = {}          # guild_id -> vc_id
SPEAK_Q = {}          # guild_id -> asyncio.Queue
SPEAK_TASK = {}       # guild_id -> task
LAST_VC_EVENT_AT = {} # (guild_id, user_id) -> time

# =====================
# ユーティリティ
# =====================
def now_mono():
    return asyncio.get_event_loop().time()

def make_call_name(user):
    name = getattr(user, "display_name", None) or getattr(user, "name", "あんた")
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 10:
        name = name[:10]
    return name + random.choice(["ちゃん", "さん", ""])

def has_call(text: str) -> bool:
    return text.strip().startswith("おばちゃん")

def strip_call(text: str) -> str:
    return text.strip()[4:].strip() if text.strip().startswith("おばちゃん") else text

async def safe_send(ch, text):
    try:
        await ch.send(text)
    except Exception as e:
        print("[send failed]", e)

# =====================
# おばちゃん文生成
# =====================
TAILS = ["やで", "やん", "ほな", "せやな", "大丈夫や"]

def make_reply(name):
    return "\n".join([
        f"{name}、それはしんどかったな{random.choice(TAILS)}",
        f"無理しすぎやで、ほんま",
        f"でも今日もここ来れてるのは偉い",
        f"今は深呼吸だけでええ{random.choice(TAILS)}"
    ])

# =====================
# TTS
# =====================
SHORT_TAILS = ["やで", "やんな", "ほなな", "せやで", "かまへん"]

def kansai_short(text):
    if random.random() < 0.8:
        text += random.choice(SHORT_TAILS)
    return text + "。"

def kansai_full(text):
    lines = text.split("\n")
    return "… ".join(lines) + "。"

async def tts_to_mp3(text, path):
    import edge_tts
    comm = edge_tts.Communicate(
        text=text,
        voice=TTS_VOICE,
        rate=TTS_RATE,
        pitch=TTS_PITCH,
        volume=TTS_VOLUME,
    )
    await comm.save(path)

async def get_vc(guild, channel):
    vc = discord.utils.get(bot.voice_clients, guild=guild)
    if vc and vc.is_connected():
        if vc.channel.id != channel.id:
            await vc.move_to(channel)
        return vc
    return await channel.connect()

async def play_mp3(vc, path):
    print("[diag] play file exists:", os.path.exists(path))
    done = asyncio.Event()

    def after(err):
        if err:
            print("[VC play error]", err)
        done.set()

    vc.play(discord.FFmpegPCMAudio(path), after=after)
    await done.wait()

async def speaker_worker(guild_id):
    q = SPEAK_Q[guild_id]
    while True:
        item = await q.get()
        if item is None:
            return

        vc_id, text, short = item
        guild = bot.get_guild(guild_id)
        vc_ch = guild.get_channel(vc_id)

        try:
            vc = await get_vc(guild, vc_ch)
            tmp = f"tts_{uuid.uuid4().hex}.mp3"

            speak = kansai_short(text) if short else kansai_full(text)
            print("[diag] speaking:", speak)

            await tts_to_mp3(speak, tmp)
            await play_mp3(vc, tmp)

            os.remove(tmp)

            if guild_id not in STAY_VC:
                await vc.disconnect()

        except Exception as e:
            print("[speaker_worker error]", e)

        q.task_done()

async def enqueue_speech(guild_id, vc_id, text, short):
    if guild_id not in SPEAK_Q:
        SPEAK_Q[guild_id] = asyncio.Queue()
    await SPEAK_Q[guild_id].put((vc_id, text, short))

    if guild_id not in SPEAK_TASK or SPEAK_TASK[guild_id].done():
        SPEAK_TASK[guild_id] = asyncio.create_task(speaker_worker(guild_id))

# =====================
# VC常駐コマンド
# =====================
@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send("先にVC入ってな。")
        return
    vc = ctx.author.voice.channel
    STAY_VC[ctx.guild.id] = vc.id
    await ctx.send(f"{vc.name} に常駐するで。")
    await get_vc(ctx.guild, vc)

@bot.command()
async def leave(ctx):
    STAY_VC.pop(ctx.guild.id, None)
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc:
        await vc.disconnect()
    await ctx.send("ほな、またな。")

# =====================
# 入退室（一言）
# =====================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    gid = member.guild.id
    vc_id = STAY_VC.get(gid)
    if not vc_id:
        return

    now = now_mono()
    key = (gid, member.id)
    if now - LAST_VC_EVENT_AT.get(key, 0) < VC_EVENT_COOLDOWN_SEC:
        return
    LAST_VC_EVENT_AT[key] = now

    name = make_call_name(member)

    if before.channel is None and after.channel and after.channel.id == vc_id:
        await enqueue_speech(gid, vc_id, f"{name}来たん？", True)

    if before.channel and before.channel.id == vc_id and after.channel is None:
        await enqueue_speech(gid, vc_id, f"{name}おつかれ", True)

# =====================
# チャット反応（VCチャット含む）
# =====================
@bot.event
async def on_message(msg):
    if msg.author.bot:
        return

    await bot.process_commands(msg)

    if DEBUG_LOG:
        print("[GOT]", type(msg.channel).__name__, msg.content)

    if not has_call(msg.content):
        return

    name = make_call_name(msg.author)
    reply = make_reply(name)

    await safe_send(msg.channel, reply)

    gid = msg.guild.id
    vc_id = STAY_VC.get(gid)

    if not vc_id and msg.author.voice:
        vc_id = msg.author.voice.channel.id

    if vc_id:
        await enqueue_speech(gid, vc_id, reply, False)

# =====================
# 起動
# =====================
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

bot.run(DISCORD_TOKEN)
