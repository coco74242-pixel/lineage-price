#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天堂經典版天幣監測：DD373 低價 vs 8591 參考賣價（扣 6% 手續費）。"""

from __future__ import annotations

import gzip
import os
import argparse
import json
import re
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

DIR = Path(__file__).resolve().parent
CONFIG_PATH = DIR / "config.json"
REF_PATH = DIR / "ref_8591.json"
STATE_PATH = DIR / "state.json"
ENV_PATH = DIR / ".env"
SITE_DIR = DIR / "site"
DATA_PATH = SITE_DIR / "data.json"
TZ = timezone(timedelta(hours=8))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CTX = ssl.create_default_context()

SERVERS_8591 = {
    70810: "獅子涅墨亞",
    68066: "太陽神阿波羅",
    71744: "公牛克里特",
    70097: "獨眼巨人庫克羅普斯",
    68565: "愛神邱比特",
    70897: "飛馬珀伽索斯",
    68566: "勝利女神雅典娜",
    69477: "地獄犬刻耳柏洛斯",
    68567: "美神維納斯",
    68568: "天神宙斯",
    68569: "天后海拉",
    68570: "戰神馬爾斯",
    68571: "月亮女神阿緹蜜斯",
    68572: "海神波塞頓",
    68573: "水蛇許德拉",
    68574: "冥王黑帝斯",
    68575: "火神赫發斯特斯",
    68576: "收獲女神蒂蜜特",
    68577: "蛇髮女墨杜沙",
    68578: "半人馬涅索斯",
    68921: "牛人彌諾陶洛斯",
    68922: "泰坦女神瑞亞",
}

DD_SERVERS = {
    "jkf6hn": "太陽神阿波羅",
    "mqnn8g": "水蛇許德拉",
    "tx17vd": "冥王黑帝斯",
    "5wmdmv": "火神赫發斯特斯",
    "h6s7hd": "收獲女神蒂蜜特",
    "f8kbht": "蛇髮女墨杜沙",
    "8vfqka": "半人馬涅索斯",
    "7ge16s": "愛神邱比特",
    "tmmbgw": "勝利女神雅典娜",
    "sksdr8": "美神維納斯",
    "s9gju1": "天神宙斯",
    "r72q3v": "天后海拉",
    "11w878": "戰神馬爾斯",
    "3wfqbb": "月亮女神阿緹蜜斯",
    "6n4mk7": "海神波塞頓",
    "8k682m": "牛人彌諾陶洛斯",
    "a9hjb6": "泰坦女神瑞亞",
    "hppe3n": "地獄犬刻耳柏洛斯",
    "16ae95": "獨眼巨人庫克羅普斯",
    "3uecnq": "獅子涅墨亞",
    "prr508": "飛馬珀伽索斯",
    "9twa8c": "公牛克里特",
}

BAIT_SUB = [
    "1個天幣=8591", "1個天幣=10000",
    "勿自行下單", "此單勿直下", "私訊詢問及時", "比值請小窗",
    "请小窗问", "請小窗問甜", "1個天幣=8591", "1個天幣=10000",
]
PLACEHOLDER = {0, 1, 8591, 8519, 10000, 88888, 9999}
STALE_MARKERS = ("07/01", "06/01", "05/01", "04/01", "03/01")
BLOCK_MARKERS = (
    "验证码", "驗證碼", "滑动验证", "請完成驗證", "人机验证",
    "captcha", "access denied", "403 forbidden",
)


def now_taipei() -> datetime:
    return datetime.now(TZ)


def iso_now() -> str:
    return now_taipei().strftime("%Y-%m-%d %H:%M:%S %z")


def load_config() -> dict:
    defaults = {
        "fx_rmb_to_twd": 5,
        "fee_8591": 0.06,
        "game_tax": 0.03,
        "min_net_rate": 0.025,
        "ref_cache_hours": 24,
        "dd_cheapest_n": 3,
        "http_timeout": 25,
        "max_workers": 8,
    }
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except Exception as e:
            print(f"ERROR: 讀取 config.json 失敗：{e}", file=sys.stderr)
    return defaults


