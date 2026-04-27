import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
claude = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から自動読み込み

# ユーザーごとの会話履歴（最大20件保持）
conversation_histories = {}

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    conversation_histories[user_id].append({
        "role": "user",
        "content": user_message
    })

    # トークン上限対策：直近20件のみ保持
    if len(conversation_histories[user_id]) > 20:
        conversation_histories[user_id] = conversation_histories[user_id][-20:]

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system="あなたは親切なアシスタントです。日本語で返答してください。",
        messages=conversation_histories[user_id]
    )

    reply_text = response.content[0].text

    conversation_histories[user_id].append({
        "role": "assistant",
        "content": reply_text
    })

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
