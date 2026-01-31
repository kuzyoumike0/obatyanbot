# おばちゃんBot（全文読み上げ / 送信者VC参加）

チャットで「おばちゃん〜」と送ると、
返答（4行）をテキスト返信しつつ、
送信者が入っているVCにBotが入って全文読み上げします（無料TTS: edge-tts）。

## 必須
- Bot権限（サーバー側）
  - View Channel
  - Connect
  - Speak
  - Send Messages / Read Message History
- Discord Developer Portal
  - MESSAGE CONTENT INTENT を ON
- 実行環境に ffmpeg が必要

## 環境変数
- DISCORD_TOKEN（必須）
- DEBUG_LOG（任意）: 1でログ増える
- TTS_VOICE（任意）: 例 ja-JP-NanamiNeural / ja-JP-KeitaNeural
- TTS_RATE（任意）: 例 "+10%"
- TTS_VOLUME（任意）: 例 "+10%"

## ローカル起動
```bash
pip install -r requirements.txt
export DISCORD_TOKEN="..."
python main.py