def decode_body(raw: bytes) -> str:
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def http_get(url: str, timeout: int, referer: str | None = None) -> tuple[int, str, str]:
    """Return (status, final_url, html). Raises on transport errors."""
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh-CN;q=0.9,zh;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            final = resp.geturl() or url
            html = decode_body(resp.read())
            return status, final, html
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = decode_body(e.read() or b"")
        except Exception:
            body = ""
        return e.code, url, body


def has_listing_content(html: str) -> bool:
    return (
        "goods-list-item" in html
        or "__NUXT_DATA__" in html
        or "1元=" in html
        or "1万金=" in html
    )


def looks_blocked(status: int, html: str) -> str | None:
    # 頁面若已有商品列表，不把頁尾「驗證」等普通文字當成擋站。
    if has_listing_content(html):
        return None
    if status in (403, 429, 503):
        return f"HTTP {status}"
    if status >= 400:
        return f"HTTP {status}"
    low = html.lower()
    head = (html[:4000] + low[:4000])
    if any(m in html[:8000] or m in low[:8000] for m in BLOCK_MARKERS):
        return "驗證或擋站頁面"
    if len(html) < 800:
        return "頁面過短，可能被擋"
    return None


# ---------- 8591 ----------

def nuxt_resolve(data, idx, seen=None):
    if seen is None:
        seen = set()
    if not isinstance(idx, int) or idx < 0 or idx >= len(data):
        return idx
    if idx in seen:
        return None
    seen = set(seen)
    seen.add(idx)
    v = data[idx]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        if (
            len(v) == 2
            and isinstance(v[0], str)
            and v[0] in ("Reactive", "ShallowReactive", "Set", "Map")
            and isinstance(v[1], int)
        ):
            return nuxt_resolve(data, v[1], seen)
        return [nuxt_resolve(data, x, seen) if isinstance(x, int) else x for x in v]
    if isinstance(v, dict):
        return {k: nuxt_resolve(data, x, seen) if isinstance(x, int) else x for k, x in v.items()}
    return v


def parse_8591_rate(title: str) -> float | None:
    m1 = re.search(r"1元\s*=\s*([\d.]+)\s*個天幣", title)
    if m1:
        return float(m1.group(1))
    m2 = re.search(r"([\d.]+)\s*個天幣\s*=\s*([\d,]+)\s*元", title)
    if m2:
        coins = float(m2.group(1))
        twd = float(m2.group(2).replace(",", ""))
        if twd > 0:
            return coins / twd
    return None


def is_valid_8591(title: str, rate: float | None) -> bool:
    if rate is None or rate in PLACEHOLDER:
        return False
    if not (900 <= rate <= 2500):
        return False
    if any(b in title for b in BAIT_SUB):
        return False
    if any(s in title for s in STALE_MARKERS):
        return False
    return True


def parse_8591_listings(html: str, sid: int, name: str) -> list[dict]:
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    items = []
    seen = set()
    for i, v in enumerate(data):
        if not (isinstance(v, dict) and "ware_title" in v and "sell_count" in v):
            continue
        item = nuxt_resolve(data, i)
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        if tid in seen:
            continue
        seen.add(tid)
        s = item.get("server_id")
        ginfo = item.get("game_info") or {}
        server = ginfo.get("server") or {}
        sname = server.get("name") if isinstance(server, dict) else None
        if s != sid and sname != name:
            continue
        title = str(item.get("ware_title") or "")
        rate = parse_8591_rate(title)
        if not is_valid_8591(title, rate):
            continue
        items.append({
            "title": title,
            "rate": rate,
            "twd_per_wan": 10000.0 / rate,
            "sell_count": item.get("sell_count") or 0,
        })
    return items


