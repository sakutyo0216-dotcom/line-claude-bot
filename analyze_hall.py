"""
ホール分析スクリプト
使い方:
  python analyze_hall.py アミューズ千葉
  python analyze_hall.py  # 対話モード（一覧から選択）
"""

import sys
import os
import re
import csv
import anthropic
from collections import defaultdict

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR    = os.path.join(BASE_DIR, "data")
STORES_CSV   = os.path.join(_DATA_DIR, "detail_stores.csv")
MODELS_CSV   = os.path.join(_DATA_DIR, "detail_models.csv")
MACHINES_CSV = os.path.join(_DATA_DIR, "detail_machines.csv")

# キャッシュ（LINE bot から繰り返し呼ばれるため）
_cache: dict = {}

def load_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_data() -> tuple[list, list, list]:
    """CSVをキャッシュ付きで読み込む"""
    if "stores" not in _cache:
        _cache["stores"]   = load_csv(STORES_CSV)
        _cache["models"]   = load_csv(MODELS_CSV)
        _cache["machines"] = load_csv(MACHINES_CSV)
    return _cache["stores"], _cache["models"], _cache["machines"]


def find_hall(stores: list[dict], query: str) -> dict | None:
    """部分一致でホールを検索"""
    for s in stores:
        if query in s["hall_name"]:
            return s
    return None


def list_hall_names(stores: list[dict]) -> list[str]:
    return [s["hall_name"] for s in stores]


def parse_schedule(schedule_week: str) -> list[tuple[str, float, str]]:
    """schedule_week → [(日付, スコア, イベント概要), ...] スコア降順"""
    results = []
    for seg in schedule_week.split(" | "):
        m = re.match(r"(\d+/\d+):([\d.]+)点\s*(.*)", seg.strip())
        if m:
            date, score, events = m.group(1), float(m.group(2)), m.group(3)
            events_clean = re.sub(r"\s+", " ", events).strip()[:150]
            results.append((date, score, events_clean))
    return sorted(results, key=lambda x: x[1], reverse=True)


def extract_day_patterns(schedule: list[tuple]) -> list[tuple[str, float, int]]:
    """
    スケジュールから「〇のつく日」「ゾロ目」等の繰り返しパターンを抽出し、
    [(パターン名, 平均スコア, 登場回数), ...] を返す（スコア降順）
    """
    pattern_scores: dict[str, list[float]] = defaultdict(list)

    # パターン名の正規化マップ（サイト表記 → わかりやすい表記）
    PATTERN_ALIAS = {
        "月と重なる日": "月と日がゾロ目の日（1/1・2/2・3/3…）",
        "ゾロ目の日":   "月と日がゾロ目の日（1/1・2/2・3/3…）",
    }

    for date, score, events in schedule:
        # 「Xのつく日」「ゾロ目の日」「月と重なる日」「周年」などを抽出
        found = re.findall(
            r'(\d+のつく日|ゾロ目の日|月と重なる日|[^\s(（]+周年|特定日|週末|土日)',
            events
        )
        # 表記を正規化
        found = [PATTERN_ALIAS.get(p, p) for p in found]
        if not found:
            # 明示的なパターンがなければ取材種別を使う
            if re.search(r'取材|来店', events):
                found = ["取材あり"]
            elif re.search(r'新台入替', events):
                found = ["新台入替"]
        for pat in set(found):
            pattern_scores[pat].append(score)

    result = []
    for pat, scores in pattern_scores.items():
        avg = round(sum(scores) / len(scores), 1)
        result.append((pat, avg, len(scores)))
    return sorted(result, key=lambda x: -x[1])


def analyze_last_digit(machines: list[dict]) -> dict:
    """台番末尾数字ごとの平均差枚・プラス率を集計"""
    digit_data: dict[int, list[int]] = defaultdict(list)
    for m in machines:
        num_str  = re.sub(r"[^\d]", "", m["machine_num"])
        diff_str = re.sub(r"[^\d+\-]", "", m["diff_mai"])
        if not num_str or not diff_str:
            continue
        try:
            last_digit = int(num_str) % 10
            diff = int(diff_str)
            digit_data[last_digit].append(diff)
        except ValueError:
            continue

    result = {}
    for digit in range(10):
        vals = digit_data[digit]
        if vals:
            result[digit] = {
                "count": len(vals),
                "avg_diff": int(sum(vals) / len(vals)),
                "plus_rate": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
            }
    return result


def analyze_models(models: list[dict]) -> list[dict]:
    """機種を集計・ランク付け"""
    model_summary: dict = defaultdict(lambda: {"diffs": [], "ranks": [], "plus": 0, "total": 0})
    for m in models:
        name = m["model_name"]
        try:
            model_summary[name]["diffs"].append(int(m["avg_diff"]))
        except (ValueError, KeyError):
            pass
        try:
            model_summary[name]["ranks"].append(int(m["rank"]))
        except (ValueError, KeyError):
            pass
        try:
            model_summary[name]["plus"]  += int(m["plus_count"])
            model_summary[name]["total"] += int(m["total_count"])
        except (ValueError, KeyError):
            pass

    result = []
    for name, data in model_summary.items():
        avg_diff  = int(sum(data["diffs"]) / len(data["diffs"])) if data["diffs"] else 0
        avg_rank  = round(sum(data["ranks"]) / len(data["ranks"]), 1) if data["ranks"] else 0
        plus_rate = round(data["plus"] / data["total"] * 100, 1) if data["total"] else 0
        result.append({
            "model_name": name,
            "avg_diff": avg_diff,
            "avg_rank": avg_rank,
            "plus_rate": plus_rate,
            "total_machines": data["total"],
        })
    return sorted(result, key=lambda x: (-x["avg_rank"], -x["avg_diff"]))


