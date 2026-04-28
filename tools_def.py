"""
エージェント用ツール定義・実行
"""
import os
import re
import requests

FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_files")
os.makedirs(FILES_DIR, exist_ok=True)

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")

# ── Claude API用ツールスキーマ ──────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": "ウェブを検索して最新情報・ニュース・価格などを取得します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "検索クエリ"},
                "max_results": {"type": "integer", "description": "取得件数（デフォルト5）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "file_write",
        "description": "ファイルを作成または上書きします。メモ・レポート・データ保存に。",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "ファイル名（例: memo.txt）"},
                "content":  {"type": "string", "description": "書き込む内容"},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "file_read",
        "description": "保存済みファイルの内容を読み込みます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "ファイル名"},
            },
            "required": ["filename"],
        },
    },
    {
        "name": "file_list",
        "description": "保存されているファイルの一覧を返します。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remember",
        "description": "重要な情報を永続的に記憶します（好み・設定・重要事項など）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "記憶のキー（例: '好きな競馬場'）"},
                "value": {"type": "string", "description": "記憶する内容"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall",
        "description": "保存された記憶を取得します。keyを省略すると全件返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "取得したいキー（省略で全件）"},
            },
        },
    },
    {
        "name": "schedule_task",
        "description": "定期タスクを登録します。毎日・毎週・毎月の自動実行。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id":     {"type": "string", "description": "タスクID（英数字、例: morning_news）"},
                "schedule":    {"type": "string", "description": "スケジュール（例: '毎日8:00', '毎週月曜9:00', '毎月1日7:00'）"},
                "prompt":      {"type": "string", "description": "実行時にLINEに送信するプロンプト"},
                "description": {"type": "string", "description": "タスクの説明"},
            },
            "required": ["task_id", "schedule", "prompt", "description"],
        },
    },
    {
        "name": "list_schedules",
        "description": "登録済みの定期タスク一覧を返します。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_schedule",
        "description": "定期タスクを削除します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "削除するタスクID"},
            },
            "required": ["task_id"],
        },
    },
]


# ── ツール実行 ──────────────────────────────────────────────

def execute_tool(name: str, inp: dict, user_id: str) -> str:
    from memory_db import remember as db_remember, recall as db_recall
    from memory_db import save_schedule, load_schedules, delete_schedule_db

    try:
        if name == "web_search":
            return _web_search(inp["query"], inp.get("max_results", 5))

        elif name == "file_write":
            return _file_write(inp["filename"], inp["content"])

        elif name == "file_read":
            return _file_read(inp["filename"])

        elif name == "file_list":
            return _file_list()

        elif name == "remember":
            db_remember(user_id, inp["key"], inp["value"])
            return f"記憶しました: {inp['key']} = {inp['value']}"

        elif name == "recall":
            return db_recall(user_id, inp.get("key"))

        elif name == "schedule_task":
            from scheduler_setup import register_schedule, parse_schedule_expr
            cron = parse_schedule_expr(inp["schedule"])
            save_schedule(user_id, inp["task_id"], cron, inp["description"], inp["prompt"])
            register_schedule(user_id, inp["task_id"], cron, inp["prompt"])
            return f"登録完了: {inp['description']} ({inp['schedule']})"

        elif name == "list_schedules":
            schedules = [s for s in load_schedules() if s["user_id"] == user_id]
            if not schedules:
                return "登録済みスケジュールなし"
            return "\n".join(
                f"・{s['task_id']}: {s['task_description']} [{s['cron_expr']}]"
                for s in schedules
            )

        elif name == "delete_schedule":
            from scheduler_setup import unregister_schedule
            delete_schedule_db(inp["task_id"])
            unregister_schedule(inp["task_id"])
            return f"削除しました: {inp['task_id']}"

        else:
            return f"不明なツール: {name}"

    except Exception as e:
        return f"ツールエラー({name}): {e}"


# ── 個別ツール実装 ──────────────────────────────────────────

def _web_search(query: str, max_results: int = 5) -> str:
    if not TAVILY_KEY:
        return "TAVILY_API_KEYが未設定です。.envに追加してください。"
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_KEY, "query": query,
                  "max_results": max_results, "include_answer": True},
            timeout=15,
        )
        data = resp.json()
        lines = [f"検索: {query}"]
        if data.get("answer"):
            lines.append(f"\n要約: {data['answer'][:300]}")
        lines.append("")
        for i, r in enumerate(data.get("results", []), 1):
            lines.append(f"{i}. {r.get('title', '')}")
            lines.append(f"   {r.get('content', '')[:200]}")
            lines.append(f"   {r.get('url', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"検索エラー: {e}"


def _file_write(filename: str, content: str) -> str:
    safe = re.sub(r'[/\\:*?"<>|]', "_", filename)
    path = os.path.join(FILES_DIR, safe)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"保存: {safe} ({len(content)}文字)"


def _file_read(filename: str) -> str:
    safe = re.sub(r'[/\\:*?"<>|]', "_", filename)
    path = os.path.join(FILES_DIR, safe)
    if not os.path.exists(path):
        files = os.listdir(FILES_DIR)
        hint = "、".join(files[:10]) if files else "なし"
        return f"{safe} が見つかりません。存在するファイル: {hint}"
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if len(content) > 3000:
        return content[:3000] + "\n...(省略)"
    return content


def _file_list() -> str:
    from datetime import datetime
    files = sorted(os.listdir(FILES_DIR))
    if not files:
        return "ファイルなし"
    lines = []
    for f in files:
        p = os.path.join(FILES_DIR, f)
        sz = os.path.getsize(p)
        mt = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m/%d %H:%M")
        lines.append(f"・{f}  {sz}B  {mt}")
    return "\n".join(lines)