def fetch_8591_server(sid: int, name: str, timeout: int) -> dict:
    url = (
        f"https://www.8591.com.tw/v3/mall/list/68065"
        f"?ware_type=0&sell_sort=1&server_id={sid}"
    )
    status, _, html = http_get(url, timeout, referer="https://www.8591.com.tw/")
    blocked = looks_blocked(status, html)
    if blocked and "__NUXT_DATA__" not in html:
        return {"ok": False, "error": f"{name} {blocked}", "name": name, "sid": sid}
    if "__NUXT_DATA__" not in html:
        return {"ok": False, "error": f"{name} 頁面無商品資料", "name": name, "sid": sid}
    items = parse_8591_listings(html, sid, name)
    items.sort(key=lambda x: -x["sell_count"])
    top = items[:3]
    if not top:
        return {"ok": False, "error": f"{name} 無有效賣單", "name": name, "sid": sid}
    # 參考價 = 銷量第一名；若有其他賣單銷量與第一名差不多（>= 第一名的 90%），
    # 取其中匯率較差（每萬台幣較低）的那張，比較保守。
    best_sc = top[0]["sell_count"]
    close = [x for x in items if x["sell_count"] >= REF_CLOSE_RATIO * best_sc]
    chosen = min(close, key=lambda x: x["twd_per_wan"])
    reason = "銷量第一名"
    if chosen is not top[0]:
        reason = "銷量相近，取匯率較差"
        if chosen not in top:
            top = top + [chosen]
    twds = [x["twd_per_wan"] for x in top]
    return {
        "ok": True,
        "name": name,
        "sid": sid,
        "ref_twd": chosen["twd_per_wan"],
        "mean_twd": statistics.mean(twds),
        "reason": reason,
        "top": [
            {
                "rate": round(x["rate"], 2),
                "twd": round(x["twd_per_wan"], 4),
                "sell_count": x["sell_count"],
                "chosen": x is chosen,
            }
            for x in top
        ],
    }


REF_CLOSE_RATIO = 0.9
REF_SOURCE = "8591 sell_sort=1, 銷量第一名（銷量相近≥90% 時取匯率較差）"
def load_or_refresh_8591(cfg: dict) -> tuple[dict, list[str]]:
    """Return ({name: ref_twd, ...} plus meta), errors."""
    errors: list[str] = []
    hours = float(cfg.get("ref_cache_hours", 24))
    if REF_PATH.exists():
        try:
            cache = json.loads(REF_PATH.read_text(encoding="utf-8"))
            fetched = cache.get("fetched_at_ts")
            # 參考價規則改過時（source 不同）就強制重抓
            if fetched and cache.get("source") == REF_SOURCE and (time.time() - float(fetched)) < hours * 3600:
                refs = cache.get("servers") or {}
                if len(refs) >= 15:
                    return cache, errors
        except Exception as e:
            errors.append(f"8591 快取讀取失敗，改為重抓：{e}")

    timeout = int(cfg.get("http_timeout", 25))
    workers = int(cfg.get("max_workers", 8))
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(fetch_8591_server, sid, name, timeout): name
            for sid, name in SERVERS_8591.items()
        }
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                results[name] = {"ok": False, "error": f"{name} 抓取失敗：{e}", "name": name}

    servers = {}
    top_map = {}
    reason_map = {}
    for name, r in results.items():
        if r.get("ok"):
            servers[name] = round(r["ref_twd"], 4)
            top_map[name] = r.get("top") or []
            reason_map[name] = r.get("reason") or ""
        else:
            errors.append(r.get("error") or f"{name} 抓取失敗")

    cache = {
        "fetched_at": iso_now(),
        "fetched_at_ts": time.time(),
        "source": REF_SOURCE,
        "servers": servers,
        "top": top_map,
        "reason": reason_map,
    }
    REF_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    if not servers:
        errors.append("8591 全部伺服器參考價抓取失敗")
    return cache, errors


# ---------- DD373 ----------

def dd_list_url(code: str) -> str:
    return f"https://www.dd373.com/s-q0kacj-c-7mp223-khkbh6-{code}.html"


def abs_dd_url(href: str) -> str:
    href = href.strip()
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.dd373.com" + href
    return "https://www.dd373.com/" + href


