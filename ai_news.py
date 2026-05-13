"""
AIニュース取得・整形・キャッシュ
- Tavily APIで最新のAI関連ニュース5〜10件を取得
- data/ai_news_cache.json にキャッシュ（/ai-news Webページが参照）
- LINE送信用の短い通知文（URL付き）を生成
"""
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_ENDPOINT = "https://api.tavily.com/search"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
CACHE_PATH = os.path.join(DATA_DIR, "ai_news_cache.json")

DEFAULT_QUERY = (
    "AI 人工知能 最新ニュース ChatGPT Claude Gemini LLM "
    "生成AI OpenAI Anthropic Google Microsoft"
)


def fetch_ai_news(count: int = 8, query: str = DEFAULT_QUERY) -> list[dict]:
    if not TAVILY_KEY:
        return []
    count = max(5, min(10, count))
    resp = requests.post(
        TAVILY_ENDPOINT,
        json={
            "api_key": TAVILY_KEY,
            "query": query,
            "max_results": count,
            "search_depth": "advanced",
            "topic": "news",
            "days": 2,
            "include_answer": False,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])[:count]


def update_news_cache(count: int = 8) -> dict:
    """ニュースを取得しキャッシュに保存。キャッシュ辞書を返す。"""
    items = fetch_ai_news(count)
    cache = {
        "updated_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "items": items,
    }
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    return cache


def load_news_cache() -> dict | None:
    if not os.path.exists(CACHE_PATH):
        return None
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_or_refresh_cache(count: int = 8) -> dict:
    """キャッシュがあれば返す。なければ即時取得して保存。"""
    cache = load_news_cache()
    if cache and cache.get("items"):
        return cache
    return update_news_cache(count)


def format_short_notification(public_url: str) -> str:
    """LINE通知用の短い文章（URL付き）"""
    now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%m/%d %H:%M")
    if public_url:
        return (
            f"【AIニュース更新 {now}】\n"
            f"最新のAI関連ニュース5〜10件を更新しました。\n"
            f"{public_url}"
        )
    return (
        f"【AIニュース更新 {now}】\n"
        f"最新のAI関連ニュースを更新しました。\n"
        f"ブラウザで /ai-news を開いてご覧ください。"
    )