def build_prompt(hall_name: str, schedule: list, day_patterns: list,
                 models: list, digit_stats: dict, for_line: bool = False) -> str:

    # スケジュール全件（日付と点数とイベント）
    schedule_str = "\n".join(
        f"  {date}: {score}点  {events}" for date, score, events in schedule
    )

    # 日付パターン
    pattern_str = "\n".join(
        f"  {pat}: 平均{avg}点 ({cnt}回)" for pat, avg, cnt in day_patterns
    ) or "  パターン検出なし"

    # 機種上位5件（Python側で確定済み・順位変更禁止）
    top_models_str = "\n".join(
        f"  {i}位: {m['model_name']} / 平均差枚{m['avg_diff']:+}枚 / プラス率{m['plus_rate']}% / "
        f"平均ランク{m['avg_rank']} / {m['total_machines']}台"
        for i, m in enumerate(models[:5], 1)
    )

    # 台番末尾集計
    digit_lines = [
        f"  末尾{d}: 平均差枚{digit_stats[d]['avg_diff']:+}枚 / "
        f"プラス率{digit_stats[d]['plus_rate']}% / {digit_stats[d]['count']}台"
        for d in range(10) if d in digit_stats
    ]
    digit_str = "\n".join(digit_lines) or "データなし"

    line_note = (
        "\n出力はLINE向けに絵文字なし・箇条書きで、全体800文字以内にまとめてください。"
        if for_line else ""
    )

    return f"""【ホール名】{hall_name}

【熱い日のパターン（システムが抽出済み・そのまま使用すること）】
{pattern_str}

【機種データ（出玉上位）】
{top_models_str}

【台番末尾数字ごとの出玉集計】
{digit_str}

上記データをもとに以下を分析してください：{line_note}

1. 【熱い日のパターン】
   上記「熱い日のパターン」欄に書かれたパターン名をそのまま使って説明してください。
   「月と日がゾロ目の日」と書いてある場合は必ずそのまま「月と日がゾロ目の日」と書いてください。
   「5のつく日」「○のつく日」などに絶対に言い換えないでください。
   日付（5/5など）から独自にパターンを推測することも禁止です。

2. 【力を入れている機種】
   上記「機種データ」の1位〜5位をそのままの順番で全て取り上げ、それぞれなぜ注目なのかを1〜2文で説明してください。
   順位の変更・省略・追加は禁止です。

3. 【台番末尾の傾向】
   末尾数字ごとのデータから有意差があるか判定し、狙い目の末尾があれば具体的に示してください。
   差がない場合もその旨を明記してください。

実際に行く際に役立つアドバイスとしてまとめてください。
"""


def run_analysis(hall_query: str, for_line: bool = False) -> str:
    """分析を実行してテキストを返す（CLI・LINE共用）"""
    stores, models, machines = get_data()

    store = find_hall(stores, hall_query)
    if not store:
        candidates = [s["hall_name"] for s in stores if hall_query[:2] in s["hall_name"]]
        msg = f"「{hall_query}」が見つかりませんでした。"
        if candidates:
            msg += "\n候補: " + "、".join(candidates[:8])
        return msg

    hall_id   = store["hall_id"]
    hall_name = store["hall_name"]

    hall_models   = [m for m in models   if m["hall_id"] == hall_id]
    hall_machines = [m for m in machines if m["hall_id"] == hall_id]

    schedule    = parse_schedule(store.get("schedule_week", ""))
    day_patterns = extract_day_patterns(schedule)
    model_stats = analyze_models(hall_models)
    digit_stats = analyze_last_digit(hall_machines)

    if not schedule and not model_stats:
        return f"「{hall_name}」の詳細データがありません。"

    prompt = build_prompt(hall_name, schedule, day_patterns, model_stats, digit_stats, for_line)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500 if not for_line else 800,
        system=(
            "あなたはパチンコ・スロットのホール分析の専門家です。"
            "データをもとに客観的・実用的なアドバイスを提供してください。"
            "ギャンブルの推奨ではなく、データ分析の観点から回答してください。"
        ),
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def analyze(hall_query: str):
    """CLI用: 分析して表示・保存"""
    sys.stdout.reconfigure(encoding="utf-8")
    stores, _, _ = get_data()

    store = find_hall(stores, hall_query)
    hall_name = store["hall_name"] if store else hall_query

    print(f"分析対象: {hall_name}\nClaude が分析中...\n")
    result = run_analysis(hall_query, for_line=False)

    print("=" * 50)
    print(result)
    print("=" * 50)

    out_path = os.path.join(BASE_DIR, f"hall_analysis_{hall_name}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"【{hall_name} 分析レポート】\n\n{result}")
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze(" ".join(sys.argv[1:]))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        stores, _, _ = get_data()
        print("=== ホール一覧 ===")
        for s in stores:
            print(f"  {s['hall_name']}")
        print()
        query = input("ホール名を入力（部分一致OK）: ").strip()
        if query:
            analyze(query)