def parse_dd_listings(html: str, list_url: str) -> list[dict]:
    items: list[dict] = []
    chunks = re.split(r'class="goods-list-item', html)
    if len(chunks) < 2:
        return items
    for chunk in chunks[1:]:
        flat = re.sub(r"<script[\s\S]*?</script>", " ", chunk)
        flat = re.sub(r"<[^>]+>", " ", flat)
        flat = re.sub(r"\s+", " ", flat)
        rmb = None
        m_wan = re.search(r"1\s*万金\s*=\s*([\d.]+)\s*元", flat)
        m_yuan = re.search(r"1\s*元\s*=\s*([\d.]+)\s*万金", flat)
        if m_wan:
            rmb = float(m_wan.group(1))
        elif m_yuan and float(m_yuan.group(1)) > 0:
            rmb = 1.0 / float(m_yuan.group(1))
        if rmb is None or not (0.3 <= rmb <= 5):
            continue
        deal = re.search(r"成交率：\s*([\d.]+)%", flat)
        stock = re.search(r"库存：\s*([\d.]+)\s*万金", flat)
        start = re.search(r"起售：\s*([\d.]+)\s*万金", flat)
        seller = None
        # common seller patterns
        for pat in (
            r'class="[^"]*seller[^"]*"[^>]*>\s*([^<]{1,40})',
            r'店铺[：:]\s*([^<\s]{1,40})',
            r'卖家[：:]\s*([^<\s]{1,40})',
        ):
            m = re.search(pat, chunk)
            if m:
                seller = re.sub(r"\s+", "", m.group(1))
                break
        href = None
        m_buy = re.search(
            r'(?://order\.dd373\.com/default/buy_form\.html\?[^"\s]+|https?://order\.dd373\.com/default/buy_form\.html\?[^"\s]+)',
            chunk,
        )
        if m_buy:
            href = abs_dd_url(m_buy.group(0))
        if not href:
            m_shop = re.search(r'shopNumber=([A-Z0-9-]+)', chunk)
            if m_shop:
                href = "https://order.dd373.com/default/buy_form.html?shopNumber=" + m_shop.group(1)
        if not href:
            for pat in (
                r'href="(//(?:www\.)?dd373\.com/[^"]+\.html)"',
                r'href="(https?://(?:www\.)?dd373\.com/[^"]+\.html)"',
                r'href="(/c-[^"]+\.html)"',
            ):
                m = re.search(pat, chunk, re.I)
                if m and "javascript" not in m.group(1):
                    href = abs_dd_url(m.group(1))
                    break
        # 以賣單標籤判斷部分結算；篩選區的「支持部分结算」不能算進單筆
        no_partial = bool(re.search(r'label-bg">\s*不支持部分结算', chunk)) or (
            "不支持部分结算" in chunk and "label-bg" in chunk
        )
        yes_partial = bool(re.search(r'label-bg">\s*支持部分结算', chunk))
        if no_partial:
            partial = False
        elif yes_partial:
            partial = True
        else:
            partial = None  # 無法判斷時，最少要買一律用庫存 50%
        items.append({
            "rmb_per_wan": rmb,
            "deal_rate": float(deal.group(1)) if deal else None,
            "stock_wan": float(stock.group(1)) if stock else None,
            "min_wan": float(start.group(1)) if start else None,
            "partial": partial,
            "seller": seller,
            "url": href or list_url,
        })
    return items


def fetch_dd_server(code: str, name: str, timeout: int, cheapest_n: int, fx: float) -> dict:
    url = dd_list_url(code)
    html = ""
    blocked = None
    for attempt in range(2):
        status, _, html = http_get(url, timeout, referer="https://www.dd373.com/")
        blocked = looks_blocked(status, html)
        if not blocked:
            break
        if attempt == 0:
            time.sleep(0.5)
    if blocked:
        return {"ok": False, "error": f"{name} {blocked}", "name": name, "code": code, "list_url": url}
    listings = parse_dd_listings(html, url)
    if not listings:
        return {"ok": False, "error": f"{name} 無有效賣單或頁面改版", "name": name, "code": code, "list_url": url}
    listings.sort(key=lambda x: x["rmb_per_wan"])
    top = listings[:cheapest_n]
    for it in top:
        it["twd_per_wan"] = it["rmb_per_wan"] * fx
        it["server"] = name
        it["code"] = code
        it["list_url"] = url
    return {"ok": True, "name": name, "code": code, "list_url": url, "listings": top, "n_raw": len(listings)}


def fetch_all_dd(cfg: dict) -> tuple[list[dict], list[str]]:
    timeout = int(cfg.get("http_timeout", 25))
    workers = int(cfg.get("max_workers", 8))
    n = int(cfg.get("dd_cheapest_n", 3))
    fx = float(cfg.get("fx_rmb_to_twd", 5))
    errors: list[str] = []
    listings: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(fetch_dd_server, code, name, timeout, n, fx): name
            for code, name in DD_SERVERS.items()
        }
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                errors.append(f"{name} 抓取失敗：{e}")
                continue
            if not r.get("ok"):
                errors.append(r.get("error") or f"{name} 抓取失敗")
                continue
            listings.extend(r.get("listings") or [])
    return listings, errors


