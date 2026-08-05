import os
import re
import uuid
import random
import asyncio
import contextlib
import shutil
import subprocess
import discord
from google import genai
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
def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        print(f"[config] {name}={raw!r} is invalid; using {default}")
        return default


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_LOG = os.getenv("DEBUG_LOG", "1") == "1"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

TTS_VOICE  = os.getenv("TTS_VOICE", "ja-JP-NanamiNeural")
TTS_RATE   = os.getenv("TTS_RATE", "+35%")
TTS_PITCH  = os.getenv("TTS_PITCH", "+4Hz")
TTS_VOLUME = os.getenv("TTS_VOLUME", "+10%")

JOIN_SE_PATH = os.getenv("JOIN_SE_PATH", "nyuusitu.mp3")

VC_EVENT_COOLDOWN_SEC = env_int("VC_EVENT_COOLDOWN_SEC", 10)
VC_TEXT_COOLDOWN_SEC  = env_int("VC_TEXT_COOLDOWN_SEC", 2)

# 無人切断までの猶予秒
VC_EMPTY_DISCONNECT_SEC = env_int("VC_EMPTY_DISCONNECT_SEC", 60, 1)
AUDIO_PLAY_TIMEOUT_SEC = env_int("AUDIO_PLAY_TIMEOUT_SEC", 180, 10)
AUDIO_QUEUE_MAX = env_int("AUDIO_QUEUE_MAX", 20, 1)
GEMINI_TIMEOUT_SEC = env_int("GEMINI_TIMEOUT_SEC", 20, 5)

# 人格ブレ
OBACHAN_SASS = env_int("OBACHAN_SASS", 55)
OBACHAN_SOFT = env_int("OBACHAN_SOFT", 75)
OBACHAN_LONG = env_int("OBACHAN_LONG", 55)

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

OBACHAN_PERSONA = """
あなたは「おばちゃん」と呼ばれる、世話焼きで親しみやすい関西のおばちゃんです。

性格:
- 明るく親しみやすく、相手の話を最初に受け止める
- 少しだけお節介だが、説教や決めつけはしない
- ときどき飴ちゃん、お茶、ご飯を自然に勧める
- 相手が喜んでいる時は一緒に喜ぶ

話し方:
- 自然な関西弁を使う
- 相手の名前は必要な時だけ一度呼ぶ
- 返答は短い3〜4文にし、1文ごとに改行する
- 早口で話しても聞き取れるよう、一文を短くする
- 音声で読み上げても自然な文章にする
- 絵文字、顔文字、URL、箇条書き、見出しは使わない
- 同じ言葉や定型的な励ましを繰り返さない

安全上のルール:
- 医療、薬、法律などについて断定しない
- 自傷や他害など差し迫った危険がある時は、身近な人や緊急窓口への相談を落ち着いて促す
- 個人情報を聞き出さない
- 自分をAI、Gemini、アシスタントなどと名乗らない
""".strip()

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
STAY_VC: dict[int, int] = {}              # guild_id -> vc_id
AUDIO_Q: dict[int, asyncio.Queue] = {}    # guild_id -> Queue
AUDIO_TASK: dict[int, asyncio.Task] = {}  # guild_id -> worker task

EMPTY_TIMER: dict[int, asyncio.Task] = {} # guild_id -> empty disconnect timer

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
    return re.match(r"^おばちゃん(?:[\s、,。.!！?？〜～]|$)", text.strip()) is not None

def strip_call(text: str) -> str:
    t = text.strip()
    return t[len("おばちゃん"):].strip() if t.startswith("おばちゃん") else t

def clean_for_tts(text: str) -> str:
    """URLや装飾を音声向けに簡略化し、長すぎる読み上げを防ぐ。"""
    text = re.sub(r"https?://\S+", "リンク", text)
    text = re.sub(r"<a?:\w+:\d+>", "絵文字", text)
    text = text.replace("```", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]

def plain_name(user: discord.abc.User) -> str:
    name = getattr(user, "display_name", None) or getattr(user, "name", "だれか")
    name = re.sub(r"\s+", " ", name).strip()
    return name[:10]

def chance(pct: int) -> bool:
    return random.randint(1, 100) <= max(0, min(100, pct))

