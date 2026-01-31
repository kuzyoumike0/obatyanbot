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

# モデルは必要に応じて変更OK
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

intents = discord.Intents.default()
intents.message_content = True  # Discord Developer Portalでも Message Content Intent をON

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# 返答トリガー：チャット内に「おばちゃん○○」がある時だけ
# 例）おばちゃん相談 / おばちゃん聞いて / おばちゃん恋バナ
# =====================
CALL_PATTERN = re.compile(r"(おばちゃん)(\S+)")

def has_call(text: str) -> bool:
    return bool(CALL_PATTERN.search(text))

def strip_call(text: str) -> str:
    # 最初に見つかった「おばちゃん○○」だけ消して本文を優先
    return CALL_PATTERN.sub("", text, count=1).strip()

def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())

# =====================
# センシティブ判定（やさしく誘導）
# =====================
SENSITIVE_KEYWORDS = [
    # 希死念慮・自傷
    "死にたい", "消えたい", "自殺", "自傷", "切りたい", "終わりたい", "楽になりたい",
    # 極端な絶望・孤立
    "もう無理", "限界", "誰もいない", "ひとりぼっち", "助けて", "耐えられない",
    # 暴力・支配・DV
    "殴られ", "蹴られ", "暴力", "dv", "監視", "支配", "脅され", "怒鳴られ",
    # 強い怒り（他害・暴走）
    "殺す", "ぶっ殺す", "許さない", "ぶち壊す",
]

def is_sensitive(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in SENSITIVE_KEYWORDS)

SENSITIVE_FALLBACK = [
    "…それ、相当しんどかったんやな。\nここで話してくれてありがとう。\n一人で抱えんでええで、まず呼吸しよ。\n今、安全な場所におる？",
    "そんな気持ちになるほど追い込まれてたんやね。\n否定せぇへん、あんたのせいって決めつけん。\n今日は休む準備だけでええ。\n近くの信頼できる人に繋がれそう？",
]

SENSITIVE_SYSTEM_APPEND = """
【センシティブ対応】
この相談はセンシティブ（希死念慮/自傷/暴力/DV/強い絶望/他害など）に該当する可能性が高い。
- 否定・説教・正論は禁止
- 具体的な手段・方法・成功率などには触れない
- 共感と安心を最優先
- 安全確認（今安全か）や休息提案を1つだけ
- 必要なら「信頼できる人/専門窓口/緊急時は地域の緊急番号」などにやさしく誘導
- 必ず4行以内
"""

# =====================
# おばちゃん人格（4行縛り＋優しさ5:ツッコミ4:正論1）
# =====================
AUNT_SYSTEM = """あなたは「知らないのにおせっかいで、でも優しいおばちゃんAI」。
口調：関西寄り（強すぎない）。距離感近め。語尾に「〜やで」「〜やん」「〜しよか」など。
比率：優しさ5：ツッコミ4：正論1（正論は最小限、説教はしない）。
得意：恋バナ、仕事の疲れへの労い、日常生活の基盤（起きてる/働いてる/ご飯食べた/風呂入った等）を見つけて褒める。
スタンス：「知らんけど」は使ってよいが、投げやりにしない。相手の気持ちを先に受け止めてから軽くツッコむ。
返答の型：
1) 共感・労い（短く）
2) ツッコミ（軽く笑える範囲）
3) 生活基盤ほめ（できてる部分を具体的に）
4) 小さい提案 or 確認質問（1つだけ）
長さ：必ず4行以内。各行は短め。絵文字は控えめ（最大1個）。
禁止：差別・暴力扇動・個人情報の詮索。医療/法律は断定せず専門家案内。
【センシティブ対応ルール】
もし希死念慮/自傷/強い絶望/DV/暴力/他害/パニック等が含まれる場合は、
否定や説教をせず、具体的な方法には触れず、安心と安全確認を優先し、必要なら相談先へやさしく誘導する。
必ず4行以内。
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
# カテゴリ判定：恋愛 > 仕事疲れ(複合) > 仕事 > 疲れ > 生活 > その他
# =====================
def detect_category(text: str) -> str:
    t = normalize(text)

    love = ["好き", "恋", "彼氏", "彼女", "既読", "未読", "告白", "デート", "脈", "別れ", "付き合"]
    work = ["仕事", "会社", "上司", "部下", "同僚", "残業", "会議", "転職", "納期", "クレーム", "シフト", "評価", "ブラック"]
    tired = ["疲れ", "しんど", "つら", "無理", "限界", "眠", "寝れ", "だる", "ストレス", "不安", "メンタル"]
    life = ["生活", "家事", "掃除", "洗濯", "料理", "自炊", "ご飯", "風呂", "片付け", "習慣", "貯金", "節約", "ルーティン"]

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
    # 4行を超えたらカット（空行は除外）
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines[:4]) if lines else text.strip()

# =====================
# 短期記憶：直近3往復（最大6発言）
# チャンネル単位で保持（必要なら user×channel にもできる）
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

# =====================
# Discord events
# =====================
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
        user_text = message.content.strip()

    # センシティブ判定
    sensitive = is_sensitive(user_text)

    # カテゴリ（センシティブならカテゴリより優先）
    category = detect_category(user_text)

    # ユーザー発言を短期記憶に追加
    add_memory(message.channel.id, "user", user_text)

    # OpenAIが使えない時の返答
    if not (OPENAI_API_KEY and OpenAI):
        if sensitive:
            out = random.choice(SENSITIVE_FALLBACK)
        else:
            out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)
        return

    # OpenAI 呼び出し
    client = OpenAI(api_key=OPENAI_API_KEY)

    # system text 構築（センシティブ優先）
    system_text = AUNT_SYSTEM + "\n"
    if sensitive:
        system_text += SENSITIVE_SYSTEM_APPEND + "\n"
    else:
        system_text += CATEGORY_GUIDE.get(category, CATEGORY_GUIDE["general"]) + "\n"
    system_text += "出力は必ず4行以内。4行を超えそうなら短くまとめる。\n"

    try:
        resp = client.responses.create(
            model=OPENAI_MODEL,
            input=build_openai_input(message.channel.id, system_text, user_text),
        )
        out = resp.output_text.strip() if hasattr(resp, "output_text") else ""
        if not out:
            out = random.choice(SENSITIVE_FALLBACK if sensitive else AUNT_FALLBACK_BY_CATEGORY[category])

        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)

    except Exception as e:
        print("OpenAI error:", e)
        out = random.choice(SENSITIVE_FALLBACK if sensitive else AUNT_FALLBACK_BY_CATEGORY[category])
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it in environment variables.")

bot.run(DISCORD_TOKEN)
