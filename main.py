import os
import random
import re
from collections import deque, defaultdict

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

# ===== おばちゃん人格 =====
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
"""

# ===== カテゴリ別の“追加ノリ”指示（OpenAIに渡す）=====
CATEGORY_GUIDE = {
    "love": "これは恋愛相談。甘やかし多め、軽いツッコミ、相手の心を守る方向で。最後に質問1つ。必ず4行以内。",
    "work_tired": "これは仕事疲れ（仕事+疲労）。まず労い最優先→軽いツッコミ→生活基盤ほめ。休憩の提案を1つ。最後に質問1つ。必ず4行以内。",
    "work": "これは仕事の愚痴/悩み。労い最優先、逃げ道や小休憩の提案を1つだけ。正論は最小。必ず4行以内。",
    "tired": "これは疲労・メンタルしんどい。睡眠・水分・食事を気遣い、優しさ多め。最後に短い提案か質問。必ず4行以内。",
    "life": "これは日常生活（家事/生活習慣/自己管理）。できてる基盤を具体的に褒めて、手間が減る小技を1つ。必ず4行以内。",
    "general": "雑談/その他。おせっかいおばちゃんとして軽く受け止めてツッコミ。最後に質問1つ。必ず4行以内。",
}

# ===== OpenAIが無い/エラー時：カテゴリ別定型返し =====
AUNT_FALLBACK_BY_CATEGORY = {
    "love": [
        "それ、好きやん。はい認めよか。\nでも焦らんでええ、恋は段取りより気持ちや。\nちゃんと悩めてる時点で優しい証拠やで。\n相手とは今どんな距離感なん？",
        "うん、その気持ち分かるわ…胸が忙しいやつな。\nツッコミ：考えすぎてスマホ握りしめてへん？\nでも日常回してる、そこが一番えらい。\n連絡の頻度、理想はどれくらい？",
    ],
    "work_tired": [
        "うわぁ…仕事で疲れ切ってるやん。今日もよう耐えたな。\nツッコミ：それ、休み無しで走らせすぎ！\n帰ってこれた時点で基盤できてる証拠やで。\n今いちばんしんどいの“人”か“量”か、どっち？",
        "しんどいの当たり前や、仕事って体力持ってかれる。\nでもあんた、投げ出さずにここまで来て偉い。\n今日は“最低限でOK”の許可出しとこ。\n5分だけ休憩、取れそう？",
    ],
    "work": [
        "今日も仕事おつかれさん。まず生きて帰ったのが偉い。\nツッコミ：それ、真面目な人ほど損するやつや！\nでもちゃんと回してる、生活基盤できてるで。\n今いちばん嫌なんは“人”か“量”か、どっち？",
        "仕事ってな、心削ってまでやるもんちゃうで？\nとはいえ頑張ってるのは事実、そこは誇ってええ。\n家帰れてる時点で土台は整ってる。\n明日ラクにする一手、何から変えたい？",
    ],
    "tired": [
        "しんどいのにここまで来た、まずそれが偉い。\nツッコミ：根性で回復するなら病院いらんねん！\n水分とご飯、どっちかだけでも入れよ。\n今の体力、何割くらい？",
        "今日は無理せんでええ日や。\nでも“助けて”って言えたのは強いで。\n生活の土台（寝る準備）だけ守ったら勝ちや。\nいま眠れそう？それとも頭が冴えてる？",
    ],
    "life": [
        "生活ちゃんと回してるやん、当たり前ちゃうで。\nツッコミ：完璧主義やと家事が敵になるで！\nできてる所を数えたら、基盤はもう出来てる。\n今いちばん面倒なんどれ？",
        "えらい、ちゃんと日常を維持してる。\nツッコミ：片付けってな、増える方が悪いねん！\nご飯・風呂・寝る、ここ守れてたら勝ちや。\nどこから軽くする？掃除？洗濯？",
    ],
    "general": [
        "うんうん、聞いたる聞いたる。\nツッコミ：それ、気にしすぎて肩凝ってへん？\nでもちゃんと日常回してる、それが一番強いで。\n結局いちばん引っかかってるの、どこ？",
        "なるほどなぁ…それはモヤるわ。\nツッコミ：悩む才能ありすぎや！\nでも今日を進めてる時点で基盤できてる。\n今ほしいのは“共感”か“作戦”か、どっち？",
    ],
}

# ===== 返答トリガー：必ず「【おばちゃん、○○】」がある時だけ =====
# 例）【おばちゃん、相談】  /  【おばちゃん、今日しんどい】
CALL_PATTERN = re.compile(r"【おばちゃん、(.+?)】")

def extract_call(text: str) -> str | None:
    """
    text に「【おばちゃん、○○】」が含まれていたら ○○ 部分を返す。
    無ければ None。
    """
    m = CALL_PATTERN.search(text)
    if not m:
        return None
    inner = m.group(1).strip()
    return inner if inner else None

def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())

def detect_category(text: str) -> str:
    t = normalize(text)

    love_kw = [
        "好き", "恋", "彼氏", "彼女", "片想い", "片思い", "告白", "デート", "line",
        "返信", "既読", "未読", "脈", "別れ", "別れた", "元カレ", "元カノ", "付き合"
    ]
    work_kw = [
        "仕事", "会社", "上司", "部下", "同僚", "残業", "出社", "退社", "転職", "会議",
        "クレーム", "納期", "シフト", "バイト", "給料", "評価", "ブラック"
    ]
    tired_kw = [
        "疲れ", "しんど", "つら", "無理", "限界", "泣", "眠", "寝れ", "だる", "メンタル",
        "不安", "ストレス", "しにたい", "消えたい"
    ]
    life_kw = [
        "生活", "家事", "掃除", "洗濯", "料理", "自炊", "ご飯", "風呂", "片付け",
        "体調管理", "運動", "早起き", "習慣", "貯金", "節約", "ルーティン"
    ]

    is_love = any(k in t for k in love_kw)
    is_work = any(k in t for k in work_kw)
    is_tired = any(k in t for k in tired_kw)
    is_life = any(k in t for k in life_kw)

    # ✅ 優先度：恋愛 > 仕事疲れ(複合) > 仕事 > 疲れ > 生活
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
    # 4行超えたらカット（空行は除外）
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return text.strip()
    return "\n".join(lines[:4])

# ===== 短期記憶：直近3往復（= 最大6発言） =====
# チャンネル単位で保持（同じチャンネルの会話として自然）
# 形式：deque([("user", "..."), ("assistant", "..."), ...], maxlen=6)
MEMORY_MAX_TURNS = 3
MEMORY_MAX_ITEMS = MEMORY_MAX_TURNS * 2
memory_by_channel: dict[int, deque] = defaultdict(lambda: deque(maxlen=MEMORY_MAX_ITEMS))

def add_memory(channel_id: int, role: str, content: str):
    if not content:
        return
    memory_by_channel[channel_id].append((role, content))

def build_openai_input(channel_id: int, user_text: str, system_text: str):
    """
    OpenAIに渡す input 配列を作る（system + 履歴 + 今回）
    """
    items = [{"role": "system", "content": system_text}]

    # 直近履歴（最大6つ）
    for role, content in memory_by_channel[channel_id]:
        if role not in ("user", "assistant"):
            continue
        items.append({"role": role, "content": content})

    # 今回のユーザー発言
    items.append({"role": "user", "content": user_text})
    return items

@bot.event
async def on_ready():
    print(f"Logged in as: {bot.user} (id={bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # コマンドも使えるように（ただし返答条件は別）
    await bot.process_commands(message)

    # ✅ 返答条件：必ず「おばちゃん○○」が入っている時だけ
    call = extract_call(message.content)
    if call is None:
        return

    # 「【おばちゃん、○○】」以外の文章も含めて会話として扱うが、
    # 呼びかけ部分を取り除いた“相談本文”を優先する
    # 例: "【おばちゃん、相談】 仕事しんどい" -> "仕事しんどい"
    user_text = message.content
    # 先頭の呼びかけだけ消して整形（他の部分は残す）
    user_text = CALL_PATTERN.sub("", user_text, count=1).strip()
    if not user_text:
        # 呼びかけだけで本文が無い場合は、call 部分を本文にする
        user_text = call

    category = detect_category(user_text)

    # まず“ユーザー発言”を短期記憶に追加（呼びかけは除去済み）
    add_memory(message.channel.id, "user", user_text)

    # OpenAIキーが無ければ、カテゴリ別定型返し
    if not (OPENAI_API_KEY and OpenAI):
        out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])
        out = enforce_4_lines(out)
        await message.reply(out[:1500], mention_author=False)
        add_memory(message.channel.id, "assistant", out)
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    extra = CATEGORY_GUIDE.get(category, CATEGORY_GUIDE["general"])
    system_text = (
        AUNT_SYSTEM
        + "\n"
        + f"【今回の相談カテゴリ】{category}\n"
        + f"【追加指示】{extra}\n"
        + "出力は必ず4行以内。4行を超えそうなら短くまとめる。\n"
    )

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=build_openai_input(message.channel.id, user_text, system_text),
        )

        out = resp.output_text.strip() if hasattr(resp, "output_text") else ""
        if not out:
            out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])

        out = enforce_4_lines(out)
        await message.reply(out[:1500], mention_author=False)

        # “おばちゃんの返答”を短期記憶に追加
        add_memory(message.channel.id, "assistant", out)

    except Exception as e:
        print("OpenAI error:", e)
        out = random.choice(AUNT_FALLBACK_BY_CATEGORY[category])
        out = enforce_4_lines(out)
        await message.reply(out[:1500], mention_author=False)
        add_memory(message.channel.id, "assistant", out)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it as an environment variable.")

bot.run(DISCORD_TOKEN)
