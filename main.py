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

# 人格ブレ
OBACHAN_SASS = int(os.getenv("OBACHAN_SASS", "55"))
OBACHAN_SOFT = int(os.getenv("OBACHAN_SOFT", "75"))
OBACHAN_LONG = int(os.getenv("OBACHAN_LONG", "55"))

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

def chance(pct: int) -> bool:
    return random.randint(1, 100) <= max(0, min(100, pct))

# =====================
# おばちゃん人格
# =====================
TAILS = ["やで", "やん", "ほな", "せやな", "大丈夫や", "まあな"]
LAUGHT = ["（笑）", "w", "ふふ", "ほんまにもう"]
CANDY = ["飴ちゃんいる？", "あったかいお茶飲み。", "とりあえず水や。", "背中さすったろか。"]
SCOLD = [
    "無理しすぎやって。ほんま。",
    "頑張り屋ほど倒れるんやで。",
    "抱え込み癖、出てるで。",
    "それ、気ぃ張りすぎや。"
]
PRAISE = [
    "今日ここまで来ただけで偉い。",
    "呼べた時点で勝ちやで。",
    "しんどいって言えたん、えらい。",
    "逃げへんかった自分、ようやった。"
]
ASK = [
    "いま一番しんどいの、どれ？",
    "体と心、どっちが先に悲鳴あげてる？",
    "0〜10で言うたら、しんどさ何点？",
    "寝れてる？ご飯は？"
]
TIP = [
    "今日は“深呼吸3回”だけやって、あとは甘やかし。",
    "1個だけやるなら、顔洗うか布団入るかや。",
    "今の自分を責めるの禁止。代わりに肩回して。",
    "まず温度上げよ。寒いとメンタル縮むんよ。"
]
TEASE = [
    "あんたほんま、頑張りすぎ選手権優勝やな。",
    "また1人で背負ってる顔しとるで。",
    "それ、我慢大会ちゃうねん。",
    "ええ子ぶりすぎや、息して。"
]

def make_obachan_reply(name: str, body: str) -> str:
    empath = random.choice([
        f"{name}、それはしんどかったな{random.choice(TAILS)}",
        f"{name}、よう言うてくれたな{random.choice(TAILS)}",
        f"{name}、今はつらい時やな{random.choice(TAILS)}",
    ])

    sc = random.choice(TEASE if chance(50) else SCOLD) if chance(OBACHAN_SASS) else ""
    pr = random.choice(PRAISE) if chance(OBACHAN_SOFT) else "まあ…しゃあない日もある。"
    tip = random.choice(TIP)
    candy = random.choice(CANDY)
    ask = random.choice(ASK)

    lines = [empath]
    if sc:
        lines.append(sc + random.choice(["", " " + random.choice(LAUGHT)]))
    lines.append(pr)
    lines.append(tip + random.choice(["", f" {candy}"]))
    lines.append(ask)

    return "\n".join(lines[:5 if chance(OBACHAN_LONG) else 4])

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
# VC 接続（★耐障害版）
# =====================
async def get_vc(guild: discord.Guild, channel: discord.VoiceChannel) -> discord.VoiceClient:
    vc = discord.utils.get(bot.voice_clients, guild=guild)

    # 壊れたVCは必ず捨てる
    if vc and not vc.is_connected():
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        vc = None

    if vc and vc.is_connected():
        if vc.channel.id != channel.id:
            await vc.move_to(channel)
        return vc

    return await channel.connect(timeout=60, reconnect=True)

# =====================
# 再生
# =====================
async def play_audio_file(vc: discord.VoiceClient, mp3_path: str):
    if not os.path.exists(mp3_path):
        return

    if vc.is_playing():
        vc.stop()
        await asyncio.sleep(0.05)

    done = asyncio.Event()

    def after(err):
        done.set()

    vc.play(discord.FFmpegPCMAudio(mp3_path), after=after)
    await done.wait()

# =====================
# Audio Queue
# =====================
async def ensure_queue(guild_id: int) -> asyncio.Queue:
    if guild_id not in AUDIO_Q:
        AUDIO_Q[guild_id] = asyncio.Queue()
    return AUDIO_Q[guild_id]

async def audio_worker(guild_id: int):
    q = await ensure_queue(guild_id)

    while True:
        item = await q.get()
        if item is None:
            q.task_done()
            return

        vc = None
        try:
            vc_id, kind, payload = item
            guild = bot.get_guild(guild_id)
            if not guild:
                continue

            ch = guild.get_channel(vc_id)
            if not isinstance(ch, discord.VoiceChannel):
                continue

            vc = await get_vc(guild, ch)

            if kind == "file":
                await play_audio_file(vc, payload)
            else:
                tmp = f"tts_{uuid.uuid4().hex}.mp3"
                text = kansai_short(payload) if kind == "tts_short" else kansai_full(payload)
                await tts_to_mp3(text, tmp)
                await play_audio_file(vc, tmp)
                os.remove(tmp)

        except Exception as e:
            print("[audio_worker]", e)

        finally:
            q.task_done()
            # ★ アイドル時は切断（安定化の要）
            if vc and not vc.is_playing() and guild_id not in STAY_VC:
                try:
                    await vc.disconnect()
                except Exception:
                    pass

async def enqueue_audio(guild_id: int, vc_id: int, kind: str, payload: str):
    q = await ensure_queue(guild_id)
    await q.put((vc_id, kind, payload))

    if guild_id not in AUDIO_TASK or AUDIO_TASK[guild_id].done():
        AUDIO_TASK[guild_id] = asyncio.create_task(audio_worker(guild_id))

# =====================
# Commands
# =====================
@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send("先にVC入ってから呼んでな。")
        return

    vc = ctx.author.voice.channel
    STAY_VC[ctx.guild.id] = vc.id
    await get_vc(ctx.guild, vc)
    await enqueue_audio(ctx.guild.id, vc.id, "file", JOIN_SE_PATH)
    await ctx.send(f"{vc.name} に常駐するで。")

@bot.command()
async def leave(ctx):
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
    stay = STAY_VC.get(gid)
    if not stay:
        return

    key = (gid, member.id)
    if now_mono() - LAST_VC_EVENT_AT.get(key, 0) < VC_EVENT_COOLDOWN_SEC:
        return
    LAST_VC_EVENT_AT[key] = now_mono()

    name = make_name(member)

    if before.channel is None and after.channel and after.channel.id == stay:
        await enqueue_audio(gid, stay, "tts_short", f"{name}来たん？")

    if before.channel and before.channel.id == stay and after.channel is None:
        await enqueue_audio(gid, stay, "tts_short", f"{name}おつかれ")

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
