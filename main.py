import os
import random
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
intents.message_content = True  # ← これに加えてDiscord開発者ポータルでもONが必要 cite参照

bot = commands.Bot(command_prefix="!", intents=intents)

AUNT_SYSTEM = """あなたは「知らないのにおせっかいな大阪のおばちゃんAI」。
特徴:
- 距離感が近い／ツッコミ／世話焼き／でも根は優しい
- 断定しすぎない（知らんことは知らんと言う）
- 最後に一言アドバイスか確認質問を添える
- 説教くさくしない、笑いを混ぜる
禁止:
- 差別・暴力扇動・個人情報の詮索
- 医療/法律は断定せず「専門家へ」誘導
返答は日本語、だいたい1〜5行。"""

AUNT_FALLBACK = [
    "あんた、それ放っといたらアカンやつちゃう？ いったん深呼吸しよか。",
    "ちょっと待ちぃ。まず何が一番困ってんの？そこから片付けよ。",
    "知らんけど！…って言いたいけど、状況もうちょい聞かせて？",
    "ほらほら、無理して強がらんでええ。何を手伝ったらええ？",
    "それな、だいたい睡眠不足が原因や。今日は早よ寝ぇ（半分マジ）。",
]

def should_reply(message: discord.Message) -> bool:
    # Botへのメンション、または「おばちゃん」呼びで反応
    if bot.user in message.mentions:
        return True
    text = message.content
    triggers = ["おばちゃん", "お節介", "相談", "助けて", "たすけて"]
    return any(t in text for t in triggers)

@bot.event
async def on_ready():
    print(f"Logged in as: {bot.user} (id={bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # コマンドも使えるように
    await bot.process_commands(message)

    if not should_reply(message):
        return

    # OpenAIキーが無ければ、定型の“おばちゃん返し”
    if not (OPENAI_API_KEY and OpenAI):
        await message.reply(random.choice(AUNT_FALLBACK), mention_author=False)
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    # 直近だけ会話として渡す（軽量）
    user_text = message.content

    try:
        # OpenAIはResponses APIが推奨（新規プロジェクト向け）:contentReference[oaicite:5]{index=5}
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": AUNT_SYSTEM},
                {"role": "user", "content": user_text},
            ],
        )
        # 出力テキストをまとめて取得
        out = resp.output_text.strip() if hasattr(resp, "output_text") else ""
        if not out:
            out = random.choice(AUNT_FALLBACK)
        await message.reply(out[:1500], mention_author=False)

    except Exception as e:
        print("OpenAI error:", e)
        await message.reply(random.choice(AUNT_FALLBACK), mention_author=False)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it as an environment variable.")

bot.run(DISCORD_TOKEN)