# ---------- state / hits ----------

def listing_key(item: dict) -> str:
    url = item.get("url") or item.get("list_url") or ""
    seller = item.get("seller") or ""
    server = item.get("server") or ""
    # prefer unique listing url; fallback seller; last resort rounded price on list page
    if url and url != item.get("list_url"):
        import re as _re
        m = _re.search(r"shopNumber=([^&]+)", url)
        if m:
            return f"{server}|shop|{m.group(1)}"
        return f"{server}|{url}"
    if seller:
        return f"{server}|{seller}|{url}"
    rmb = round(float(item.get("rmb_per_wan") or 0), 4)
    return f"{server}|{rmb}|{url}"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"notified": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "notified" in data:
            return data
    except Exception:
        pass
    return {"notified": {}}


def save_state(state: dict) -> None:
    state["updated_at"] = iso_now()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_new_or_cheaper(state: dict, key: str, rmb: float) -> bool:
    prev = (state.get("notified") or {}).get(key)
    if not prev:
        return True
    try:
        old = float(prev.get("rmb_per_wan"))
    except Exception:
        return True
    # notify again only if meaningfully cheaper
    return rmb < old * 0.98


def mark_notified(state: dict, key: str, hit: dict) -> None:
    state.setdefault("notified", {})[key] = {
        "server": hit["伺服器"],
        "rmb_per_wan": hit["DD373_RMB每萬"],
        "twd_per_wan": hit["DD373_TWD每萬"],
        "net_rate": hit["淨利率"],
        "url": hit["網址"],
        "notified_at": iso_now(),
    }


def min_buy_label(it: dict) -> str:
    """不支援部分結算→整批；支援或無法判斷→庫存×50%。"""
    stock = it.get("stock_wan")
    partial = it.get("partial")
    if partial is False:
        return "整批"
    if not isinstance(stock, (int, float)):
        return "—"
    need = stock * 0.5
    if abs(need - round(need)) < 1e-6:
        return f"{int(round(need)):g}"
    return f"{need:.1f}"


def build_hits(listings: list[dict], ref_cache: dict, cfg: dict, state: dict | None) -> list[dict]:
    refs = ref_cache.get("servers") or {}
    fee = float(cfg.get("fee_8591", 0.0))
    tax = float(cfg.get("game_tax", 0.03))
    min_rate = float(cfg.get("min_net_rate", 0.025))
    hits = []
    for it in listings:
        name = it["server"]
        ref = refs.get(name)
        if ref is None:
            continue
        dd_twd = it["twd_per_wan"]
        if dd_twd <= 0:
            continue
        cost = dd_twd * (1.0 + tax)
        if cost <= 0:
            continue
        net = ref * (1.0 - fee) - cost
        net_rate = net / cost
        if net_rate < min_rate:
            continue
        key = listing_key(it)
        if state is not None and not is_new_or_cheaper(state, key, it["rmb_per_wan"]):
            continue
        hit = {
            "伺服器": name,
            "DD373_RMB每萬": round(it["rmb_per_wan"], 4),
            "DD373_TWD每萬": round(dd_twd, 4),
            "含稅成本_TWD每萬": round(cost, 4),
            "8591參考價_TWD每萬": round(ref, 4),
            "每萬淨利_TWD": round(net, 4),
            "淨利率": round(net_rate * 100, 2),
            "庫存_萬金": it.get("stock_wan"),
            "最少要買": min_buy_label(it),
            "部分結算": it.get("partial"),
            "網址": it.get("url") or it.get("list_url"),
            "_key": key,
        }
        hits.append(hit)
    hits.sort(key=lambda x: -x["淨利率"])
    return hits


