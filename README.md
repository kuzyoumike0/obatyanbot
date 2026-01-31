# おばちゃんbot（Discord + OpenAI）

文頭が「おばちゃん」で始まると反応する、世話焼きおばちゃんAI Bot。

## 使い方
- `おばちゃん` → 「どしたん？」
- `おばちゃんしんどい`
- `おばちゃん 今日ほんま疲れた`
- `おばちゃん 恋の相談していい？`

## 特徴
- 呼ばれた時だけ反応（文頭「おばちゃん」）
- 直近3往復の短期記憶（チャンネル単位）
- OpenAI Responses API（推奨）でAI反応
- 返答は必ず4行以内（強制カットあり）
- センシティブ内容は安心・安全確認・支援先へのやさしい誘導

## 環境変数
- DISCORD_TOKEN（必須）
- OPENAI_API_KEY（任意：ない場合は定型返し）
- OPENAI_MODEL（任意：デフォルト gpt-4.1-mini）

## Railwayデプロイ
1. GitHubへpush
2. RailwayでDeploy from GitHub
3. VariablesにDISCORD_TOKEN / OPENAI_API_KEYを設定
4. 起動
