import os
import random
import re
import discord
from discord.ext import commands

# =====================
# ENV
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_LOG = os.getenv("DEBUG_LOG", "0") == "1"  # Railwayで1にするとログが増える

# =====================
# Intents（重要）
# - message_content: 本文取得に必須（DevPortalでもON）
# - guilds: チャンネル周り安定
# - members: 表示名（ニック）安定（DevPortalでMembers intentが必要な場合あり）
# =====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# トリガー：文頭「おばちゃん」で反応
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
# カテゴリ判定
# =====================
def detect_category(text: str) -> str:
    t = text

    # センシティブ（最低限）
    if any(k in t for k in ["死にたい", "消えたい", "自殺", "自傷", "切りたい"]):
        return "sensitive"

    # 仕事疲れを優先（work+tired）
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
# 返信（VCチャットがスレッド扱いでも落ちないように）
# =====================
async def safe_respond(message: discord.Message, text: str):
    # replyが通らない環境があるのでフォールバック付き
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
# 人間臭さパーツ
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
    # センシティブは専用
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

# =====================
# Discord events
# =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id})")

    # DEBUG: Botが見えてるチャンネル確認（必要なら）
    if DEBUG_LOG and bot.guilds:
        for g in bot.guilds:
            print("GUILD:", g.name)
            # 見えてるチャンネルだけ表示
            for ch in g.channels:
                try:
                    perms = ch.permissions_for(g.me)
                    if perms.view_channel:
                        print("  CAN VIEW:", ch.name, type(ch).__name__)
                except Exception:
                    pass

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # DEBUG: VCチャット(スレッド含む)で拾えてるか判定
    if DEBUG_LOG:
        print(
            "GOT:",
            getattr(message.guild, "name", None),
            "|",
            getattr(message.channel, "name", str(message.channel)),
            "|",
            type(message.channel).__name__,
            "|",
            repr(message.content),
        )

    if not has_call(message.content):
        return

    body = strip_call(message.content)

    # 「おばちゃん」だけ
    if body == "":
        call_name = make_call_name(message.author)
        if random.random() < 0.60:
            await safe_respond(message, f"{call_name}、どしたん？")
        else:
            await safe_respond(message, "どしたん？")
        return

    category = detect_category(body)
    call_name = make_call_name(message.author)
    reply = make_reply(category, call_name)

    await safe_respond(message, reply)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

bot.run(DISCORD_TOKEN)