def write_site_snapshot(hits: list[dict], errors: list[str], ref_cache: dict, cfg: dict) -> None:
    """寫出網站用的完整比價結果。不含 webhook，也不寫入去重狀態。"""
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    uniq: list[str] = []
    for e in errors:
        if e not in uniq:
            uniq.append(e)
    refs_out: dict = {}
    servers = ref_cache.get("servers") or {}
    top_map = ref_cache.get("top") or {}
    reason_map = ref_cache.get("reason") or {}
    for name, ref in servers.items():
        refs_out[name] = {
            "ref_twd": ref,
            "reason": reason_map.get(name) or "",
            "top": top_map.get(name) or [],
        }
    public = []
    for h in hits:
        public.append({
            "伺服器": h["伺服器"],
            "DD373_RMB每萬": h["DD373_RMB每萬"],
            "DD373_TWD每萬": h["DD373_TWD每萬"],
            "含稅成本_TWD每萬": h["含稅成本_TWD每萬"],
            "8591參考價_TWD每萬": h["8591參考價_TWD每萬"],
            "每萬淨利_TWD": h["每萬淨利_TWD"],
            "淨利率": h["淨利率"],
            "庫存_萬金": h.get("庫存_萬金"),
            "最少要買": h.get("最少要買"),
            "部分結算": h.get("部分結算"),
            "網址": h.get("網址"),
        })
    payload = {
        "updated_at": iso_now(),
        "updated_at_ts": time.time(),
        "timezone": "Asia/Taipei",
        "fx_rmb_to_twd": cfg.get("fx_rmb_to_twd", 5),
        "fee_8591": cfg.get("fee_8591", 0.06),
        "game_tax": cfg.get("game_tax", 0.03),
        "min_net_rate": cfg.get("min_net_rate", 0.025),
        "hit_count": len(public),
        "server_count": len({h["伺服器"] for h in public}),
        "errors": uniq,
        "ref_fetched_at": ref_cache.get("fetched_at"),
        "ref_source": ref_cache.get("source"),
        "refs": refs_out,
        "hits": public,
    }
    tmp = DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_PATH)
    print(f"SITE_OK {DATA_PATH} hits={len(public)} errors={len(uniq)}")


def emit(hits: list[dict], errors: list[str]) -> int:
    # Public output: JSON hits and/or ERROR lines. No hits -> NO_HITS.
    if errors:
        uniq = []
        for e in errors:
            if e not in uniq:
                uniq.append(e)
        print("ERROR: " + "；".join(uniq))
    if not hits:
        print("NO_HITS")
        return 1 if errors else 0

    public = []
    for h in hits:
        public.append({
            "伺服器": h["伺服器"],
            "DD373_RMB每萬": h["DD373_RMB每萬"],
            "DD373_TWD每萬": h["DD373_TWD每萬"],
            "含稅成本_TWD每萬": h["含稅成本_TWD每萬"],
            "8591參考價_TWD每萬": h["8591參考價_TWD每萬"],
            "每萬淨利_TWD": h["每萬淨利_TWD"],
            "淨利率": h["淨利率"],
            "庫存": h["庫存_萬金"],
            "最少要買": h["最少要買"],
            "網址": h["網址"],
        })
    print(json.dumps(public, ensure_ascii=False, separators=(",", ":")))
    return 0


# ---------- Discord ----------

def load_dotenv() -> None:
    """Load .env into os.environ if the key is missing or empty. Never print values."""
    if not ENV_PATH.exists():
        return
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
    except Exception:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key and not (os.environ.get(key) or "").strip():
            os.environ[key] = val


def webhook_url() -> str:
    return (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()


def post_discord(content: str | None = None, embeds: list | None = None, timeout: int = 15) -> int:
    """Post text/embeds to webhook. Return HTTP status. Never log the URL."""
    url = webhook_url()
    if not url:
        print("ERROR: 未設定 Discord Webhook", file=sys.stderr)
        return 0
    payload: dict = {}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    if not payload:
        return 0
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "lineage-monitor",
        },
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except Exception as e:
        print(f"ERROR: Discord 推送失敗：{e}", file=sys.stderr)
        return 0


def split_discord_messages(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    rest = text
    first = True
    while rest:
        if len(rest) <= limit:
            parts.append(rest if first else "（續）\n" + rest)
            break
        cut = rest.rfind("\n", 0, limit)
        if cut < 200:
            cut = limit
        chunk = rest[:cut]
        parts.append(chunk if first else "（續）\n" + chunk)
        rest = rest[cut:].lstrip("\n")
        first = False
    return parts


def _fmt_num(v, nd=2) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v:.{nd}f}"


