#!/usr/bin/env python3
"""DD373 價差提醒：勝利女神、牛人的第 1 名與第 2、3 名價差 ≥ 0.15 元/萬時，發 Discord。

不改算價、不寫入 data.json。Webhook 只從本機 /workspace/lineage-monitor/.discord_gap_webhook 讀取，
絕不印出、寫入網站或公開 repo。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

THRESHOLD = 0.15
WEBHOOK_PATH = Path("/workspace/lineage-monitor/.discord_gap_webhook")
STATE_PATH = Path("/workspace/lineage-monitor/gap-state/last.json")
LISTINGS_PATH = Path(os.environ.get("DD373_GAP_LISTINGS") or "/workspace/lineage-monitor/gap-state/listings.json")
TAIPEI = timezone(timedelta(hours=8))


def load_webhook() -> str:
    # New gap-alert webhook only. Do not fall back to the older .env value.
    if WEBHOOK_PATH.is_file():
        return WEBHOOK_PATH.read_text(encoding="utf-8").strip()
    return ""


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def fmt_num(v, digits=4) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    t = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return t if t else "0"


def settle_text(item: dict) -> str:
    minimum = item.get("min_buy")
    stock = item.get("stock")
    if not isinstance(minimum, (int, float)) or not isinstance(stock, (int, float)):
        return "拆單資訊不明"
    if minimum < stock:
        return f"可拆單（起售 {fmt_num(minimum, 2)} 萬金）"
    return f"需整單（起售 {fmt_num(minimum, 2)} 萬金）"


def listing_line(rank: int, item: dict) -> str:
    price = fmt_num(item.get("price"))
    stock = fmt_num(item.get("stock"), 2)
    return f"第{rank}名  {price} 元/萬，庫存 {stock} 萬金，{settle_text(item)}"


def gaps_of(listings: list) -> tuple[float | None, float | None]:
    if not listings or not isinstance(listings[0].get("price"), (int, float)):
        return None, None
    p1 = listings[0]["price"]
    g2 = g3 = None
    if len(listings) >= 2 and isinstance(listings[1].get("price"), (int, float)):
        g2 = round(listings[1]["price"] - p1, 4)
    if len(listings) >= 3 and isinstance(listings[2].get("price"), (int, float)):
        g3 = round(listings[2]["price"] - p1, 4)
    return g2, g3


def has_gap(g2, g3) -> bool:
    return (g2 is not None and g2 >= THRESHOLD) or (g3 is not None and g3 >= THRESHOLD)


def key_of(item: dict) -> tuple:
    return (item.get("price"), item.get("stock"))


def build_message(name: str, info: dict, g2, g3, now: datetime) -> str:
    listings = info.get("listings") or []
    lines = [
        "【DD373 價差提醒】" + now.strftime("%Y-%m-%d %H:%M") + "（台北）",
        name,
    ]
    for i, item in enumerate(listings[:3], 1):
        lines.append(listing_line(i, item))
    parts = []
    if g2 is not None:
        parts.append(f"第2名 − 第1名 = {fmt_num(g2)} 元/萬")
    if g3 is not None:
        parts.append(f"第3名 − 第1名 = {fmt_num(g3)} 元/萬")
    if parts:
        lines.append("價差：" + "；".join(parts) + f"（門檻 {fmt_num(THRESHOLD)} 元/萬）")
    url = info.get("url")
    if url:
        lines.append("頁面：" + url)
    return "\n".join(lines)


def post_discord(webhook: str, content: str) -> tuple[bool, str]:
    body = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "dd373-gap-alert"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
        if 200 <= int(code) < 300:
            return True, f"HTTP {code}"
        return False, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, type(e).__name__


def send_test(webhook: str) -> int:
    ok, detail = post_discord(webhook, "DD373 價差提醒已開啟（測試）")
    print("DISCORD test sent ok" if ok else f"DISCORD test failed ({detail})")
    return 0 if ok else 1


def run_alerts(webhook: str) -> int:
    data = load_json(LISTINGS_PATH)
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict) or not servers:
        print("GAP skip (no listings file)")
        return 0
    now = datetime.now(TAIPEI)
    state = load_json(STATE_PATH)
    if not isinstance(state, dict):
        state = {}
    sent = skipped = 0
    for name, info in servers.items():
        if not isinstance(info, dict):
            continue
        listings = info.get("listings") or []
        g2, g3 = gaps_of(listings)
        first = listings[0] if listings else {}
        rec = state.get(name) if isinstance(state.get(name), dict) else {}
        if not has_gap(g2, g3):
            rec = {"price": first.get("price"), "qty": first.get("stock"), "alerted": False}
            state[name] = rec
            gtxt = ",".join(fmt_num(x) if x is not None else "—" for x in (g2, g3))
            print(f"GAP none {name} diffs={gtxt}")
            continue
        same_first = rec.get("alerted") and rec.get("price") == first.get("price") and rec.get("qty") == first.get("stock")
        if same_first:
            print(f"GAP skip {name} (same #1 still listed)")
            skipped += 1
            continue
        msg = build_message(name, info, g2, g3, now)
        ok, detail = post_discord(webhook, msg)
        if ok:
            state[name] = {"price": first.get("price"), "qty": first.get("stock"), "alerted": True}
            sent += 1
            print(f"GAP sent {name} ({detail})")
        else:
            print(f"GAP send failed {name} ({detail})")
    save_json(STATE_PATH, state)
    print(f"GAP done sent={sent} skipped={skipped}")
    return 0


def main(argv: list[str]) -> int:
    webhook = load_webhook()
    if not webhook:
        print("GAP skip (no webhook)")
        return 0
    if "--test" in argv:
        return send_test(webhook)
    return run_alerts(webhook)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
