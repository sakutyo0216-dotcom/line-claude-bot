"""
Claude エージェントループ（tool_use対応）
"""
import anthropic
import json
from memory_db import load_history, save_message
from tools_def import TOOLS, execute_tool

client = anthropic.Anthropic()

SYSTEM_PROMPT = """あなたは高機能LINEアシスタントエージェントです。
ユーザーの依頼を自律的に実行するためにツールを使えます。

能力:
- web_search: 最新情報・ニュース・価格をウェブ検索
- file_write/read/list: ファイルの作成・読み書き
- remember/recall: 重要情報を永続記憶
- schedule_task: 定期タスクの登録・管理

返答はLINE向けに簡潔に（900文字以内）。絵文字は使わない。
ツールを使う前に何をするか一言添える必要はなく、すぐに実行してよい。"""


def run_agent(user_id: str, user_message: str) -> str:
    history = load_history(user_id, limit=20)
    history.append({"role": "user", "content": user_message})
    save_message(user_id, "user", user_message)

    for _ in range(10):  # 最大10ターン
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "（返答なし）"
            )
            save_message(user_id, "assistant", text)
            return text

        if response.stop_reason == "tool_use":
            history.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, user_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
            history.append({"role": "user", "content": tool_results})
            continue

        break

    return "処理が複雑すぎました。より具体的な指示をお願いします。"