def _fmt_stock(v) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    if abs(v - round(v)) < 1e-6:
        return f"{int(round(v))}"
    return f"{v:g}"


def format_min_buy_card(h: dict) -> str:
    """支援部分結算才回傳「最少 N 萬」；不支援則空字串，不顯示整批。"""
    label = h.get("最少要買") or ""
    if not label or label in ("整批", "—"):
        return ""
    return f"最少 {label} 萬"


CARD_RULE = "──────────"  # 約 10 字元，避免超過卡片寬度換行


def format_hit_field(h: dict) -> dict:
    rate = float(h.get("淨利率") or 0)
    rate_txt = _fmt_num(rate, 1) + "%"
    name = f"{h['伺服器']} · 🟢 {rate_txt}" if rate > 30 else f"{h['伺服器']} · {rate_txt}"
    cost = h.get("含稅成本_TWD每萬", h.get("DD373_TWD每萬"))
    ref = h.get("8591參考價_TWD每萬")
    stock = _fmt_stock(h.get("庫存_萬金"))
    url = h.get("網址") or ""
    link = f"[連結]({url})" if url else "—"
    mid = format_min_buy_card(h)
    second = f"庫存 {stock} 萬｜{mid}｜{link}" if mid else f"庫存 {stock} 萬｜{link}"
    value = (
        f"成本 **{_fmt_num(cost)}** → 8591 **{_fmt_num(ref)}**\n"
        f"{second}\n"
        f"{CARD_RULE}"
    )
    return {"name": name, "value": value, "inline": True}


def embed_color_for_hits(hits: list[dict]) -> int:
    """依最高淨利率：超過 20% 綠、10–20% 黃、其他灰。"""
    if not hits:
        return 0x95A5A6
    top = float(hits[0].get("淨利率") or 0)
    if top > 20:
        return 0x2ECC71
    if top >= 10:
        return 0xF1C40F
    return 0x95A5A6


def format_hits_embed(hits: list[dict], when: str, example: bool = False, limit: int = 9) -> dict:
    shown = hits[:limit]
    extra = 0 if example else max(0, len(hits) - len(shown))
    n_desc = len(shown) if example else len(hits)
    description = (
        f"檢查時間：{when}（台北時間）\n"
        f"本輪新低價單 {n_desc} 筆"
    )
    footer_parts = [
        "價格單位：台幣／萬；成本已含 3% 交易稅，淨利已扣 8591 的 6% 手續費。下單前請核對伺服器與收貨資訊。"
    ]
    if extra > 0:
        footer_parts.append(f"另外還有 {extra} 筆未列出。")
    if example:
        footer_parts.append("此則為格式範例，不含去重。")
    title = "📋 格式範例｜DD373 低價監測" if example else "🔍 DD373 低價監測"
    return {
        "title": title,
        "description": description,
        "color": embed_color_for_hits(shown),
        "fields": [format_hit_field(h) for h in shown],
        "footer": {"text": " ".join(footer_parts)},
    }


def update_health(state: dict, errors: list[str]) -> str | None:
    """Return 'error' or 'ok' on transition, else None. Persist flag on state."""
    now_ok = not errors
    prev = state.get("health") or {}
    prev_ok = prev.get("ok")
    if prev_ok is None:
        prev_ok = True
    transition = None
    if prev_ok and not now_ok:
        transition = "error"
    elif (not prev_ok) and now_ok:
        transition = "ok"
    uniq = []
    for e in errors:
        if e not in uniq:
            uniq.append(e)
    state["health"] = {
        "ok": now_ok,
        "last_errors": uniq,
        "updated_at": iso_now(),
    }
    return transition


def push_discord_messages(contents: list[str] | None = None, embeds: list | None = None) -> list[int]:
    statuses = []
    for content in contents or []:
        for part in split_discord_messages(content):
            statuses.append(post_discord(content=part))
            time.sleep(0.3)
    if embeds:
        statuses.append(post_discord(embeds=embeds))
    return statuses


def send_test_discord() -> int:
    load_dotenv()
    if not webhook_url():
        print("ERROR: 未設定 Discord Webhook")
        return 1
    msg = "✅ 天堂經典版 DD373 低價監測已連上 Discord，之後每 10 分鐘檢查一次，有新低價單會推到這裡。"
    status = post_discord(msg)
    print(f"TEST_HTTP {status}")
    return 0 if status in (200, 204) else 1