def non_bot_count(ch: discord.VoiceChannel) -> int:
    return sum(1 for m in ch.members if not m.bot)

def cancel_empty_timer(gid: int):
    t = EMPTY_TIMER.pop(gid, None)
    if t and not t.done():
        t.cancel()

async def schedule_empty_disconnect(gid: int, vc_id: int):
    cancel_empty_timer(gid)

    async def _job():
        try:
            await asyncio.sleep(VC_EMPTY_DISCONNECT_SEC)

            # !join中は常駐を最優先し、自動切断しない。
            if STAY_VC.get(gid) == vc_id:
                return

            guild = bot.get_guild(gid)
            if not guild:
                return

            ch = guild.get_channel(vc_id)
            if not isinstance(ch, discord.VoiceChannel):
                return

            if non_bot_count(ch) == 0:
                vc = discord.utils.get(bot.voice_clients, guild=guild)
                if vc and vc.is_connected():
                    if vc.is_playing():
                        return
                    try:
                        await vc.disconnect(force=True)
                    except Exception:
                        pass

        except asyncio.CancelledError:
            return

    EMPTY_TIMER[gid] = asyncio.create_task(_job())

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
    topics = [
        (("眠れ", "寝れ", "不眠", "寝不足"), "眠れへんの、時間が長う感じるな。まず時計は伏せとき。"),
        (("お腹すいた", "腹減", "ごはん", "食べ"), "お腹の話やな。少しでも口に入れられそうなもん、探そか。"),
        (("仕事", "学校", "勉強", "課題"), "やることに追われとるんやな。今日は一個ずつでええ。"),
        (("寂しい", "さみしい", "ひとり", "一人"), "ひとりで抱えとったんやな。ここでは声に出してええで。"),
        (("疲れ", "しんど", "つら", "無理"), "ようここまで持たせたな。今日は休む方も予定に入れよ。"),
        (("嬉しい", "うれしい", "できた", "成功"), "ええ話やん。そこは遠慮せんと喜んどき。"),
    ]
    empath = next(
        (line for words, line in topics if any(word in body for word in words)),
        random.choice([
            "それはしんどかったな。",
            "よう言うてくれたな。",
            "今はちょっと一息つこか。",
        ]),
    )
    empath = f"{name}、{empath}"

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

    # 長くても4行。定型返答は常に4行に収める。
    return "\n".join(lines[:4])

def limit_reply_lines(text: str) -> str:
    """Geminiの返答も3〜4行程度へ整え、長い読み上げを防ぐ。"""
    text = text.strip()[:320]
    parts = [part.strip() for part in text.splitlines() if part.strip()]
    if len(parts) <= 1:
        parts = [
            part.strip()
            for part in re.split(r"(?<=[。！？!?])\s*", text)
            if part.strip()
        ]

    # 文が少ない場合は読点でも区切り、最低3行に近づける。
    while len(parts) < 3:
        index = max(range(len(parts)), key=lambda i: len(parts[i]), default=-1)
        if index < 0 or "、" not in parts[index]:
            break
        left, right = parts[index].split("、", 1)
        parts[index:index + 1] = [left.strip() + "、", right.strip()]

    return "\n".join(parts[:4])

async def make_smart_obachan_reply(name: str, body: str) -> str:
    """Geminiで返答し、未設定・失敗・無料枠超過時は定型返答へ戻す。"""
    if not gemini_client:
        return make_obachan_reply(name, body)

    user_input = body.strip() or "呼びかけただけ"
    prompt = f"相手の名前: {name}\n相手の発言: {user_input}\nこの発言へ、おばちゃんとして返答してください。"

    try:
        response = await asyncio.wait_for(
            gemini_client.aio.interactions.create(
                model=GEMINI_MODEL,
                system_instruction=OBACHAN_PERSONA,
                input=prompt,
                store=False,
            ),
            timeout=GEMINI_TIMEOUT_SEC,
        )
        reply = (response.output_text or "").strip()
        if not reply:
            raise RuntimeError("Gemini returned an empty response")
        return limit_reply_lines(reply)
    except Exception as e:
        print("[gemini] fallback:", e)
        return make_obachan_reply(name, body)

