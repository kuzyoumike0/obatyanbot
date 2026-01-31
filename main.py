import os
import random
import re
from collections import deque, defaultdict

import discord
from discord.ext import commands

# OpenAI（無ければ定型返し）
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

intents = discord.Intents.default()
intents.message_content = True  # Discord Developer PortalでもONにする

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# トリガー判定
# =====================
def has_call(text: str) -> bool:
    return text.strip().startswith("おばちゃん")

def strip_call(text: str) -> str:
    t = text.strip()
    if t.startswith("おばちゃん"):
        return t[len("おばちゃん"):].strip()
    return t

# =====================
# センシティブ判定
# =====================
SENSITIVE_KEYWORDS = [
    "死にたい", "消えたい", "自殺", "自傷", "切りたい",
    "もう無理", "限界", "誰もいない", "ひとりぼっち",
    "殴られ", "蹴られ", "暴力", "dv", "支配", "監視",
    "殺す", "ぶっ殺す"
]

def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())

def is_sensitive(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in SENSITIVE_KEYWORDS)

SENSITIVE_FALLBACK = [
    "…それ、相当しんどかったんやな。\nここで話してくれてありがとう。\n一人で抱えんでええで。\n今、安全な場所におる？",
    "そこまで追い込まれてたんやね。\n否定せぇへん、あんたは悪くない。\n今日は休む準備だけでええ。\n誰か信頼できる人に繋がれそう？",
]

SENSITIVE_SYSTEM_APPEND = """
【センシティブ対応】
否定・説教は禁止。具体的な方法には触れない。
共感と安心を最優先し、安全確認や相談先への誘導を1つだけ。
必ず4行以内。
"""

# =====================
# おばちゃん人格
# =====================
AUNT_SYSTEM = """あなたは「知らないのにおせっかいで、でも優しいおばちゃんAI」。
口調：関西寄り（強すぎない）。距離感近め。
比率：優しさ5：ツッコミ4：正論1（説教しない）。
得意：恋バナ、仕事疲れケア、生活基盤（起きてる/働いてる/食べた/風呂）を褒める。
返答構成：
1) 共感
2) 軽いツッコミ
3) 生活基盤ほめ
4) 小さい提案 or 質問（1つ）
長さ：必ず4行以内。各行短く。
"""

CATEGORY_GUIDE = {
    "love": "恋愛相談。甘やかし多め。最後に質問1つ。必ず4行以内。",
    "work_tired": "仕事疲れ。労い最優先→基盤ほめ→小休憩提案。必ず4行以内。",
    "work": "仕事の悩み。正論最小。必ず4行以内。",
    "tired": "疲労・メンタル。体調気遣い最優先。必ず4行以内。",
    "life": "生活・家事。できてる所を具体的に褒める。必ず4行以内。",
    "general": "雑談。おせっかいおばちゃんで軽く。必ず4行以内。",
}

AUNT_FALLBACK_BY_CATEGORY = {
    "love": ["それ好きやん。\n真剣な証拠やで。\nちゃんと日常回してるの偉い。\n何が一番不安？"],
    "work_tired": ["仕事で疲れ切ってるやん。\nよう耐えたな。\n帰れてる時点で合格。\n人と量、どっちがしんどい？"],
    "work": ["仕事おつかれ。\n真面目すぎるんや。\nでも生活回せてるの立派。\n一個減らすなら何？"],
    "tired": ["しんどかったな。\n無理せんでええ。\n水かご飯どっちか取ろ。\n今眠れそう？"],
    "life": ["生活ちゃんと回ってるやん。\n完璧いらんで。\n基盤できてるの強い。\nどこ手抜きする？"],
    "general": ["聞いたるで。\n考えすぎちゃう？\n今日進めてるの偉い。\n何が一番気になる？"],
}

# =====================
# カテゴリ判定
# =====================
def detect_category(text: str) -> str:
    t = normalize(text)
    love = ["好き", "恋", "彼氏", "彼女", "既読", "未読"]
    work = ["仕事", "会社", "残業", "上司", "会議"]
    tired = ["疲れ", "しんど", "無理", "限界", "眠"]
    life = ["生活", "家事", "掃除", "洗濯", "ご飯", "風呂"]

    is_love = any(k in t for k in love)
    is_work = any(k in t for k in work)
    is_tired = any(k in t for k in tired)
    is_life = any(k in t for k in life)

    if is_love:
        return "love"
    if is_work and is_tired:
        return "work_tired"
    if is_work:
        return "work"
    if is_tired:
        return "tired"
    if is_life:
        return "life"
    return "general"

def enforce_4_lines(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines[:4])

# =====================
# 短期記憶（3往復）
# =====================
memory_by_channel = defaultdict(lambda: deque(maxlen=6))

def add_memory(ch_id, role, content):
    if content:
        memory_by_channel[ch_id].append((role, content))

def build_openai_input(ch_id, system_text, user_text):
    msgs = [{"role": "system", "content": system_text}]
    for role, content in memory_by_channel[ch_id]:
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs

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

    await bot.process_commands(message)

    # 呼びかけなければ無視
    if not has_call(message.content):
        return

    raw = strip_call(message.content)

    # ✅ 初期リアクション：「おばちゃん」だけ
    if raw == "":
        await message.reply("どしたん？", mention_author=False)
        return

    user_text = raw
    category = detect_category(user_text)
    sensitive = is_sensitive(user_text)

    add_memory(message.channel.id, "user", user_text)

    # OpenAIなし
    if not (OPENAI_API_KEY and OpenAI):
        out = random.choice(
            SENSITIVE_FALLBACK if sensitive else AUNT_FALLBACK_BY_CATEGORY[category]
        )
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    system_text = AUNT_SYSTEM + "\n"
    if sensitive:
        system_text += SENSITIVE_SYSTEM_APPEND
    else:
        system_text += CATEGORY_GUIDE[category]
    system_text += "\n必ず4行以内で返答する。\n"

    try:
        resp = client.responses.create(
            model=OPENAI_MODEL,
            input=build_openai_input(message.channel.id, system_text, user_text),
        )
        out = resp.output_text.strip()
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)

    except Exception as e:
        print("OpenAI error:", e)
        out = random.choice(
            SENSITIVE_FALLBACK if sensitive else AUNT_FALLBACK_BY_CATEGORY[category]
        )
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

bot.run(DISCORD_TOKEN)