def run(discord: bool) -> int:
    cfg = load_config()
    if discord:
        load_dotenv()
    ref_cache, ref_errors = load_or_refresh_8591(cfg)
    listings, dd_errors = fetch_all_dd(cfg)
    errors = ref_errors + dd_errors
    missing_ref = [n for n in DD_SERVERS.values() if n not in (ref_cache.get("servers") or {})]
    if missing_ref and listings:
        errors.append("8591 缺參考價：" + "、".join(missing_ref))
    state = load_state()
    all_hits = build_hits(listings, ref_cache, cfg, None)
    write_site_snapshot(all_hits, errors, ref_cache, cfg)

    hits = build_hits(listings, ref_cache, cfg, state) if discord else []
    for h in hits:
        mark_notified(state, h["_key"], h)
    transition = update_health(state, errors)
    save_state(state)

    if discord:
        when = now_taipei().strftime("%Y-%m-%d %H:%M")
        messages = []
        if transition == "error":
            uniq = []
            for e in errors:
                if e not in uniq:
                    uniq.append(e)
            messages.append(
                f"⚠️ DD373 監測出現錯誤（{when} 台北時間）\n"
                + "原因：" + "；".join(uniq)
            )
        elif transition == "ok":
            messages.append(f"✅ DD373 監測已恢復正常（{when} 台北時間）")
        if messages:
            statuses = push_discord_messages(contents=messages)
            bad = [s for s in statuses if s not in (200, 204)]
            if bad:
                print("ERROR: Discord 推送失敗 HTTP " + ",".join(str(s) for s in bad))
        if hits:
            statuses = []
            for i in range(0, len(hits), 9):
                embed = format_hits_embed(hits[i:i + 9], when, example=False, limit=9)
                embed["description"] = (
                    f"檢查時間：{when}（台北時間）\n"
                    f"本輪新低價單 {len(hits)} 筆（第 {i // 9 + 1} 頁）"
                )
                statuses += push_discord_messages(embeds=[embed])
                time.sleep(0.5)
            bad = [s for s in statuses if s not in (200, 204)]
            if bad:
                print("ERROR: Discord 推送失敗 HTTP " + ",".join(str(s) for s in bad))

    return emit(all_hits if not discord else hits, errors)


def send_example_discord() -> int:
    """用目前實際行情推一則格式範例（前 9 筆），不寫進去重狀態。"""
    load_dotenv()
    if not webhook_url():
        print("ERROR: 未設定 Discord Webhook")
        return 1
    cfg = load_config()
    ref_cache, ref_errors = load_or_refresh_8591(cfg)
    listings, dd_errors = fetch_all_dd(cfg)
    errors = ref_errors + dd_errors
    hits = build_hits(listings, ref_cache, cfg, state=None)
    if errors:
        uniq = []
        for e in errors:
            if e not in uniq:
                uniq.append(e)
        print("ERROR: " + "；".join(uniq))
    if not hits:
        print("NO_HITS")
        return 1 if errors else 0
    when = now_taipei().strftime("%Y-%m-%d %H:%M")
    embed = format_hits_embed(hits, when, example=True, limit=9)
    status = post_discord(embeds=[embed])
    print(f"EXAMPLE_HTTP {status}")
    # 純文字預覽（不含 webhook）
    print(embed["title"])
    print(embed["description"])
    for f in embed.get("fields") or []:
        print(f["name"])
        print(f["value"])
        print("")
    print(embed.get("footer", {}).get("text") or "")
    return 0 if status in (200, 204) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="天堂經典版天幣監測")
    parser.add_argument("--discord", action="store_true", help="有命中或健康狀態變化時推到 Discord")
    parser.add_argument("--test-discord", action="store_true", help="推一則測試訊息後結束")
    parser.add_argument("--example-discord", action="store_true", help="推一則格式範例（不寫進去重）")
    args = parser.parse_args()
    if args.test_discord:
        return send_test_discord()
    if args.example_discord:
        return send_example_discord()
    return run(discord=args.discord)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("ERROR: 中斷")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