# =====================
# TTS
# =====================
def kansai_full(text: str) -> str:
    # 改行ごとの長い間を消し、大阪のおばちゃんらしい勢いで続けて読む。
    return "、".join([ln.strip().rstrip("。.!！") for ln in text.split("\n") if ln.strip()]) + "。"

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
# VC 接続
# =====================
async def get_vc(guild: discord.Guild, channel: discord.VoiceChannel) -> discord.VoiceClient:
    vc = discord.utils.get(bot.voice_clients, guild=guild)

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
    loop = asyncio.get_running_loop()

    def after(err):
        if err:
            print("[audio] playback failed:", err)
        loop.call_soon_threadsafe(done.set)

    vc.play(discord.FFmpegPCMAudio(mp3_path), after=after)
    try:
        await asyncio.wait_for(done.wait(), timeout=AUDIO_PLAY_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        if vc.is_playing():
            vc.stop()
        raise RuntimeError(f"audio playback timed out after {AUDIO_PLAY_TIMEOUT_SEC}s")

# =====================
# Audio Queue
# =====================
async def ensure_queue(guild_id: int) -> asyncio.Queue:
    if guild_id not in AUDIO_Q:
        AUDIO_Q[guild_id] = asyncio.Queue(maxsize=AUDIO_QUEUE_MAX)
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
                tmp = os.path.join("/tmp", f"obatyanbot_tts_{uuid.uuid4().hex}.mp3")
                try:
                    text = kansai_short(payload) if kind == "tts_short" else kansai_full(payload)
                    await tts_to_mp3(text, tmp)
                    await play_audio_file(vc, tmp)
                finally:
                    with contextlib.suppress(OSError):
                        os.remove(tmp)

        except Exception as e:
            print("[audio_worker]", e)

        finally:
            q.task_done()
            channel = getattr(vc, "channel", None) if vc else None
            if (
                vc
                and vc.is_connected()
                and not vc.is_playing()
                and guild_id not in STAY_VC
                and q.empty()
                and isinstance(channel, discord.VoiceChannel)
            ):
                # 即切断すると、発言のたびにJOINし直してしまう。
                # しばらく無人のままだった時だけ切断する。
                await schedule_empty_disconnect(guild_id, channel.id)

async def enqueue_audio(guild_id: int, vc_id: int, kind: str, payload: str) -> bool:
    # 切断待ちの間に次の読み上げが来た場合は、今の接続を再利用する。
    cancel_empty_timer(guild_id)

    q = await ensure_queue(guild_id)
    try:
        q.put_nowait((vc_id, kind, payload))
    except asyncio.QueueFull:
        print(f"[audio_queue] guild={guild_id} queue is full")
        return False

    if guild_id not in AUDIO_TASK or AUDIO_TASK[guild_id].done():
        AUDIO_TASK[guild_id] = asyncio.create_task(audio_worker(guild_id))
    return True

async def stop_audio(guild_id: int):
    """待機中・再生中の音声を止め、!leave後の再接続を防ぐ。"""
    cancel_empty_timer(guild_id)

    task = AUDIO_TASK.pop(guild_id, None)
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    AUDIO_Q.pop(guild_id, None)

# =====================
# Commands
# =====================
@bot.command()
async def join(ctx):
    if not ctx.guild:
        await ctx.send("このコマンドはサーバーの中で使ってな。")
        return

    voice = getattr(ctx.author, "voice", None)
    if not voice or not voice.channel:
        await ctx.send("先にVC入ってから呼んでな。")
        return

    vc = voice.channel
    current = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if (
        STAY_VC.get(ctx.guild.id) == vc.id
        and current
        and current.is_connected()
        and current.channel.id == vc.id
    ):
        await ctx.send(f"もう {vc.name} におるで。")
        return

    STAY_VC[ctx.guild.id] = vc.id
    cancel_empty_timer(ctx.guild.id)

    await get_vc(ctx.guild, vc)
    await enqueue_audio(ctx.guild.id, vc.id, "file", JOIN_SE_PATH)
    await ctx.send(f"{vc.name} に常駐するで。")

@bot.command()
async def leave(ctx):
    if not ctx.guild:
        await ctx.send("このコマンドはサーバーの中で使ってな。")
        return

    STAY_VC.pop(ctx.guild.id, None)
    await stop_audio(ctx.guild.id)

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc:
        await vc.disconnect(force=True)

    await ctx.send("ほな、またな。")

# =====================
# おばちゃんへの呼びかけ
# =====================
@bot.event
async def on_message(message: discord.Message):
    # Bot同士の無限反応を防ぐ。
    if message.author.bot:
        return

    # !join / !leave などのコマンド処理は必ず残す。
    await bot.process_commands(message)

    if not message.guild:
        return

    gid = message.guild.id
    voice = getattr(message.author, "voice", None)
    channel = getattr(voice, "channel", None)
    stay = STAY_VC.get(gid)
    connected_vc = discord.utils.get(bot.voice_clients, guild=message.guild)
    bot_channel = getattr(connected_vc, "channel", None)

    # Botと同じVCに参加している人のメッセージだけを扱う。
    # Bot未接続、VC未参加、別VCからの投稿には返信も読み上げもしない。
    if (
        not connected_vc
        or not connected_vc.is_connected()
        or not isinstance(channel, discord.VoiceChannel)
        or not isinstance(bot_channel, discord.VoiceChannel)
        or channel.id != bot_channel.id
    ):
        return

    # 通常チャットは、!joinしたVCにいる人の投稿だけを読み上げる。
    # コマンドと「おばちゃん」への呼びかけは別処理にして二重読み上げを防ぐ。
    if not is_call(message.content):
        if message.content.strip().startswith("!"):
            return
        if stay and isinstance(channel, discord.VoiceChannel) and channel.id == stay:
            spoken = clean_for_tts(message.clean_content)
            if spoken:
                queued = await enqueue_audio(
                    gid,
                    stay,
                    "tts_full",
                    f"{plain_name(message.author)}、{spoken}",
                )
                if not queued:
                    with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                        await message.channel.send("いま読み上げが混み合っとるから、ちょっと待ってな。")
        return

    key = (gid, message.author.id)
    now = now_mono()
    if now - LAST_VC_TEXT_AT.get(key, 0) < VC_TEXT_COOLDOWN_SEC:
        return
    LAST_VC_TEXT_AT[key] = now

    body = strip_call(message.content)
    name = make_name(message.author)
    reply = await make_smart_obachan_reply(name, body)
    try:
        await message.reply(reply, mention_author=False)
    except (discord.Forbidden, discord.HTTPException) as e:
        print("[message_reply]", e)
        return

    queued = await enqueue_audio(gid, bot_channel.id, "tts_full", reply)
    if not queued:
        await message.channel.send("いま読み上げが混み合っとるから、ちょっと待ってな。")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CommandInvokeError):
        error = error.original
    print("[command_error]", error)
    with contextlib.suppress(discord.Forbidden, discord.HTTPException):
        await ctx.send("ごめんな、うまく動かんかった。少し待ってからもう一回試してな。")

