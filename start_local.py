"""
ローカル起動スクリプト
1. .env 読み込み
2. ngrok でトンネル開通
3. LINE Webhook URL を自動更新
4. Flask アプリ起動
"""

import os
import sys
import time
import threading
import requests
from dotenv import load_dotenv

load_dotenv()

REQUIRED_VARS = [
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_CHANNEL_SECRET",
    "ANTHROPIC_API_KEY",
    "NGROK_AUTHTOKEN",
]

def check_env():
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] .env に未設定の変数があります: {', '.join(missing)}")
        print("  .env.example を参考に .env を作成してください。")
        sys.exit(1)

def start_ngrok(port: int) -> str:
    from pyngrok import ngrok, conf
    token = os.environ.get("NGROK_AUTHTOKEN", "")
    if token:
        conf.get_default().auth_token = token
    tunnel = ngrok.connect(port, "http")
    public_url = tunnel.public_url
    if public_url.startswith("http://"):
        public_url = "https://" + public_url[7:]
    print(f"[ngrok] トンネル開通: {public_url}")
    return public_url

def update_line_webhook(public_url: str):
    webhook_url = public_url + "/webhook"
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    resp = requests.put(
        "https://api.line.me/v2/bot/channel/webhook/endpoint",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"webhook_url": webhook_url},
        timeout=10,
    )
    if resp.status_code == 200:
        print(f"[LINE] Webhook更新成功: {webhook_url}")
    else:
        print(f"[LINE] Webhook更新失敗 ({resp.status_code}): {resp.text}")

def run_flask(port: int):
    from app import app
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    check_env()
    PORT = int(os.environ.get("PORT", 5000))

    print("[start] ngrok 起動中...")
    public_url = start_ngrok(PORT)

    print("[start] LINE Webhook 更新中...")
    try:
        update_line_webhook(public_url)
    except Exception as e:
        print(f"[WARNING] Webhook更新エラー: {e}")
        print("  手動で LINE Developers Console から設定してください。")
        print(f"  URL: {public_url}/webhook")

    print(f"[start] Flask 起動 (port={PORT}) ...")
    run_flask(PORT)
