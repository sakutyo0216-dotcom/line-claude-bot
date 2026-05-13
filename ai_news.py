"""
AIニュース取得・整形
Tavily APIを使い最新のAI関連ニュースを5〜10件取得し、LINE送信用にフォーマットする。
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_ENDPOINT = "https://api.tavily.com/search"

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


def format_ai_news_for_line(items: list[dict]) -> str:
    now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M")
    if not items:
        return (
            f"【AIニュース {now}】\n"
            "ニュースを取得できませんでした。\n"
            "TAVILY_API_KEY の設定をご確認ください。"
        )
    lines = [f"【AIニュース {now}】"]
    for i, r in enumerate(items, 1):
        title = (r.get("title") or "").strip().replace("\n", " ")
        url = (r.get("url") or "").strip()
        content = (r.get("content") or "").strip().replace("\n", " ")
        snippet = content[:100] + ("…" if len(content) > 100 else "")
        lines.append(f"\n{i}. {title}")
        if snippet:
            lines.append(f"   {snippet}")
        if url:
            lines.append(f"   {url}")
    return "\n".join(lines)


def get_ai_news_message(count: int = 8) -> str:
    try:
        items = fetch_ai_news(count)
    except Exception as e:
        return f"AIニュース取得エラー: {e}"
    return format_ai_news_for_line(items)
