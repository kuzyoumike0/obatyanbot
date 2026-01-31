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
# 起動時診断
# =====================
print("=== BOOT DIAG ===")
print("[diag] ffmpeg:", shutil.which("ffmpeg"))
try:
    print("[diag]", subprocess.check_output(["ffmpeg", "-version"]).decode().splitlines()[0])
except Exception as e:
    print("[diag] ffmpeg check failed:", e)

try:
    if not discord.opus.is_loaded():
        discord.opus.load_opus("libopus.so.0")
    print("[diag] opus loaded:", discord.opus.is_loaded())
except Exception as e:
    print("[diag] opus load failed:", e)
print("==================")

# =====================
# ENV
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_LOG = os.getenv("DEBUG_LOG", "1") == "1"

TTS_VOICE  = os.getenv("TTS_VOICE", "ja-JP-NanamiNeural")
TTS_RATE   = os.getenv("TTS_RATE", "+15%")
TTS_PITCH  = os.getenv("TTS_PITCH", "+2Hz")
TTS_VOLUME = os.getenv("TTS_VOLUME", "+10%")

JOIN_SE_PATH = os.getenv("JOIN_SE_PATH", "nyuusitu.mp3")

VC_EVENT_COOLDOWN_SEC = int(os.getenv("VC_EVENT_COOLDOWN_SEC", "10"))
VC_TEXT_COOLDOWN_SEC  = int(os.getenv("VC_TEXT_COOLDOWN_SEC", "2"))

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
STAY_VC: dict[int, int] = {}
AUDIO_Q: dict[int, asyncio.Queue] = {}
AUDIO_TASK: dict[int, asyncio.Task] = {}

LAST_VC_EVENT_AT: dict[tuple[int, int], float] = {}
LAST_VC_TEXT_AT: dict[tuple[int, int], float] = {}

# =====================
# Utility
# =====================
def now_mono() -> float:
    return asyncio.get_event_loop().time()

def make_name(user: discord.abc.User) -> str:
    name = getattr(user, "display_name", None) or getattr(user, "name", "あんた")
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 10:
        name = name[:10]
    return name + random.choice(["ちゃん", "さん", ""])

def is_call(text: str) -> bool:
    return text.strip().startswith("おばちゃん")

def strip_call(text: str) -> str:
    t = text.strip()
    return t[len("おばちゃん"):].strip() if t.startswith("おばちゃん") else t

# =====================
# おばちゃん文
# =====================
TAILS = ["やで", "やん", "ほな", "せやな", "大丈夫や"]

def make_reply(name: str) -> str:
    return "\n".join([
        f"{name}、それはしんどかったな{random.choice(TAILS)}",
        "無理しすぎやで",
        "でも今日も生きてるのは偉い",
        f"今は深呼吸だけでええ{random.choice(TAILS)}"
    ])

# =====================
# TTS
# =====================
def kansai_full(text: str) -> str:
    return "… ".join([ln.strip() for ln in text.split("\n") if ln.strip()]) + "。"

def kansai_short(text: str) -> str:
    return text + random.choice(["やで。", "やんな。", "ほなな。"])

async def tts_to_mp3(text: str, out_path: str):
    import edge_tts
    tts = edge_tts.Communicate(
        text=text,
        voice=TTS_VOICE,
        rate=TTS_RATE,
        pitch=TTS_PITCH,
        volume=TTS_VOLUME,
    )
    await tts.save(out_path)

# =====================
# VC 接続 / 再生
# =====================
async def get_vc(guild: discord.Guild, channel: discord.VoiceChannel) -> discord.VoiceClient:
    vc = discord.utils.get(bot.voice_clients, guild=guild)
    if vc and vc.is_connected():
        if vc.channel and vc.channel.id != channel.id:
            await vc.move_to(channel)
        return vc
    return await channel.connect(timeout=10)

async def play_audio_file(vc: discord.VoiceClient, mp3_path: str):
    if not os.path.exists(mp3_path):
        print("[audio missing]", mp3_path)
        return

    if vc.is_playing():
        vc.stop()
        await asyncio.sleep(0.05)

    done = asyncio.Event()

    def after(err):
        if err:
            print("[audio play error]", err)
        done.set()

    vc.play(discord.FFmpegPCMAudio(mp3_path), after=after)
    await done.wait()

# =====================
# Audio Queue
# =====================
async def ensure_queue(guild_id: int) -> asyncio.Queue:
    q = AUDIO_Q.get(guild_id)
    if q is None:
        q = asyncio.Queue()
        AUDIO_Q[guild_id] = q
    return q

