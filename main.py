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
# 起動時診断（無音対策）
# =====================
def boot_diagnostics():
    print("=== BOOT DIAGNOSTICS ===")
    print("[diag] ffmpeg path:", shutil.which("ffmpeg"))

    try:
        print("[diag]", subprocess.check_output(
            ["ffmpeg", "-version"]
        ).decode().splitlines()[0])
    except Exception as e:
        print("[diag] ffmpeg check failed:", e)

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
DEBUG_LOG = True

TTS_VOICE  = "ja-JP-NanamiNeural"
TTS_RATE   = "+15%"
TTS_PITCH  = "+2Hz"
TTS_VOLUME = "+10%"

# =====================
# Discord intents
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
STAY_VC = {}              # guild_id -> vc_id
SPEAK_Q = {}              # guild_id -> queue
SPEAK_TASK = {}           # guild_id -> task

# =====================
# Utility
# =====================
def make_name(user):
    name = user.display_name or user.name
    return name[:10] + random.choice(["ちゃん", "さん", ""])

def is_call(text):
    return text.strip().startswith("おばちゃん")

def strip_call(text):
    return text.strip()[4:].strip()

# =====================
# おばちゃん文
# =====================
TAILS = ["やで", "やんな", "ほな", "せやな"]

def make_reply(name):
    return "\n".join([
        f"{name}、それはしんどかったな{random.choice(TAILS)}",
        "無理しすぎやで",
        "でも今日も生きてるのは偉い",
        f"今は深呼吸だけでええ{random.choice(TAILS)}"
    ])

# =====================
# TTS
# =====================
def kansai_full(text):
    return "… ".join(text.split("\n")) + "。"

def kansai_short(text):
    return text + random.choice(["やで。", "やんな。", "ほなな。"])

async def tts_to_mp3(text, path):
    import edge_tts
    tts = edge_tts.Communicate(
        text=text,
        voice=TTS_VOICE,
        rate=TTS_RATE,
        pitch=TTS_PITCH,
        volume=TTS_VOLUME,
    )
    await tts.save(path)

async def get_vc(guild, channel):
    vc = discord.utils.get(bot.voice_clients, guild=guild)
    if vc and vc.is_connected():
        if vc.channel.id != channel.id:
            await vc.move_to(channel)
        return vc
    return await channel.connect()

async def play_once(vc, mp3_path):
    if not os.path.exists(mp3_path):
        print("[missing sound]", mp3_path)
        return

    done = asyncio.Event()

    def after(err):
        if err:
            print("[sound error]", err)
        done.set()

    vc.play(discord.FFmpegPCMAudio(mp3_path), after=after)
    await done.wait()

async def play_mp3(vc, mp3_path):
    done = asyncio.Event()

    def after(err):
        if err:
            print("[tts play error]", err)
        done.set()

    vc.play(discord.FFmpegPCMAudio(mp3_path), after=after)
    await done.wait()

async def speaker_worker(guild_id):
    q = SPEAK_Q[guild_id]
    while True:
        vc_id, text, short = await q.get()
        guild = bot.get_guild(guild_id)
        vc_ch = guild.get_channel(vc_id)

        try:
            vc = await get_vc(guild, vc_ch)
            tmp = f"tts_{uuid.uuid4().hex}.mp3"

            speak = kansai_short(text) if short else kansai_full(text)
            await tts_to_mp3(speak, tmp)
            await play_mp3(vc, tmp)
            os.remove(tmp)

        except Exception as e:
            print("[speaker error]", e)

        q.task_done()

async def enqueue_speech(guild_id, vc_id, text, short):
    if guild_id not in SPEAK_Q:
        SPEAK_Q[guild_id] = asyncio.Queue()

    await SPEAK_Q[guild_id].put((vc_id, text, short))

    if guild_id not in SPEAK_TASK or SPEAK_TASK[guild_id].done():
        SPEAK_TASK[guild_id] = asyncio.create_task(
            speaker_worker(guild_id)
        )

# =====================
# VC常駐
# =====================
@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send("先にVC入ってから呼んでな。")
        return

    vc_ch = ctx.author.voice.channel
    STAY_VC[ctx.guild.id] = vc_ch.id
    vc = await get_vc(ctx.guild, vc_ch)

    # ★ 入室音（1回だけ）
    await play_once(vc, "nyuusitu.mp3")

    await ctx.send(f"{vc_ch.name} に常駐するで。")

@bot.command()
async def leave(ctx):
    STAY_VC.pop(ctx.guild.id, None)
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc:
        await vc.disconnect()
    await ctx.send("ほな、またな。")

# =====================
# 入退室（短文）
# =====================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    gid = member.guild.id
    vc_id = STAY_VC.get(gid)
    if not vc_id:
        return

    name = make_name(member)

    if before.channel is None and after.channel and after.channel.id == vc_id:
        await enqueue_speech(gid, vc_id, f"{name}来たん？", True)

    if before.channel and before.channel.id == vc_id and after.channel is None:
        await enqueue_speech(gid, vc_id, f"{name}おつかれ", True)

# =====================
# チャット反応（VC読み上げ）
# =====================
@bot.event
async def on_message(msg):
    if msg.author.bot:
        return

    await bot.process_commands(msg)

    if not is_call(msg.content):
        return

    name = make_name(msg.author)

    # 「おばちゃん」だけ
    body = strip_call(msg.content)
    if body == "":
        reply = f"{name}、どしたん？\n無理せんでええ。\n呼べた時点で偉い。\n今いちばんしんどいのどれ？"
    else:
        reply = make_reply(name)

    await msg.channel.send(reply)

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
