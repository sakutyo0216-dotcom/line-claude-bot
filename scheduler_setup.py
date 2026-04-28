"""
APScheduler - 定期タスク管理
"""
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
_line_api = None


def init_scheduler(line_bot_api):
    global _line_api
    _line_api = line_bot_api
    if not scheduler.running:
        scheduler.start()
        print("[scheduler] 起動完了")


def parse_schedule_expr(text: str) -> str:
    """日本語スケジュール文字列 → cron式（分 時 日 月 曜）"""
    DAY_MAP = {"月": "mon", "火": "tue", "水": "wed", "木": "thu",
               "金": "fri", "土": "sat", "日": "sun"}

    # 毎日/毎朝/毎晩 HH:MM
    m = re.search(r'毎(?:日|朝|晩)\s*(\d{1,2})[：:](\d{2})', text)
    if m:
        return f"{m.group(2)} {m.group(1)} * * *"

    # 毎週X曜 HH:MM
    m = re.search(r'毎週([月火水木金土日])曜(?:日)?\s*(\d{1,2})[：:](\d{2})', text)
    if m:
        return f"{m.group(3)} {m.group(2)} * * {DAY_MAP[m.group(1)]}"

    # 毎月N日 HH:MM
    m = re.search(r'毎月(\d{1,2})日\s*(\d{1,2})[：:](\d{2})', text)
    if m:
        return f"{m.group(3)} {m.group(2)} {m.group(1)} * *"

    # HH:MM のみ → 毎日その時刻
    m = re.search(r'(\d{1,2})[：:](\d{2})', text)
    if m:
        return f"{m.group(2)} {m.group(1)} * * *"

    return "0 8 * * *"  # デフォルト: 毎朝8時


def _run_job(user_id: str, task_id: str, prompt: str):
    from agent import run_agent
    from linebot.models import TextSendMessage
    try:
        print(f"[scheduler] 実行: {task_id}")
        result = run_agent(user_id, f"[定期タスク: {task_id}] {prompt}")
        _line_api.push_message(user_id, TextSendMessage(text=result))
    except Exception as e:
        print(f"[scheduler] エラー({task_id}): {e}")


def register_schedule(user_id: str, task_id: str, cron_expr: str, prompt: str):
    parts = cron_expr.split()
    if len(parts) != 5:
        print(f"[scheduler] 不正なcron式: {cron_expr}")
        return
    minute, hour, day, month, dow = parts
    trigger = CronTrigger(
        minute=minute, hour=hour, day=day,
        month=month, day_of_week=dow,
        timezone="Asia/Tokyo",
    )
    scheduler.add_job(
        _run_job, trigger=trigger,
        id=task_id, replace_existing=True,
        args=[user_id, task_id, prompt],
    )
    print(f"[scheduler] 登録: {task_id} ({cron_expr})")


def unregister_schedule(task_id: str):
    try:
        scheduler.remove_job(task_id)
        print(f"[scheduler] 削除: {task_id}")
    except Exception:
        pass


def restore_all_schedules(line_bot_api):
    """起動時にDBのスケジュールを全て再登録"""
    from memory_db import load_schedules
    init_scheduler(line_bot_api)
    for s in load_schedules():
        register_schedule(s["user_id"], s["task_id"], s["cron_expr"], s["prompt"])
