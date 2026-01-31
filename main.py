import os
import random
import re
import asyncio
import uuid
import discord
from discord.ext import commands

# =====================
# ENV
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_LOG = os.getenv("DEBUG_LOG", "0") == "1"

# TTS設定（無料：edge-tts）
TTS_VOICE = os.getenv("TTS_VOICE", "ja-JP-NanamiNeural")  # 例: ja-JP-KeitaNeural
TTS_RATE = os.getenv("TTS_RATE", "+5%")                   # 少し早口
TTS_VOLUME = os.getenv("TTS_VOLUME", "+0%")               # 例: "+10%"

# =====================
# Intents（重要）
# =====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# サーバーごとの読み上げロック（連投でVC再生が被らないように）
_guild_locks: dict[int, asyncio.Lock] = {}

# =====================
# トリガー：文頭「おばちゃん」
# =====================
def has_call(text: str) -> bool:
    return text.strip().startswith("おばちゃん")

def strip_call(text: str) -> str:
    t = text.strip()
    return t[len("おばちゃん"):].strip() if t.startswith("おばちゃん") else t

# =====================
# ユーザー名呼び（ニック優先）
# =====================
def make_call_name(author: discord.abc.User) -> str:
    name = getattr(author, "display_name", None) or getattr(author, "name", "あんた")
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 10:
        name = name[:10]
    if not re.search(r"[A-Za-z0-9ぁ-んァ-ン一-龥]", name):
        name = "あんた"
    suffix = random.choice(["ちゃん", "さん", ""])
    return f"{name}{suffix}"

# =====================
# カテゴリ判定（work+tired優先）
# =====================
def detect_category(text: str) -> str:
    t = text

    # センシティブ（最低限の誘導）
    if any(k in t for k in ["死にたい", "消えたい", "自殺", "自傷", "切りたい"]):
        return "sensitive"

    is_work = any(k in t for k in ["仕事", "会社", "上司", "残業", "会議", "納期"])
    is_tired = any(k in t for k in ["疲れ", "しんど", "無理", "限界", "眠", "だる", "つらい"])
    if is_work and is_tired:
        return "work_tired"

    if any(k in t for k in ["好き", "恋", "彼氏", "彼女", "既読", "未読", "告白"]):
        return "love"
    if is_work:
        return "work"
    if is_tired:
        return "tired"
    if any(k in t for k in ["家事", "生活", "掃除", "洗濯", "ご飯", "風呂", "片付け"]):
        return "life"
    return "general"

# =====================
# 返信（テキスト）
# =====================
TAILS = ["やで", "やん", "しよか", "せやな", "ほな", "大丈夫や"]
PAUSES = ["…", ""]
EMOJIS = ["", "🙂"]

CALL_PREFIX = [
    "{name}、",
    "{name}な、",
    "{name}、ちょい聞きぃ、",
    "{name}、こっちおいで、",
]

EMPATHY = ["それはしんどかったな", "よう言うてくれたな", "大変やったんやな"]
TSUKKOMI = ["無理しすぎやで", "抱え込みすぎやん", "根性論では乗り切れん話や"]
BASE_PRAISE = [
    "でもここに書けてるのは偉い",
    "今日も生きてるのは立派や",
    "呼びかけられた時点で基盤は残ってる",
]
SUGGEST = ["今は深呼吸だけでええで", "水かご飯、どっちか入れよ", "今日は最低限で済ませよ"]

CATEGORY_ADDON = {
    "work_tired": "仕事で削られてるやん、今日は最低限でええ",
    "work": "仕事は全部背負わんでええ",
    "tired": "今日は休む日やと思ってええ",
    "love": "それ、気持ちがちゃんと動いてる証拠や",
    "life": "生活回してるだけで十分や",
}

SENSITIVE_REPLY = [
    [
        "…それ、相当しんどかったんやな",
        "ここで話してくれてありがとう",
        "一人で抱えんでええで",
        "今、安全な場所におる？",
    ],
    [
        "そこまで追い込まれてたんやね",
        "否定せぇへん、責めへんで",
        "今日は休む準備だけでええ",
        "誰か頼れる人おる？",
    ],
]

def make_reply(category: str, call_name: str) -> str:
    if category == "sensitive":
        lines = random.choice(SENSITIVE_REPLY).copy()
        if random.random() < 0.25:
            lines[0] = random.choice(CALL_PREFIX).format(name=call_name) + lines[0]
        return "\n".join(lines)

    tail = random.choice(TAILS)
    pause = random.choice(PAUSES)
    emoji = random.choice(EMOJIS)

    line1 = random.choice(EMPATHY) + pause + tail
    line2 = (CATEGORY_ADDON.get(category) or random.choice(TSUKKOMI)) + tail
    line3 = random.choice(BASE_PRAISE) + tail
    line4 = random.choice(SUGGEST) + tail + emoji

    # ユーザー名呼び（入れすぎない）
    if random.random() < 0.60:
        prefix = random.choice(CALL_PREFIX).format(name=call_name)
        if random.random() < 0.70:
            line1 = prefix + line1
        else:
            line2 = prefix + line2

    # 4行固定
    return "\n".join([line1, line2, line3, line4])

