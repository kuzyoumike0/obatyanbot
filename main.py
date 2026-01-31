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
# トリガー判定：文頭「おばちゃん」で反応
# =====================
def has_call(text: str) -> bool:
    return text.strip().startswith("おばちゃん")

def strip_call(text: str) -> str:
    t = text.strip()
    return t[len("おばちゃん"):].strip() if t.startswith("おばちゃん") else t

# =====================
# ユーザー名（呼び名）生成
# - サーバーの表示名（nick）優先、無ければユーザー名
# - 長すぎる/記号だらけを軽く整える
# - 「〜ちゃん」「〜さん」を揺らす
# =====================
def make_call_name(member: discord.abc.User) -> str:
    # guild内ならdisplay_nameがニック優先になる
    name = getattr(member, "display_name", None) or getattr(member, "name", "あんた")

    # 余計な空白をまとめる
    name = re.sub(r"\s+", " ", name).strip()

    # 長すぎる時は短く
    if len(name) > 10:
        name = name[:10]

    # 記号だけ等のときの保険
    if not re.search(r"[A-Za-z0-9ぁ-んァ-ン一-龥]", name):
        name = "あんた"

    suffix = random.choice(["ちゃん", "さん", ""])
    return f"{name}{suffix}"

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

# 呼びかけテンプレ（ユーザー名を差し込む）
# 入れるときは 1行目 or 2行目 にだけ入れる（くどさ回避）
CALL_PREFIX = [
    "{name}、",
    "{name}な、",
    "{name}、ちょい聞きぃ、",
    "{name}、こっちおいで、",
]

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
# - user_name を自然に混ぜる（確率）
# =====================
def make_reply(category: str, call_name: str) -> str:
    # センシティブは安全優先、でも1行目だけ名前入れてもOK（確率低め）
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

    # ✅ ユーザー名呼び（入れすぎない：60%で1行だけ）
    if random.random() < 0.60:
        prefix = random.choice(CALL_PREFIX).format(name=call_name)
        # 1行目か2行目にだけ付ける（自然）
        if random.random() < 0.70:
            line1 = prefix + line1
        else:
            line2 = prefix + line2

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
        call_name = make_call_name(message.author)
        # 名前入りにすると可愛い（確率で）
        if random.random() < 0.60:
            await message.reply(f"{call_name}、どしたん？", mention_author=False)
        else:
            await message.reply("どしたん？", mention_author=False)
        return

    category = detect_category(body)
    call_name = make_call_name(message.author)

    reply = make_reply(category, call_name)
    await message.reply(reply, mention_author=False)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

bot.run(DISCORD_TOKEN)
