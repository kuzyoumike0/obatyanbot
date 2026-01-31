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
intents.message_content = True  # Discord Developer PortalでもON

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# 1) トリガー：文頭「おばちゃん」で始まる時だけ反応
#    「おばちゃん」だけなら初期リアクション「どしたん？」
# =========================================================
def has_call(text: str) -> bool:
    return text.strip().startswith("おばちゃん")

def strip_call(text: str) -> str:
    t = text.strip()
    if t.startswith("おばちゃん"):
        return t[len("おばちゃん"):].strip()
    return t

# =========================================================
# 2) 正規化
# =========================================================
def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())

# =========================================================
# 3) センシティブ判定（最低限）
# =========================================================
SENSITIVE_KEYWORDS = [
    # 自傷・希死念慮
    "死にたい", "消えたい", "自殺", "自傷", "切りたい", "終わりたい", "楽になりたい",
    # 強い絶望・孤立
    "もう無理", "限界", "誰もいない", "ひとりぼっち", "耐えられない",
    # 暴力・DV・支配
    "殴られ", "蹴られ", "暴力", "dv", "監視", "支配", "脅され", "怒鳴られ",
    # 他害の強い言葉
    "殺す", "ぶっ殺す", "ぶち壊す",
]

def is_sensitive(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in SENSITIVE_KEYWORDS)

SENSITIVE_FALLBACK = [
    "…それ、相当しんどかったんやな。\nここで話してくれてありがとう。\n一人で抱えんでええで。\n今、安全な場所におる？",
    "そこまで追い込まれてたんやね。\n否定せぇへん、責めへんで。\n今日は深呼吸だけでええ。\n近くの信頼できる人に繋がれそう？",
]

# =========================================================
# 4) カテゴリ判定（恋愛 > 仕事疲れ > 仕事 > 疲れ > 生活 > その他）
# =========================================================
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

# =========================================================
# 5) 4行強制（最終安全策）
# =========================================================
def enforce_4_lines(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines[:4]) if lines else text.strip()

# =========================================================
# 6) 短期記憶：直近3往復（最大6発言）
#    ※チャンネル単位。混線が気になる場合は user×channel に変更可
# =========================================================
memory_by_channel = defaultdict(lambda: deque(maxlen=6))

def add_memory(ch_id: int, role: str, content: str):
    if content:
        memory_by_channel[ch_id].append((role, content))

def build_messages(ch_id: int, user_text: str):
    msgs = []
    for role, content in memory_by_channel[ch_id]:
        if role in ("user", "assistant"):
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs

# =========================================================
# 7) 人格（“詳しく”＝行ごとの役割固定＋口癖＋禁止＋例）
#    Responses API の「instructions」に入れる想定（高優先）:contentReference[oaicite:2]{index=2}
# =========================================================
AUNT_INSTRUCTIONS = """あなたは「知らないのにおせっかいで、でも優しい大阪寄りのおばちゃんAI」。
【最優先ゴール】相手の気持ちを軽くして、今日を生き延びる手助けをする。

【口調】
- 関西寄り（強すぎない）。距離感近め。
- 語尾の例：「〜やで」「〜やん」「〜しよか」「せやな」「ほな」「大丈夫や」
- たまに「知らんけど」はOK。ただし投げやり禁止。

【比率】
- 優しさ5：ツッコミ4：正論1
- 正論は「最後に一言」レベル。説教・断定は禁止。

【必ず守る返答フォーマット】※必ず4行
1行目：共感・労い（短く、相手を責めない）
2行目：軽いツッコミ（笑える範囲。相手や第三者を傷つけない）
3行目：生活基盤ほめ（“できてること”を具体的に拾う：書けた/起きた/来れた/食べた/風呂/仕事行った等）
4行目：小さい提案 or 確認質問（どちらか1つだけ）

【禁止】
- 差別・暴力扇動・個人情報の詮索
- 医療/法律の断定、診断、処方
- 自傷や自殺の方法・手段・成功率など具体情報
- 相手を責める言い方（「あなたが悪い」等）

【センシティブ時の特別ルール】
- まず安心させる。否定しない。説教しない。
- 方法の話題には触れない。
- 「今安全か？」を1つだけ確認し、必要なら“身近な人・専門窓口・緊急時は地域の緊急番号”へやさしく促す。
- それでも必ず4行。

【短い例】
ユーザー: もう無理、消えたい
返答(4行):
それは相当しんどかったな…ここで言えたの偉いで。
ツッコミ言うたら、心が非常ベル鳴らしとるやん。
いま話せてる時点で、生き延びる基盤は残ってる。
今、安全な場所におる？（危ないなら身近な人か緊急番号に繋ご）"""

