"""
SQLite永続記憶
- conversations: 会話履歴（ユーザー別・全ハンドラ共通）
- user_memories : キー値記憶（エージェントのremember/recall）
- schedules     : 定期タスク定義
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "line_bot.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, created_at);

            CREATE TABLE IF NOT EXISTS user_memories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, key)
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          TEXT NOT NULL,
                task_id          TEXT UNIQUE NOT NULL,
                cron_expr        TEXT NOT NULL,
                task_description TEXT NOT NULL,
                prompt           TEXT NOT NULL,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


def save_message(user_id: str, role: str, content):
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )


def load_history(user_id: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    result = []
    for row in reversed(rows):
        raw = row["content"]
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                result.append({"role": row["role"], "content": parsed})
                continue
        except (json.JSONDecodeError, TypeError):
            pass
        result.append({"role": row["role"], "content": raw})
    return result


def remember(user_id: str, key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_memories (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, key, value, datetime.now())
        )


def recall(user_id: str, key: str | None = None) -> str:
    with get_conn() as conn:
        if key:
            row = conn.execute(
                "SELECT value FROM user_memories WHERE user_id=? AND key=?",
                (user_id, key)
            ).fetchone()
            return row["value"] if row else f"「{key}」の記憶はありません"
        rows = conn.execute(
            "SELECT key, value FROM user_memories WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,)
        ).fetchall()
    if not rows:
        return "記憶データなし"
    return "\n".join(f"・{r['key']}: {r['value']}" for r in rows)


def save_schedule(user_id: str, task_id: str, cron_expr: str,
                  task_description: str, prompt: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schedules "
            "(user_id, task_id, cron_expr, task_description, prompt) VALUES (?,?,?,?,?)",
            (user_id, task_id, cron_expr, task_description, prompt)
        )


def load_schedules() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM schedules").fetchall()
    return [dict(r) for r in rows]


def delete_schedule_db(task_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE task_id=?", (task_id,))
