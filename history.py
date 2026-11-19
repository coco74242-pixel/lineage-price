#!/usr/bin/env python3
"""Record a 3-hourly price-history point for selected DD373 servers.

Does not scrape or change price logic. Reads the already-written site data
files, appends one point when the interval has elapsed, and keeps ~90 days.
Stale or blocked values are stored as null; they are never recorded as new.
勝利女神 history stays in victory.json (existing points kept intact).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DD373 = ROOT / "site" / "dd373" / "data.json"

SERVERS = (
    {
        "name": "勝利女神雅典娜",
        "path": ROOT / "site" / "history" / "victory.json",
    },
    {
        "name": "牛人彌諾陶洛斯",
        "path": ROOT / "site" / "history" / "niuren.json",
    },
)

INTERVAL_SEC = 3 * 3600
MAX_DAYS = 90
TAIPEI = timezone(timedelta(hours=8))
GRACE_SEC = 10 * 60  # 每小時一輪會有幾十秒誤差；允許提早 10 分，才不會 3 小時一點變成 4 小時


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


def price_dd373(data: dict, server: str) -> tuple[float | None, float | None]:
    """(成本 金/台幣, 匯率) if this round succeeded for the server; else (None, None)."""
    if not data or not data.get("ok"):
        return None, None
    raw = next(
        (
            r
            for r in (data.get("raw") or [])
            if r.get("name") == server and "error" not in r
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


def load_history(path: Path, server: str) -> dict:
    hist = load_json(path)
    points = hist.get("points") if isinstance(hist, dict) else None
    if not isinstance(points, list):
        points = []
    return {
        "server": server,
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


def write_history(path: Path, hist: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(hist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_server(server: str, path: Path, data: dict, now: datetime) -> str:
    hist = load_history(path, server)
    last = last_ts_ms(hist["points"])
    if last is not None and (now.timestamp() * 1000 - last) < (INTERVAL_SEC - GRACE_SEC) * 1000:
        age = (now.timestamp() * 1000 - last) / 1000
        return f"HISTORY skip {server} (last point {age:.0f}s ago, need {INTERVAL_SEC}s)"

    pdd, rate = price_dd373(data, server)
    point = {
        "ts": iso_taipei(now),
        "ts_ms": int(now.timestamp() * 1000),
        "pdd373": pdd,
        "rate": rate,
    }
    hist["points"] = prune(hist["points"], now)
    hist["points"].append(point)
    write_history(path, hist)
    return (
        f"HISTORY appended {server} {point['ts']} pdd373={pdd} rate={rate} "
        f"n={len(hist['points'])}"
    )


def main() -> int:
    now = now_taipei()
    data = load_json(DATA_DD373)
    for srv in SERVERS:
        print(record_server(srv["name"], srv["path"], data, now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
