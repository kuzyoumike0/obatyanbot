# おばちゃんbot

「おばちゃん」で呼ぶと反応する、世話焼きおばちゃんDiscord Bot。

## 使い方
- `おばちゃん` → 「どしたん？」
- `おばちゃんしんどい`
- `おばちゃん 今日ほんま疲れた`
- `おばちゃん 恋の相談していい？`

## 特徴
- 呼ばれた時だけ反応
- 直近3往復の短期記憶
- OpenAI Responses API使用
- センシティブ内容はやさしく誘導
- 返答は必ず4行以内

## 環境変数
- `DISCORD_TOKEN`
- `OPENAI_API_KEY`（任意）
- `OPENAI_MODEL`（任意）

## Railwayデプロイ
1. GitHubにpush
2. RailwayでDeploy from GitHub
3. Variables設定
4. 起動