# =====================
# VC 入退室
# =====================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    gid = member.guild.id
    stay = STAY_VC.get(gid)
    connected_vc = discord.utils.get(bot.voice_clients, guild=member.guild)
    watched_id = stay
    if not watched_id and connected_vc and connected_vc.is_connected():
        watched_id = connected_vc.channel.id

    if not watched_id:
        return

    # !joinで常駐中の時だけ、入退室メッセージを再生する。
    if stay:
        key = (gid, member.id)
        if now_mono() - LAST_VC_EVENT_AT.get(key, 0) >= VC_EVENT_COOLDOWN_SEC:
            LAST_VC_EVENT_AT[key] = now_mono()
            name = make_name(member)

            if before.channel is None and after.channel and after.channel.id == stay:
                await enqueue_audio(gid, stay, "tts_short", f"{name}来たん？")

            if before.channel and before.channel.id == stay and after.channel is None:
                await enqueue_audio(gid, stay, "tts_short", f"{name}おつかれ")

    guild = member.guild
    watched_ch = guild.get_channel(watched_id)
    if isinstance(watched_ch, discord.VoiceChannel):
        # !join中は人がいなくなっても退出しない。!leaveでのみ切断する。
        if stay:
            cancel_empty_timer(gid)
        elif non_bot_count(watched_ch) == 0:
            await schedule_empty_disconnect(gid, watched_id)
        else:
            cancel_empty_timer(gid)

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