async def audio_worker(guild_id: int):
    q = await ensure_queue(guild_id)

    while True:
        item = await q.get()
        if item is None:
            q.task_done()
            return

        try:
            vc_id, kind, payload = item
            guild = bot.get_guild(guild_id)
            if not guild:
                q.task_done()
                continue

            vc_ch = guild.get_channel(vc_id)
            if not isinstance(vc_ch, discord.VoiceChannel):
                q.task_done()
                continue

            vc = await get_vc(guild, vc_ch)

            if kind == "file":
                await play_audio_file(vc, payload)

            elif kind == "tts_short":
                tmp = f"tts_{uuid.uuid4().hex}.mp3"
                await tts_to_mp3(kansai_short(payload), tmp)
                await play_audio_file(vc, tmp)
                os.remove(tmp)

            elif kind == "tts_full":
                tmp = f"tts_{uuid.uuid4().hex}.mp3"
                await tts_to_mp3(kansai_full(payload), tmp)
                await play_audio_file(vc, tmp)
                os.remove(tmp)

        except Exception as e:
            print("[audio_worker error]", e)
        finally:
            q.task_done()

async def enqueue_audio(guild_id: int, vc_id: int, kind: str, payload: str):
    q = await ensure_queue(guild_id)
    await q.put((vc_id, kind, payload))

    if guild_id not in AUDIO_TASK or AUDIO_TASK[guild_id].done():
        AUDIO_TASK[guild_id] = asyncio.create_task(audio_worker(guild_id))

# =====================
# Commands
# =====================
@bot.command()
async def join(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("先にVC入ってから呼んでな。")
        return

    vc_ch = ctx.author.voice.channel
    STAY_VC[ctx.guild.id] = vc_ch.id

    await get_vc(ctx.guild, vc_ch)
    await enqueue_audio(ctx.guild.id, vc_ch.id, "file", JOIN_SE_PATH)
    await ctx.send(f"{vc_ch.name} に常駐するで。")

@bot.command()
async def leave(ctx: commands.Context):
    STAY_VC.pop(ctx.guild.id, None)
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc:
        await vc.disconnect(force=True)
    await ctx.send("ほな、またな。")

# =====================
# VC 入退室
# =====================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    gid = member.guild.id
    stay_vc_id = STAY_VC.get(gid)
    if not stay_vc_id:
        return

    key = (gid, member.id)
    if now_mono() - LAST_VC_EVENT_AT.get(key, 0) < VC_EVENT_COOLDOWN_SEC:
        return
    LAST_VC_EVENT_AT[key] = now_mono()

    name = make_name(member)

    if before.channel is None and after.channel and after.channel.id == stay_vc_id:
        await enqueue_audio(gid, stay_vc_id, "tts_short", f"{name}来たん？")

    if before.channel and before.channel.id == stay_vc_id and after.channel is None:
        await enqueue_audio(gid, stay_vc_id, "tts_short", f"{name}おつかれ")

# =====================
# メッセージ処理
# =====================
@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return

    await bot.process_commands(msg)

    # ===== VCテキスト =====
    if msg.guild and msg.channel.type == discord.ChannelType.voice:
        gid = msg.guild.id

        # おばちゃん呼びを最優先
        if is_call(msg.content):
            name = make_name(msg.author)
            body = strip_call(msg.content)

            if body == "":
                reply = f"{name}、どしたん？\n無理せんでええ。\n呼べた時点で偉い。\n今いちばんしんどいのどれ？"
            else:
                reply = make_reply(name)

            await msg.channel.send(reply)
            vc_id = STAY_VC.get(gid) or msg.channel.id
            await enqueue_audio(gid, vc_id, "tts_full", reply)
            return

        # 通常VCテキスト読み上げ
        key = (gid, msg.author.id)
        if now_mono() - LAST_VC_TEXT_AT.get(key, 0) < VC_TEXT_COOLDOWN_SEC:
            return
        LAST_VC_TEXT_AT[key] = now_mono()

        content = msg.content.strip()
        if content and not content.startswith("!"):
            content = re.sub(r"https?://\S+", "URL", content)
            name = make_name(msg.author)
            vc_id = STAY_VC.get(gid) or msg.channel.id
            await enqueue_audio(gid, vc_id, "tts_short", f"{name}、{content}")
        return

    # ===== 通常テキスト =====
    if not is_call(msg.content):
        return

    name = make_name(msg.author)
    body = strip_call(msg.content)
    reply = make_reply(name) if body else f"{name}、どしたん？\n無理せんでええ。"

    await msg.channel.send(reply)

    vc_id = STAY_VC.get(msg.guild.id)
    if vc_id:
        await enqueue_audio(msg.guild.id, vc_id, "tts_full", reply)

# =====================
# Ready
# =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")

# =====================
# 起動
# =====================
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

bot.run(DISCORD_TOKEN)
