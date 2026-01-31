# おばちゃんbot（Discord + OpenAI + Railway）

「おばちゃん○○」と呼びかけた時だけ返事を返す、世話焼きおばちゃんAI Botです。  
OpenAI API（Responses API）を使い、直近3往復の短期記憶付き。

## 特徴
- 反応トリガー：チャットに `おばちゃん○○` が含まれる時のみ返信
- 口調：関西寄り、優しさ5：ツッコミ4：正論1
- 得意：恋バナ / 仕事疲れ / 生活基盤ほめ
- 直近3往復（最大6発言）の短期記憶（チャンネル単位）
- センシティブ検知：やさしく誘導（4行以内）

## 必要なもの
- Discord Bot Token
- OpenAI API Key（任意だが推奨）

## 環境変数
Railway（またはローカル）に以下を設定：

- `DISCORD_TOKEN`：DiscordのBotトークン
- `OPENAI_API_KEY`：OpenAI APIキー
- `OPENAI_MODEL`：任意（デフォルト `gpt-4.1-mini`）

## ローカル起動
```bash
pip install -r requirements.txt
export DISCORD_TOKEN="..."
export OPENAI_API_KEY="..."
python main.py
