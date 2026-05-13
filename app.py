"""
統合 LINE Bot + エージェント
- ホール名を送る    → パチンコホール分析（熱い日・注力機種・台番末尾）
- 「最新予想」      → 直近の競馬予想レポート一覧
- 「〇〇ステークス」→ 該当レースの予想を返す
- 「ホール一覧」    → 千葉県登録ホール一覧
- その他           → エージェント（Web検索・ファイル・記憶・スケジュール対応）
"""

import os
import re
import glob
import threading
from datetime import datetime
from flask import Flask, request, abort, render_template_string
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic

from analyze_hall import run_analysis, get_data, list_hall_names, find_hall
from memory_db import init_db, save_message
from agent import run_agent

KEIBA_DIR = os.path.join(os.path.dirname(__file__), "..", "keiba-predictor")

app          = Flask(__name__)
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler      = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
claude       = anthropic.Anthropic()

# DB初期化・スケジューラ起動
init_db()
from scheduler_setup import restore_all_schedules
restore_all_schedules(line_bot_api)


# ─────────────────────────────────────────
# ホール分析ヘルパー
# ─────────────────────────────────────────

def detect_hall_query(text: str) -> str | None:
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
    pattern = os.path.join(KEIBA_DIR, "prediction_*.txt")
    return sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)


def search_prediction(query: str) -> str | None:
    for path in get_prediction_files():
        if query in os.path.basename(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    for path in get_prediction_files():
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if query in content:
            return content
    return None


def get_latest_prediction_summary() -> str:
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
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system="競馬予想レポートをLINE送信用に要約するアシスタントです。",
        messages=[{"role": "user", "content": (
            "以下の競馬予想レポートを600文字以内で要約してください。\n"
            "必ず含める内容：レース名・本命/対抗/単穴・買い目（単勝/馬連/3連複）\n"
            "絵文字なし・シンプルなテキストで。\n\n"
            f"【レポート】\n{full_text[:3000]}"
        )}]
    )
    return response.content[0].text


# ─────────────────────────────────────────
# Webhook
# ─────────────────────────────────────────

