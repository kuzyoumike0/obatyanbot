import os
import random
import re
import discord
from discord.ext import commands

# =====================
# Discord設定
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# トリガー判定
# 文頭「おばちゃん」で反応
# =====================
def has_call(text: str) -> bool:
    return text.strip().startswith("おばちゃん")

def strip_call(text: str) -> str:
    t = text.strip()
    return t[len("おばちゃん"):].strip() if t.startswith("おばちゃん") else t

# =====================
# カテゴリ判定
# =====================
def detect_category(text: str) -> str:
    t = text

    if any(k in t for k in ["死にたい", "消えたい", "自殺", "自傷"]):
        return "sensitive"
    if any(k in t for k in ["疲れ", "しんど", "無理", "限界"]):
        return "tired"
    if any(k in t for k in ["仕事", "会社", "上司", "残業"]):
        return "work"
    if any(k in t for k in ["好き", "恋", "彼氏", "彼女"]):
        return "love"
    if any(k in t for k in ["家事", "生活", "掃除", "洗濯", "ご飯", "風呂"]):
        return "life"
    return "general"

# =====================
# 人間臭さパーツ
# =====================
TAILS = ["やで", "やん", "しよか", "せやな", "ほな", "大丈夫や"]
PAUSES = ["…", ""]
EMOJIS = ["", "🙂"]

EMPATHY = [
    "それはしんどかったな",
    "よう言うてくれたな",
    "大変やったんやな",
]

TSUKKOMI = [
    "無理しすぎやで",
    "抱え込みすぎやん",
    "根性論では乗り切れん話や",
]

BASE_PRAISE = [
    "でもここに書けてるのは偉い",
    "今日も生きてるのは立派や",
    "呼びかけられた時点で基盤は残ってる",
]

SUGGEST = [
    "今は深呼吸だけでええで",
    "水かご飯、どっちか入れよ",
    "今日は最低限で済ませよ",
]

CATEGORY_ADDON = {
    "tired": "今日は休む日やと思ってええ",
    "work": "仕事は全部背負わんでええ",
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

# =====================
# 返答生成（4行固定）
# =====================
def make_reply(category: str) -> str:
    if category == "sensitive":
        return "\n".join(random.choice(SENSITIVE_REPLY))

    tail = random.choice(TAILS)
    pause = random.choice(PAUSES)
    emoji = random.choice(EMOJIS)

    line1 = random.choice(EMPATHY) + pause + tail
    line2 = (CATEGORY_ADDON.get(category) or random.choice(TSUKKOMI)) + tail
    line3 = random.choice(BASE_PRAISE) + tail
    line4 = random.choice(SUGGEST) + tail + emoji

    return "\n".join([line1, line2, line3, line4])

# =====================
# Discordイベント
# =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not has_call(message.content):
        return

    body = strip_call(message.content)

    # 「おばちゃん」だけ
    if body == "":
        await message.reply("どしたん？", mention_author=False)
        return

    category = detect_category(body)
    reply = make_reply(category)
    await message.reply(reply, mention_author=False)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

bot.run(DISCORD_TOKEN)
