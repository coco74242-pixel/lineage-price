#!/usr/bin/env python3
"""Record a 勝利女神 price-history point at most every 3 hours.

Does not scrape or change price logic. Reads the already-written site data
files, appends one point when the interval has elapsed, and keeps ~90 days.
Stale or blocked values are stored as null; they are never recorded as new.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_8591 = ROOT / "site" / "data.json"
DATA_DD373 = ROOT / "site" / "dd373" / "data.json"
HIST_PATH = ROOT / "site" / "history" / "victory.json"

SERVER = "勝利女神雅典娜"
INTERVAL_SEC = 3 * 3600
MAX_DAYS = 90
TAIPEI = timezone(timedelta(hours=8))
GRACE_SEC = 10 * 60  # 每小時一輪會有幾十秒誤差；允許提早 10 分，才不會 3 小時一點變成 4 小時
FRESH_SEC = INTERVAL_SEC  # cached/fetched refs older than the interval are stale


def now_taipei() -> datetime:
    return datetime.now(TAIPEI)


def iso_taipei(dt: datetime) -> str:
    return dt.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S +0800")


def parse_ts(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=TAIPEI)
        except Exception:
            return None
    s = str(value).strip()
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TAIPEI)
    except Exception:
        return None


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_fresh(dt: datetime | None, now: datetime, max_age: float = FRESH_SEC) -> bool:
    if dt is None:
        return False
    return 0 <= (now - dt).total_seconds() <= max_age


def price_8591(data: dict, now: datetime) -> float | None:
    """8591 參考價 as 金/台幣, or None if this round failed / value is stale."""
    if not data:
        return None
    errors = data.get("errors") or []
    if data.get("last_attempt_ok") is False:
        return None
    if any(str(e).startswith("本輪全部抓取失敗") for e in errors):
        return None
    if any("8591 全部伺服器參考價抓取失敗" in str(e) for e in errors):
        return None
    if any(str(e).startswith(SERVER) for e in errors):
        return None
    fetched = parse_ts(data.get("ref_fetched_at")) or (
        datetime.fromtimestamp(data["fetched_at_ts"], tz=TAIPEI)
        if isinstance(data.get("fetched_at_ts"), (int, float))
        else None
    )
    # Prefer the refs' own fetch time; fall back to snapshot time only if present.
    if not is_fresh(fetched, now):
        return None
    ref = (data.get("refs") or {}).get(SERVER) or {}
    ref_twd = ref.get("ref_twd")
    if not isinstance(ref_twd, (int, float)) or ref_twd <= 0:
        return None
    return round(10000 / ref_twd, 2)


def price_dd373(data: dict) -> tuple[float | None, float | None]:
    """(成本 金/台幣, 匯率) if this round succeeded for 勝利女神; else (None, None)."""
    if not data or not data.get("ok"):
        return None, None
    raw = next(
        (
            r
            for r in (data.get("raw") or [])
            if r.get("name") == SERVER and "error" not in r
        ),
        None,
    )
    cost = raw.get("cost_per_twd") if raw else None
    if not isinstance(cost, (int, float)) or cost <= 0:
        cost = None
    else:
        cost = round(cost, 2)
    rate = data.get("rate")
    if not isinstance(rate, (int, float)) or not (3 < rate < 7):
        rate = None
    return cost, rate


def load_history() -> dict:
    hist = load_json(HIST_PATH)
    points = hist.get("points") if isinstance(hist, dict) else None
    if not isinstance(points, list):
        points = []
    return {
        "server": SERVER,
        "interval_hours": 3,
        "unit": "金/台幣",
        "timezone": "Asia/Taipei",
        "points": points,
    }


def last_ts_ms(points: list) -> int | None:
    for p in reversed(points):
        if not isinstance(p, dict):
            continue
        ms = p.get("ts_ms")
        if isinstance(ms, (int, float)):
            return int(ms)
        dt = parse_ts(p.get("ts"))
        if dt:
            return int(dt.timestamp() * 1000)
    return None


def prune(points: list, now: datetime) -> list:
    cutoff = int((now - timedelta(days=MAX_DAYS)).timestamp() * 1000)
    kept = []
    for p in points:
        if not isinstance(p, dict):
            continue
        ms = p.get("ts_ms")
        if not isinstance(ms, (int, float)):
            dt = parse_ts(p.get("ts"))
            ms = int(dt.timestamp() * 1000) if dt else None
        if ms is None or int(ms) >= cutoff:
            kept.append(p)
    return kept


def main() -> int:
    now = now_taipei()
    hist = load_history()
    last = last_ts_ms(hist["points"])
    if last is not None and (now.timestamp() * 1000 - last) < (INTERVAL_SEC - GRACE_SEC) * 1000:
        age = (now.timestamp() * 1000 - last) / 1000
        print(f"HISTORY skip (last point {age:.0f}s ago, need {INTERVAL_SEC}s)")
        return 0

    data_a = load_json(DATA_8591)
    data_b = load_json(DATA_DD373)
    p8591 = price_8591(data_a, now)
    pdd, rate = price_dd373(data_b)
    point = {
        "ts": iso_taipei(now),
        "ts_ms": int(now.timestamp() * 1000),
        "p8591": p8591,
        "pdd373": pdd,
        "rate": rate,
    }
    hist["points"] = prune(hist["points"], now)
    hist["points"].append(point)
    HIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HIST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(hist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(HIST_PATH)
    print(
        f"HISTORY appended {point['ts']} p8591={p8591} pdd373={pdd} rate={rate} "
        f"n={len(hist['points'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