AI_NEWS_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIニュース</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans", "Yu Gothic", sans-serif;
         max-width: 760px; margin: 0 auto; padding: 16px; line-height: 1.6; }
  header { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px;
           border-bottom: 1px solid #ccc; padding-bottom: 8px; margin-bottom: 16px; }
  h1 { font-size: 1.4rem; margin: 0; }
  .updated { font-size: 0.85rem; color: #666; }
  .actions a { font-size: 0.9rem; margin-left: 8px; }
  article { padding: 12px 0; border-bottom: 1px solid #eee; }
  article h2 { font-size: 1.05rem; margin: 0 0 6px; }
  article h2 a { text-decoration: none; }
  article h2 a:hover { text-decoration: underline; }
  .snippet { color: #444; font-size: 0.95rem; margin: 4px 0; }
  .url { font-size: 0.8rem; color: #888; word-break: break-all; }
  .num { color: #888; margin-right: 6px; }
  .empty { color: #888; padding: 24px 0; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>AIニュース</h1>
  <div>
    <span class="updated">更新: {{ updated_at or "未取得" }}</span>
    <span class="actions"><a href="/ai-news?refresh=1">いますぐ更新</a></span>
  </div>
</header>
{% if items %}
  {% for r in items %}
    <article>
      <h2><span class="num">{{ loop.index }}.</span><a href="{{ r.url }}" target="_blank" rel="noopener noreferrer">{{ r.title or "(無題)" }}</a></h2>
      {% if r.content %}<div class="snippet">{{ r.content[:240] }}{% if r.content|length > 240 %}…{% endif %}</div>{% endif %}
      <div class="url">{{ r.url }}</div>
    </article>
  {% endfor %}
{% else %}
  <div class="empty">ニュースがまだありません。「いますぐ更新」を押してください。</div>
{% endif %}
</body>
</html>"""


@app.route("/ai-news")
def ai_news_page():
    from ai_news import get_or_refresh_cache, update_news_cache
    if request.args.get("refresh") == "1":
        cache = update_news_cache(count=8)
    else:
        cache = get_or_refresh_cache(count=8)
    updated = cache.get("updated_at", "")
    if updated:
        try:
            updated = datetime.fromisoformat(updated).strftime("%Y/%m/%d %H:%M")
        except Exception:
            pass
    return render_template_string(
        AI_NEWS_HTML, items=cache.get("items", []), updated_at=updated
    )


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
    reply_token  = event.reply_token

    # 長時間処理でも LINE の webhook タイムアウトに引っかからないようスレッドで処理
    t = threading.Thread(
        target=_process_and_reply,
        args=(user_message, user_id, reply_token),
        daemon=True,
    )
    t.start()


def _process_and_reply(text: str, user_id: str, reply_token: str):
    reply = _get_reply(text, user_id)
    try:
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
    except Exception:
        # reply_token 期限切れの場合は push で送る
        try:
            line_bot_api.push_message(user_id, TextSendMessage(text=reply))
        except Exception as e:
            print(f"[bot] 送信失敗: {e}")


def _get_reply(text: str, user_id: str) -> str:

    # ── AIニュース自動配信 登録/停止 ──
    if re.search(r'AIニュース.*(自動配信|登録|購読|開始|オン|on)', text, re.IGNORECASE):
        from scheduler_setup import register_ai_news_schedule
        times = register_ai_news_schedule(user_id)
        base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
        url_line = f"\n閲覧URL: {base}/ai-news" if base else ""
        reply = (
            "AIニュース自動配信を登録しました。\n"
            f"毎日 {' / '.join(times)} に更新通知を送ります。"
            f"{url_line}\n"
            "停止: 「AIニュース停止」"
        )
        save_message(user_id, "user", text)
        save_message(user_id, "assistant", reply)
        return reply

    if re.search(r'AIニュース.*(停止|解除|オフ|off|キャンセル)', text, re.IGNORECASE):
        from scheduler_setup import unregister_ai_news_schedule
        n = unregister_ai_news_schedule(user_id)
        reply = f"AIニュース自動配信を解除しました（{n}件削除）。"
        save_message(user_id, "user", text)
        save_message(user_id, "assistant", reply)
        return reply

    # ── AIニュース 即時更新＋URL通知 ──
    if re.search(r'^(AIニュース|aiニュース|AI ニュース|AI news)', text, re.IGNORECASE):
        from ai_news import update_news_cache, format_short_notification
        try:
            update_news_cache(count=8)
        except Exception as e:
            reply = f"AIニュース取得エラー: {e}"
        else:
            base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
            reply = format_short_notification(f"{base}/ai-news" if base else "")
        save_message(user_id, "user", text)
        save_message(user_id, "assistant", reply)
        return reply

    # ── ホール一覧 ──
    if is_hall_list_request(text):
        stores, _, _ = get_data()
        names = list_hall_names(stores)
        body   = "\n".join(f"・{n}" for n in names[:30])
        suffix = f"\n…他{len(names)-30}件" if len(names) > 30 else ""
        reply  = f"【千葉県 登録ホール一覧】\n{body}{suffix}"
        save_message(user_id, "user", text)
        save_message(user_id, "assistant", reply)
        return reply

    # ── ホール分析 ──
    hall_name = detect_hall_query(text)
    if hall_name:
        try:
            reply = run_analysis(hall_name, for_line=True)
        except Exception as e:
            reply = f"分析中にエラーが発生しました: {e}"
        save_message(user_id, "user", text)
        save_message(user_id, "assistant", reply)
        return reply

    # ── 競馬: 最新予想一覧 ──
    if re.search(r'最新予想|予想一覧|レース一覧', text):
        reply = get_latest_prediction_summary()
        save_message(user_id, "user", text)
        save_message(user_id, "assistant", reply)
        return reply

    # ── 競馬: レース名で検索 ──
    if is_keiba_request(text):
        race_match = re.search(
            r'([^\s　]{2,15}(?:ステークス|杯|賞|オークス|ダービー|カップ|記念|特別))',
            text
        )
        query = race_match.group(1) if race_match else None
        if query:
            content = search_prediction(query)
            if content:
                reply = format_prediction_for_line(content)
            else:
                reply = f"「{query}」の予想が見つかりませんでした。\n「最新予想」と送ると一覧を確認できます。"
        else:
            files = get_prediction_files()
            if files:
                with open(files[0], encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                reply = format_prediction_for_line(content)
            else:
                reply = "保存済みの予想がありません。先にスクレイピング・予想生成を実行してください。"
        save_message(user_id, "user", text)
        save_message(user_id, "assistant", reply)
        return reply

    # ── エージェントモード（Web検索・ファイル・記憶・スケジュール・通常会話すべて対応）──
    try:
        return run_agent(user_id, text)
    except Exception as e:
        return f"エラーが発生しました: {e}"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
