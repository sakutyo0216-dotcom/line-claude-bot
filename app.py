"""
統合 LINE Bot
- ホール名を送る    → パチンコホール分析（熱い日・注力機種・台番末尾）
- 「最新予想」      → 直近の競馬予想レポート一覧
- 「〇〇ステークス」→ 該当レースの予想を返す
- 「ホール一覧」    → 千葉県登録ホール一覧
- その他           → Claude と通常会話
"""

import os
import sys
import re
import glob
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic

from analyze_hall import run_analysis, get_data, list_hall_names, find_hall

KEIBA_DIR = os.path.join(os.path.dirname(__file__), "..", "keiba-predictor")

app        = Flask(__name__)
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler    = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
claude     = anthropic.Anthropic()

conversation_histories: dict = {}


# ─────────────────────────────────────────
# ホール分析ヘルパー
# ─────────────────────────────────────────

def detect_hall_query(text: str) -> str | None:
    """メッセージがホール分析リクエストか判定してホール名を返す"""
    cleaned = re.sub(
        r'(を?分析|を?教えて|を?調べて|はどう|について|の情報|どんなホール)',
        '', text
    ).strip()
    stores, _, _ = get_data()
    for name in list_hall_names(stores):
        if name in text:
            return name
    store = find_hall(stores, cleaned)
    return cleaned if store else None


def is_hall_list_request(text: str) -> bool:
    return bool(re.search(r'ホール一覧|店舗一覧|どんな(ホール|店)|何の(ホール|店)', text))


# ─────────────────────────────────────────
# 競馬予想ヘルパー
# ─────────────────────────────────────────

def get_prediction_files() -> list[str]:
    """prediction_*.txt を更新日時降順で返す"""
    pattern = os.path.join(KEIBA_DIR, "prediction_*.txt")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return files


def search_prediction(query: str) -> str | None:
    """レース名でファイルを検索して内容を返す"""
    for path in get_prediction_files():
        fname = os.path.basename(path)
        if query in fname:
            with open(path, encoding="utf-8") as f:
                return f.read()
    # ファイル名でなくても中身を検索
    for path in get_prediction_files():
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if query in content:
            return content
    return None


def get_latest_prediction_summary() -> str:
    """最新予想ファイルの一覧を返す"""
    files = get_prediction_files()
    if not files:
        return "保存済みの競馬予想はありません。"
    lines = ["【直近の競馬予想レポート】"]
    for path in files[:5]:
        fname = os.path.basename(path).replace("prediction_", "").replace(".txt", "")
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m/%d %H:%M")
        lines.append(f"・{fname}（{mtime}）")
    lines.append("\nレース名を送ると予想内容を表示します。")
    return "\n".join(lines)


def is_keiba_request(text: str) -> bool:
    return bool(re.search(r'競馬|予想|レース|馬券|ステークス|杯|賞|オークス|ダービー|最新予想', text))


def format_prediction_for_line(full_text: str) -> str:
    """長い予想テキストをLINE向けに要約する（Claude使用）"""
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system="競馬予想レポートをLINE送信用に要約するアシスタントです。",
        messages=[{
            "role": "user",
            "content": (
                "以下の競馬予想レポートを600文字以内で要約してください。\n"
                "必ず含める内容：レース名・本命/対抗/単穴・買い目（単勝/馬連/3連複）\n"
                "絵文字なし・シンプルなテキストで。\n\n"
                f"【レポート】\n{full_text[:3000]}"
            )
        }]
    )
    return response.content[0].text


# ─────────────────────────────────────────
# Webhook
# ─────────────────────────────────────────

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
    user_id      = event.source.user_id
    user_message = event.message.text.strip()

    reply = _get_reply(user_message, user_id)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))


def _get_reply(text: str, user_id: str) -> str:

    # ── ホール一覧 ──
    if is_hall_list_request(text):
        stores, _, _ = get_data()
        names = list_hall_names(stores)
        body = "\n".join(f"・{n}" for n in names[:30])
        suffix = f"\n…他{len(names)-30}件" if len(names) > 30 else ""
        return f"【千葉県 登録ホール一覧】\n{body}{suffix}"

    # ── ホール分析 ──
    hall_name = detect_hall_query(text)
    if hall_name:
        try:
            return run_analysis(hall_name, for_line=True)
        except Exception as e:
            return f"分析中にエラーが発生しました: {e}"

    # ── 競馬: 最新予想一覧 ──
    if re.search(r'最新予想|予想一覧|レース一覧', text):
        return get_latest_prediction_summary()

    # ── 競馬: レース名で検索 ──
    if is_keiba_request(text):
        # レース名候補を抽出（ステークス/杯/賞/オークス等）
        race_match = re.search(
            r'([^\s　]{2,15}(?:ステークス|杯|賞|オークス|ダービー|カップ|記念|特別))',
            text
        )
        query = race_match.group(1) if race_match else None

        if query:
            content = search_prediction(query)
            if content:
                return format_prediction_for_line(content)
            return f"「{query}」の予想が見つかりませんでした。\n「最新予想」と送ると一覧を確認できます。"

        # レース名が特定できない場合は最新ファイルを返す
        files = get_prediction_files()
        if files:
            with open(files[0], encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return format_prediction_for_line(content)
        return "保存済みの予想がありません。先にスクレイピング・予想生成を実行してください。"

    # ── 通常 Claude 会話 ──
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    conversation_histories[user_id].append({"role": "user", "content": text})
    if len(conversation_histories[user_id]) > 20:
        conversation_histories[user_id] = conversation_histories[user_id][-20:]

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=(
            "あなたは競馬予想とパチンコホール分析のアシスタントです。\n"
            "・ホール名を送ると：熱い日のパターン・注力機種・台番末尾の傾向を分析します\n"
            "・「最新予想」と送ると：競馬予想レポート一覧を表示します\n"
            "・レース名を送ると：そのレースの予想を表示します\n"
            "日本語で返答してください。"
        ),
        messages=conversation_histories[user_id],
    )

    reply_text = response.content[0].text
    conversation_histories[user_id].append({"role": "assistant", "content": reply_text})
    return reply_text


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
