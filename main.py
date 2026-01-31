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

intents = discord.Intents.default()
intents.message_content = True  # Discord開発者ポータルでも Message Content Intent をONにする

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# おばちゃん人格
# =====================
AUNT_SYSTEM = """あなたは「知らないのにおせっかいで、でも優しいおばちゃんAI」。
口調：関西寄り（強すぎない）。距離感近め。
比率：優しさ5：ツッコミ4：正論1（説教はしない）。
得意：恋バナ、仕事の疲れケア、日常生活の基盤を見つけて褒める。
返答構成：
1) 共感・労い
2) 軽いツッコミ
3) 生活基盤ほめ
4) 小さい提案 or 質問（1つ）
長さ：必ず4行以内。各行短く。絵文字は最大1個。
禁止：差別・暴力扇動・個人情報の詮索。医療/法律は断定せず専門家案内。
"""

CATEGORY_GUIDE = {
    "love": "恋愛相談。甘やかし多め、相手の心を守る。最後に質問1つ。必ず4行以内。",
    "work_tired": "仕事疲れ（仕事+疲労）。労い最優先→軽いツッコミ→生活基盤ほめ→小休憩提案。最後に質問1つ。必ず4行以内。",
    "work": "仕事の悩み。正論最小、逃げ道1つ。最後に質問1つ。必ず4行以内。",
    "tired": "疲労・メンタル。体調気遣い最優先。最後に質問1つ。必ず4行以内。",
    "life": "生活・家事。できてる所を具体的に褒める。最後に質問1つ。必ず4行以内。",
    "general": "雑談。おせっかいおばちゃんで軽く。最後に質問1つ。必ず4行以内。",
}

AUNT_FALLBACK_BY_CATEGORY = {
    "love": [
        "それ好きやん、もう顔に出てるで。\n考えすぎるほど真剣ってことや。\nちゃんと日常回してるのも偉い。\n今いちばん不安なん、どこ？"
    ],
    "work_tired": [
        "仕事で疲れ切ってるやん、今日もよう耐えた。\nツッコミ：それ休み無しはアカン！\n帰ってこれてる時点で基盤は合格。\n今つらいのは人？量？"
    ],
    "work": [
        "仕事おつかれさん、生きて帰っただけで勝ち。\n真面目すぎるのが裏目出てるな。\nでも日常回せてるのは立派。\n一個だけ減らすなら何？"
    ],
    "tired": [
        "しんどい中で声出せたの偉い。\n根性論は今日は休みや。\n水分かご飯、どっちか入れよ。\n今眠れそう？"
    ],
    "life": [
        "生活ちゃんと維持してるやん。\n完璧目指すと家事が敵になるで。\n基盤できてるのが一番強い。\nどこ手抜きする？"
    ],
    "general": [
        "うんうん、聞いたるで。\n考えすぎて肩ガチガチちゃう？\nでも日常進めてるのは偉い。\n何が一番ひっかかってる？"
    ],
}

# =====================
# 呼びかけトリガー
# 「おばちゃん○○」が含まれる時だけ反応
# =====================
CALL_PATTERN = re.compile(r"(おばちゃん)(\S+)")

def has_call(text: str) -> bool:
    return bool(CALL_PATTERN.search(text))

def strip_call(text: str) -> str:
    # 最初に見つかった「おばちゃん○○」だけ消す（本文を優先）
    return CALL_PATTERN.sub("", text, count=1).strip()

def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())

def detect_category(text: str) -> str:
    t = normalize(text)

    love = ["好き", "恋", "彼氏", "彼女", "既読", "未読", "告白", "デート", "脈", "別れ"]
    work = ["仕事", "会社", "上司", "部下", "同僚", "残業", "会議", "転職", "納期", "クレーム"]
    tired = ["疲れ", "しんど", "つら", "無理", "限界", "眠", "寝れ", "だる", "ストレス", "不安", "消えたい", "しにたい"]
    life = ["生活", "家事", "掃除", "洗濯", "料理", "自炊", "ご飯", "風呂", "片付け", "習慣", "貯金", "節約"]

    is_love = any(k in t for k in love)
    is_work = any(k in t for k in work)
    is_tired = any(k in t for k in tired)
    is_life = any(k in t for k in life)

    # 優先度：恋愛 > 仕事疲れ(複合) > 仕事 > 疲れ > 生活 > その他
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
    return "\n".join(lines[:4]) if lines else text.strip()

# =====================
# 短期記憶：直近3往復（= 最大6発言）
# チャンネル単位で保持
# =====================
memory_by_channel = defaultdict(lambda: deque(maxlen=6))

def add_memory(ch_id: int, role: str, content: str):
    if content:
        memory_by_channel[ch_id].append((role, content))

def build_openai_input(ch_id: int, system_text: str, user_text: str):
    msgs = [{"role": "system", "content": system_text}]
    for role, content in memory_by_channel[ch_id]:
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    # ✅ 呼びかけが無ければ完全無視
    if not has_call(message.content):
        return

    # 呼びかけ部分を除去して本文を作る
    user_text = strip_call(message.content)
    if not user_text:
        # 本文が空なら、元メッセージをそのまま使う
        user_text = message.content.strip()

    category = detect_category(user_text)

    # まずユーザー発言を記憶
    add_memory(message.channel.id, "user", user_text)

    # OpenAIなし or 失敗時の定型返し
    if not (OPENAI_API_KEY and OpenAI):
        out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Responses API（新規はこれ推奨）
    system_text = AUNT_SYSTEM + "\n" + CATEGORY_GUIDE.get(category, CATEGORY_GUIDE["general"]) + "\n出力は必ず4行以内。"

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=build_openai_input(message.channel.id, system_text, user_text),
        )
        out = resp.output_text.strip() if hasattr(resp, "output_text") else ""
        if not out:
            out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])

        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)

    except Exception as e:
        print("OpenAI error:", e)
        out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

bot.run(DISCORD_TOKEN)