async def safe_respond(message: discord.Message, text: str):
    try:
        await message.reply(text, mention_author=False)
        return
    except Exception as e:
        if DEBUG_LOG:
            print("[safe_respond] reply failed:", repr(e))
    try:
        await message.channel.send(text)
    except Exception as e:
        print("[safe_respond] send failed:", repr(e))

# =====================
# TTS（全文読み上げ：edge-tts）
# =====================
def to_speakable_text(full_reply: str) -> str:
    """
    4行を「句点＋間」で読みやすく整形して全文読み上げ。
    VC荒らし対策として、超長文化しないよう軽く制限。
    """
    lines = [l.strip() for l in full_reply.split("\n") if l.strip()]
    lines = lines[:4]

    # 読み上げ用にちょい整形
    speak = "。 ".join(lines)

    # 長すぎるとTTSが重いので上限（安全策）
    if len(speak) > 220:
        speak = speak[:220] + "…"
    return speak

async def tts_to_mp3(text: str, out_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(
        text=text,
        voice=TTS_VOICE,
        rate=TTS_RATE,
        volume=TTS_VOLUME,
    )
    await communicate.save(out_path)

async def get_or_connect_vc(guild: discord.Guild, channel: discord.VoiceChannel) -> discord.VoiceClient:
    vc: discord.VoiceClient | None = discord.utils.get(bot.voice_clients, guild=guild)
    if vc and vc.is_connected():
        if vc.channel and vc.channel.id != channel.id:
            await vc.move_to(channel)
        return vc
    return await channel.connect(timeout=10)

async def play_mp3(vc: discord.VoiceClient, mp3_path: str):
    """
    FFmpegでmp3を再生。終わるまで待つ。
    """
    done = asyncio.Event()

    def after_play(err):
        if err:
            print("[VC] play error:", err)
        done.set()

    source = discord.FFmpegPCMAudio(mp3_path)
    vc.play(source, after=after_play)
    await done.wait()

async def speak_in_sender_vc(member: discord.Member, full_reply: str) -> tuple[bool, str | None]:
    """
    送信者のいるVCに入って、返答全文を読み上げ、終わったら退出。
    """
    if not member.voice or not member.voice.channel:
        return False, "VC入ってへんやん？ 先に入ってから呼んでな。"

    voice_channel = member.voice.channel
    guild = member.guild
    lock = _guild_locks.setdefault(guild.id, asyncio.Lock())

    async with lock:
        vc: discord.VoiceClient | None = None
        tmp_name = f"tts_{uuid.uuid4().hex}.mp3"
        try:
            vc = await get_or_connect_vc(guild, voice_channel)

            speak_text = to_speakable_text(full_reply)
            if DEBUG_LOG:
                print("[TTS] speak:", speak_text)

            await tts_to_mp3(speak_text, tmp_name)
            await play_mp3(vc, tmp_name)
            return True, None

        except Exception as e:
            # ここで落ちるのはだいたい「権限」か「ffmpeg無し」か「PyNaCl無し」
            return False, f"喋れんかったわ…（権限/ffmpeg/環境）: {e}"

        finally:
            try:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
            except Exception:
                pass

            # 毎回退出（常駐させたいならここを消す）
            try:
                if vc and vc.is_connected():
                    await vc.disconnect(force=True)
            except Exception:
                pass

# =====================
# Events
# =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if DEBUG_LOG:
        print("GOT:", getattr(message.channel, "name", str(message.channel)), "|", repr(message.content))

    if not has_call(message.content):
        return

    body = strip_call(message.content)
    call_name = make_call_name(message.author)

    # 「おばちゃん」だけ
    if body == "":
        reply = f"{call_name}、どしたん？"
        await safe_respond(message, reply)

        ok, err = await speak_in_sender_vc(message.author, reply + "\n" + "無理せんでええで。\n" + "呼んだ時点で偉い。\n" + "今、何が一番しんどい？")
        if (not ok) and err:
            await safe_respond(message, err)
        return

    category = detect_category(body)
    reply = make_reply(category, call_name)

    # テキスト返信
    await safe_respond(message, reply)

    # VCで全文読み上げ
    ok, err = await speak_in_sender_vc(message.author, reply)
    if (not ok) and err:
        await safe_respond(message, err)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

bot.run(DISCORD_TOKEN)
