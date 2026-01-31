import os
import random
import re
import discord
from discord.ext import commands

# OpenAIを使う場合だけ必要（OPENAI_API_KEYが無ければ“おばちゃん定型返し”モードで動く）
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

intents = discord.Intents.default()
intents.message_content = True  # Discord開発者ポータルでも Message Content Intent をONにする

bot = commands.Bot(command_prefix="!", intents=intents)

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
長さ：1〜5行。絵文字は控えめ（最大1個）。
禁止：差別・暴力扇動・個人情報の詮索。医療/法律は断定せず専門家案内。
"""

# カテゴリ別の“追加ノリ”指示（OpenAIに渡す）
CATEGORY_GUIDE = {
    "love": "これは恋愛相談。甘やかし多め、軽いツッコミ、相手の心を守る方向で。最後に1つだけ質問。",
    "work": "これは仕事の疲れ/愚痴。労い最優先、逃げ道や小休憩の提案を1つだけ。正論は最小。",
    "tired": "これは疲労・メンタルしんどい。まず体調と睡眠・水分・食事を気遣い、優しさ多め。最後に短い提案か質問。",
    "life": "これは日常生活（家事/生活習慣/自己管理）。できてる基盤を具体的に褒めて、手間が減る小技を1つ。",
    "general": "雑談/その他。おせっかいおばちゃんとして、軽く受け止めてツッコミ。最後に1つ質問。",
}

AUNT_FALLBACK_BY_CATEGORY = {
    "love": [
        "それ、好きやん。はい認めよか。で、相手とは今どんな距離感なん？",
        "焦らんでええ、恋は逃げへん…たぶん。連絡の頻度、今どれくらい？",
        "気持ち大事にしぃや。相手の反応で一喜一憂してへん？",
    ],
    "work": [
        "今日もよう頑張ったな…。まず水飲み。ほんで、何が一番しんどい？人？量？",
        "仕事ってな、心削ってまでやるもんちゃうで？今いちばん嫌なんどれ？",
        "えらい、ちゃんと働いて帰ってきた時点で勝ち。明日ラクにする一手考えよか。",
    ],
    "tired": [
        "しんどい時は正解探さんでええ。ご飯と水、取れてる？",
        "今日は“最低限できた”で十分やで。まず寝れる準備しよか。",
        "無理して強がらんでええ。今の体力、何割くらい？",
    ],
    "life": [
        "生活ちゃんと回してるやん、偉いで。今いちばん面倒なんどれ？",
        "基盤できてるのが一番強い。ご飯・風呂・寝る、ここ守れたら勝ちや。",
        "やれてるとこ、ちゃんと数えよ。今週“できた”こと一個言うて？",
    ],
    "general": [
        "知らんけど！…って言う前に聞くわ。今なにが一番気になってんの？",
        "ちょっと待ちぃ、整理しよか。要するに何が困りごと？",
        "ほらほら、深呼吸。で、結局どうしたいん？",
    ],
}

def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())

def detect_category(text: str) -> str:
    t = normalize(text)

    # 恋愛
    love_kw = [
        "好き", "恋", "彼氏", "彼女", "片想い", "片思い", "告白", "デート", "line",
        "返信", "既読", "未読", "脈", "別れ", "別れた", "元カレ", "元カノ", "付き合"
    ]
    # 仕事
    work_kw = [
        "仕事", "会社", "上司", "部下", "同僚", "残業", "出社", "退社", "転職", "会議",
        "クレーム", "納期", "シフト", "バイト", "給料", "評価", "ブラック"
    ]
    # 疲れ/メンタル
    tired_kw = [
        "疲れ", "しんど", "つら", "無理", "限界", "泣", "眠", "寝れ", "だる", "メンタル",
        "不安", "ストレス", "しにたい", "消えたい"
    ]
    # 生活
    life_kw = [
        "生活", "家事", "掃除", "洗濯", "料理", "自炊", "ご飯", "風呂", "片付け",
        "体調管理", "運動", "早起き", "習慣", "貯金", "節約", "ルーティン"
    ]

    # 判定優先度：恋愛 > 仕事 > 疲れ > 生活（※「仕事疲れ」は仕事が拾いやすい）
    if any(k in t for k in love_kw):
        return "love"
    if any(k in t for k in work_kw):
        return "work"
    if any(k in t for k in tired_kw):
        return "tired"
    if any(k in t for k in life_kw):
        return "life"
    return "general"

def should_reply(message: discord.Message) -> bool:
    # Botへのメンション、またはキーワードで反応
    if bot.user in message.mentions:
        return True

    text = message.content
    triggers = ["おばちゃん", "お節介", "相談", "助けて", "たすけて", "聞いて", "しんどい", "疲れた"]
    return any(t in text for t in triggers)

@bot.event
async def on_ready():
    print(f"Logged in as: {bot.user} (id={bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if not should_reply(message):
        return

    user_text = message.content
    category = detect_category(user_text)

    # OpenAIキーが無ければ、カテゴリ別定型返し
    if not (OPENAI_API_KEY and OpenAI):
        await message.reply(random.choice(AUNT_FALLBACK_BY_CATEGORY[category]), mention_author=False)
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    # カテゴリ別の追加指示
    extra = CATEGORY_GUIDE.get(category, CATEGORY_GUIDE["general"])
    system_text = AUNT_SYSTEM + "\n" + f"【今回の相談カテゴリ】{category}\n【追加指示】{extra}\n"

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
        )
        out = resp.output_text.strip() if hasattr(resp, "output_text") else ""
        if not out:
            out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])

        await message.reply(out[:1500], mention_author=False)

    except Exception as e:
        print("OpenAI error:", e)
        await message.reply(random.choice(AUNT_FALLBACK_BY_CATEGORY[category]), mention_author=False)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it as an environment variable.")

bot.run(DISCORD_TOKEN)