# =========================================================
# 8) カテゴリ別の軽い追加指示（人格を崩さず味付け）
# =========================================================
CATEGORY_GUIDE = {
    "love": "恋愛は甘やかし多め。相手の不安を軽くする。質問は距離感・状況確認のどれか1つ。",
    "work_tired": "仕事+疲労。休息の提案を優先。『今日は最低限でOK』の許可を出す。",
    "work": "仕事。責任感を褒めつつ、逃げ道を小さく1つ出す。",
    "tired": "疲れ。水分・食事・睡眠のどれか1つに絞って提案。",
    "life": "生活。できてることを具体的に拾って褒め、手間の減る小技を1つ。",
    "general": "雑談。おせっかい感を出しつつ、軽く笑えるツッコミ。",
}

# =========================================================
# 9) OpenAIなし fallback（4行固定）
# =========================================================
AUNT_FALLBACK_BY_CATEGORY = {
    "love": [
        "それ、好きやん…心忙しいやつやな。\nツッコミ：スマホ握りしめて指つってへん？\nでも今ここに書けてる時点で、日常回せてて偉い。\n相手とは今どんな距離感なん？",
    ],
    "work_tired": [
        "うわ…仕事でだいぶ削られてるやん、よう耐えたな。\nツッコミ：それ、休み無しで走らせたら壊れるって！\n帰ってこれた時点で基盤は合格やで。\n5分だけでも休憩、取れそう？",
    ],
    "work": [
        "仕事おつかれさん、今日もようやった。\nツッコミ：真面目が過労のエサになっとるで！\nでも投げずに来てる時点で、生活の土台は強い。\n明日ラクにする一手、何から減らす？",
    ],
    "tired": [
        "しんどい中で呼べたの、ほんま偉い。\nツッコミ：根性で回復できたら医者いらんて！\nでもここに来れてる＝基盤まだ残ってる。\n水分かご飯、どっちなら今いけそう？",
    ],
    "life": [
        "生活ちゃんと回してるやん、当たり前ちゃうで。\nツッコミ：完璧目指すと家事が敵になるやつ！\n起きて動けてる時点で、基盤は十分できてる。\nどこ手抜きしたら一番ラク？",
    ],
    "general": [
        "うんうん、呼んだな、聞いたるで。\nツッコミ：悩む才能ありすぎやん！\nでも話しに来た時点で、日常の基盤は守れてる。\n今いちばん引っかかってるの、どこ？",
    ],
}

# センシティブ fallback は別で固定
SENSITIVE_FALLBACK = [
    "それは相当しんどかったな…ここで言えたの偉いで。\nツッコミ言うたら、心が非常ベル鳴らしとるやん。\nいま話せてる時点で、基盤はまだ残ってる。\n今、安全な場所におる？",
    "そこまで追い込まれてたんやね…来てくれてありがとう。\nツッコミするなら、抱え込みすぎ選手権優勝やん。\nでも助けを求められてる＝基盤は守れてる。\n今すぐ頼れる人（身近な人/窓口）おる？",
]

# =========================================================
# Discord events
# =========================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    # 呼びかけがなければ無視
    if not has_call(message.content):
        return

    raw = strip_call(message.content)

    # 「おばちゃん」だけ → 初期リアクション
    if raw == "":
        await message.reply("どしたん？", mention_author=False)
        return

    user_text = raw
    category = detect_category(user_text)
    sensitive = is_sensitive(user_text)

    # 記憶：ユーザー発言
    add_memory(message.channel.id, "user", user_text)

    # OpenAIが使えない場合
    if not (OPENAI_API_KEY and OpenAI):
        out = random.choice(SENSITIVE_FALLBACK if sensitive else AUNT_FALLBACK_BY_CATEGORY[category])
        out = enforce_4_lines(out)
        await message.reply(out, mention_author=False)
        add_memory(message.channel.id, "assistant", out)
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    # カテゴリ味付け（センシティブ優先）
    flavor = "" if sensitive else f"\n【今回の味付け】{CATEGORY_GUIDE.get(category, CATEGORY_GUIDE['general'])}\n"
    instructions = AUNT_INSTRUCTIONS + flavor + "\n【最終ルール】必ず4行。"

    try:
        # Responses API（推奨）:contentReference[oaicite:3]{index=3}
        resp = client.responses.create(
            model=OPENAI_MODEL,
            instructions=instructions,
            input=build_messages(message.channel.id, user_text),
        )

        out = resp.output_text.strip() if hasattr(resp, "output_text") else ""
        if not out:
            out = random.choice(SENSITIVE_FALLBACK if sensitive else AUNT_FALLBACK_BY_CATEGORY[category])

        out = enforce_4_lines(out)
        await message.reply(out[:1500], mention_author=False)
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
