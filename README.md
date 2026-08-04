# おばちゃんBot（全文読み上げ / 送信者VC参加）

チャットで「おばちゃん〜」と送ると、
短い返答（3〜4行）をテキスト返信しつつ、
送信者が入っているVCにBotが入って全文読み上げします（無料TTS: edge-tts）。

`!join`で常駐した後は、同じVCにいる人の通常チャットも名前付きで読み上げます。

## 必須
- Bot権限（サーバー側）
  - View Channel
  - Connect
  - Speak
  - Send Messages / Read Message History
- Discord Developer Portal
  - MESSAGE CONTENT INTENT を ON
- 実行環境に ffmpeg が必要
- Discord VCのDAVE暗号化に対応するため、`discord.py[voice]`を使用

## 環境変数
- DISCORD_TOKEN（必須）
- GEMINI_API_KEY（任意）: Google AI Studioで作成したAPIキー。未設定時は定型返答
- GEMINI_MODEL（任意）: 初期値 `gemini-3.1-flash-lite`
- GEMINI_TIMEOUT_SEC（任意）: Geminiの応答待ち秒数（初期値20）
- DEBUG_LOG（任意）: 1でログ増える
- TTS_VOICE（任意）: 例 ja-JP-NanamiNeural / ja-JP-KeitaNeural
- TTS_RATE（任意）: 読み上げ速度。初期値は早口の「+35%」
- TTS_PITCH（任意）: 声の高さ。初期値は「+4Hz」
- TTS_VOLUME（任意）: 例 "+10%"
- VC_EMPTY_DISCONNECT_SEC（任意）: VCが無人になってから切断するまでの秒数（初期値60）
- AUDIO_PLAY_TIMEOUT_SEC（任意）: 1回の音声再生の上限秒数（初期値180）
- AUDIO_QUEUE_MAX（任意）: サーバーごとの読み上げ待ち上限（初期値20）

## ローカル起動
```bash
pip install -r requirements.txt
export DISCORD_TOKEN="..."
export GEMINI_API_KEY="..."
python main.py
```

## 動作メモ
- `!join`中は指定したVCに常駐し、無人になっても自動退出せず、別のVCにも移動しません。
- 同じVCにいる人の通常チャットと、Geminiが作ったおばちゃんの返答を両方読み上げます。
- `!join`や`!leave`など、`!`で始まるコマンドは読み上げません。
- `!leave`で再生中・待機中の音声を破棄して切断します。
- 常駐していない場合も、VCが無人になるまでは接続を再利用します。
- Geminiが未設定・無料上限・通信エラーの場合は、自動で定型返答へ戻ります。
- APIキーをソースコードやGitHubへ書かず、必ず環境変数で設定してください。

## Dockerで起動
デプロイ時のルートディレクトリは、このREADMEや`main.py`がある
`obatyanbot-main`に設定してください。
