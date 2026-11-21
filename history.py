#!/usr/bin/env python3
"""Record a price-history point every 30 minutes for selected DD373 servers.

Does not scrape or change price logic. Reads the already-written site data
files, appends one point when the interval has elapsed, and keeps ~90 days.
Also maintains site/dd373/price_log.csv (all servers, last 60 days) for the
Google Sheet IMPORTDATA report.
Stale or blocked values are stored as null; they are never recorded as new.
勝利女神 history stays in victory.json (existing points kept intact).
New servers start from price_log.csv rows when their history file is empty.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DD373 = ROOT / "site" / "dd373" / "data.json"
PRICE_LOG = ROOT / "site" / "dd373" / "price_log.csv"
PRICE_LOG_DAYS = 60
PRICE_LOG_HEADER = ["時間(台北)", "伺服器", "最低價(人民幣/萬)", "1台幣成本(金)", "匯率"]

SERVERS = (
    {
        "name": "勝利女神雅典娜",
        "path": ROOT / "site" / "history" / "victory.json",
    },
    {
        "name": "牛人彌諾陶洛斯",
        "path": ROOT / "site" / "history" / "niuren.json",
    },
    {
        "name": "戰神馬爾斯",
        "path": ROOT / "site" / "history" / "mars.json",
    },
    {
        "name": "火神赫發斯特斯",
        "path": ROOT / "site" / "history" / "hephaestus.json",
    },
    {
        "name": "愛神邱比特",
        "path": ROOT / "site" / "history" / "cupid.json",
    },
    {
        "name": "蛇髮女墨杜沙",
        "path": ROOT / "site" / "history" / "medusa.json",
    },
    {
        "name": "冥王黑帝斯",
        "path": ROOT / "site" / "history" / "hades.json",
    },
    {
        "name": "地獄犬刻耳柏洛斯",
        "path": ROOT / "site" / "history" / "cerberus.json",
    },
    {
        "name": "天后海拉",
        "path": ROOT / "site" / "history" / "hera.json",
    },
    {
        "name": "海神波塞頓",
        "path": ROOT / "site" / "history" / "poseidon.json",
    },
)

INTERVAL_SEC = 30 * 60
MAX_DAYS = 90
TAIPEI = timezone(timedelta(hours=8))
GRACE_SEC = 3 * 60  # 每 30 分鐘一輪會有幾十秒誤差；允許提早 3 分，避免漏點或重複記


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


def price_dd373(data: dict, server: str) -> tuple[float | None, float | None, float | None]:
    """(成本 金/台幣, 匯率, 最低價 人民幣/萬) if this round succeeded; else (None, None, None).

    Cost and rate rounding is unchanged; low is an extra field for the report/chart.
    """
    if not data or not data.get("ok"):
        return None, None, None
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
    low = raw.get("low") if raw else None
    if not isinstance(low, (int, float)) or low <= 0:
        low = None
    return cost, rate, low


def load_history(path: Path, server: str) -> dict:
    hist = load_json(path)
    points = hist.get("points") if isinstance(hist, dict) else None
    if not isinstance(points, list):
        points = []
    return {
        "server": server,
        "interval_minutes": 30,
        "interval_hours": 0.5,
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


def num_cell(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if f <= 0 or f != f:
        return None
    return f


def points_from_price_log(server: str) -> list[dict]:
    """Build history points from price_log.csv rows for one server (same schema)."""
    points: list[dict] = []
    seen: set[int] = set()
    for r in load_price_log():
        if len(r) < 2 or r[1] != server:
            continue
        dt = parse_ts(r[0])
        if not dt:
            continue
        ms = int(dt.timestamp() * 1000)
        if ms in seen:
            continue
        seen.add(ms)
        cost = num_cell(r[3] if len(r) > 3 else "")
        if cost is not None:
            cost = round(cost, 2)
        points.append(
            {
                "ts": iso_taipei(dt),
                "ts_ms": ms,
                "pdd373": cost,
                "rate": num_cell(r[4] if len(r) > 4 else ""),
                "low": num_cell(r[2] if len(r) > 2 else ""),
            }
        )
    points.sort(key=lambda p: p["ts_ms"])
    return points


def record_server(server: str, path: Path, data: dict, now: datetime) -> str:
    hist = load_history(path, server)
    seeded = 0
    if not hist["points"]:
        hist["points"] = points_from_price_log(server)
        seeded = len(hist["points"])
    last = last_ts_ms(hist["points"])
    if last is not None and (now.timestamp() * 1000 - last) < (INTERVAL_SEC - GRACE_SEC) * 1000:
        age = (now.timestamp() * 1000 - last) / 1000
        if seeded:
            write_history(path, hist)
        extra = f" seeded={seeded}" if seeded else ""
        return f"HISTORY skip {server} (last point {age:.0f}s ago, need {INTERVAL_SEC}s){extra}"

    pdd, rate, low = price_dd373(data, server)
    point = {
        "ts": iso_taipei(now),
        "ts_ms": int(now.timestamp() * 1000),
        "pdd373": pdd,
        "rate": rate,
        "low": low,
    }
    hist["points"] = prune(hist["points"], now)
    hist["points"].append(point)
    write_history(path, hist)
    extra = f" seeded={seeded}" if seeded else ""
    return (
        f"HISTORY appended {server} {point['ts']} pdd373={pdd} low={low} rate={rate} "
        f"n={len(hist['points'])}{extra}"
    )



def csv_cell(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return ""
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if v <= 0 or v != v:
            return ""
        text = f"{v:.6f}".rstrip("0").rstrip(".")
        return text
    s = str(v).replace(",", "").strip()
    if not s or s == "—":
        return ""
    try:
        f = float(s)
    except ValueError:
        return ""
    if f <= 0:
        return ""
    return f"{f:.6f}".rstrip("0").rstrip(".")


def log_key(row: list[str]) -> tuple[str, str]:
    ts = (row[0] if row else "")[:19]
    name = row[1] if len(row) > 1 else ""
    return ts, name


def rows_from_history() -> list[list[str]]:
    """Seed rows from existing curve files (勝利女神 / 牛人)."""
    out: list[list[str]] = []
    for srv in SERVERS:
        hist = load_history(srv["path"], srv["name"])
        for p in hist["points"]:
            if not isinstance(p, dict):
                continue
            ts = str(p.get("ts") or "")
            if ts.endswith(" +0800"):
                ts = ts[:-6]
            ts = ts[:19]
            if not ts:
                continue
            out.append(
                [
                    ts,
                    srv["name"],
                    csv_cell(p.get("low")),
                    csv_cell(p.get("pdd373")),
                    csv_cell(p.get("rate")),
                ]
            )
    return out


def rows_from_data(data: dict) -> list[list[str]]:
    """One row per server for this scrape; does not change price logic."""
    if not data:
        return []
    ts = str(data.get("updated_at") or "")[:19]
    if not ts:
        ts = now_taipei().strftime("%Y-%m-%d %H:%M:%S")
    rate = csv_cell(data.get("rate"))
    if rate:
        try:
            rv = float(rate)
        except ValueError:
            rv = 0
        if not (3 < rv < 7):
            rate = ""
    out: list[list[str]] = []
    used: set[str] = set()
    for r in data.get("raw") or []:
        name = r.get("name")
        if not name or "error" in r:
            continue
        used.add(name)
        cost = r.get("cost_per_twd")
        if isinstance(cost, (int, float)) and cost > 0:
            cost = round(cost, 2)
        else:
            cost = None
        out.append([ts, name, csv_cell(r.get("low")), csv_cell(cost), rate])
    for r in data.get("rows") or []:
        name = r.get("name")
        if not name or name in used or r.get("tag") == "error":
            continue
        out.append(
            [
                ts,
                name,
                csv_cell(r.get("low")),
                csv_cell(str(r.get("cost") or "").replace(",", "")),
                csv_cell(r.get("rate")) or rate,
            ]
        )
    return out


def load_price_log() -> list[list[str]]:
    if not PRICE_LOG.is_file():
        return []
    try:
        with PRICE_LOG.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
    except Exception:
        return []
    if not rows:
        return []
    # drop header if present
    if rows[0] and rows[0][0].startswith("時間"):
        rows = rows[1:]
    kept: list[list[str]] = []
    for r in rows:
        if len(r) < 2 or not r[0] or not r[1]:
            continue
        padded = (r + [""] * 5)[:5]
        padded[0] = str(padded[0])[:19]
        kept.append(padded)
    return kept


def write_price_log(rows: list[list[str]]) -> None:
    PRICE_LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRICE_LOG.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(PRICE_LOG_HEADER)
        w.writerows(rows)
    tmp.replace(PRICE_LOG)


def update_price_log(data: dict, now: datetime) -> str:
    rows = load_price_log()
    seeded = 0
    if not rows:
        rows = rows_from_history()
        seeded = len(rows)
    seen = {log_key(r) for r in rows}
    added = 0
    for r in rows_from_data(data):
        k = log_key(r)
        if k in seen:
            continue
        rows.append(r)
        seen.add(k)
        added += 1
    cutoff = (now - timedelta(days=PRICE_LOG_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    before = len(rows)
    rows = [r for r in rows if r[0] >= cutoff]
    pruned = before - len(rows)
    rows.sort(key=lambda r: (r[0], r[1]))
    write_price_log(rows)
    return (
        f"PRICE_LOG rows={len(rows)} added={added} seeded={seeded} pruned={pruned}"
    )


def main() -> int:
    now = now_taipei()
    data = load_json(DATA_DD373)
    for srv in SERVERS:
        print(record_server(srv["name"], srv["path"], data, now))
    print(update_price_log(data, now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
