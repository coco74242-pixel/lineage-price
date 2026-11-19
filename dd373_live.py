#!/usr/bin/env python3
"""DD373 即時價格（網站版）——市場部分。

照「DD373即時價格.exe」(dd_monitor.py) 的邏輯逐行搬過來，只換掉：
  * 匯率來源：原本 Rate.ps1 用 Chrome 開 rate.bot.com.tw/xrt 讀「人民幣 (CNY)」後面第 2 個數字
    （現金賣出）寫進 匯率.xlsx C2；這裡用 headless Chrome（Playwright）讀同一頁、同一個數字，
    存進 dd373_rate.json（取代 匯率.xlsx）。
  * 畫面：tkinter 改成 site/dd373/data.json + 網頁。
常數、掃單、四捨五入、格式都沒改。我的成本（讀訂單）尚未接上。
"""
import json
import os
import re
import sys
import time
import traceback
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

# ---- 常數（與 dd_monitor.py 第 31–39 行相同）----
BUDGET_TWD = 50000
INTERVAL_MIN = 5
ORDER_INTERVAL_MIN = 30
MARGINS = (0.03, 0.04)
PAGE_DELAY = 1.0
RATE_FROM = (9, 30)
LOOKBACK_DAYS = 90
MAX_ORDER_PAGES = 10
DONE_STATUS = {'1', '11'}

HERE = os.path.dirname(os.path.abspath(__file__))
RATE_JSON = os.path.join(HERE, 'dd373_rate.json')          # 取代 匯率\匯率.xlsx
OUT_JSON = os.path.join(HERE, 'site', 'dd373', 'data.json')
URL = 'https://www.dd373.com/s-q0kacj-khkbh6-{code}-0-0-0-7mp223-0-0-0-0-0-{page}-0-0-0.html'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
SERVERS = {
    '水蛇許德拉': 'mqnn8g',
    '太陽神阿波羅': 'jkf6hn',
    '火神赫發斯特斯': '5wmdmv',
    '戰神馬爾斯': '11w878',
    '冥王黑帝斯': 'tx17vd',
    '勝利女神雅典娜': 'tmmbgw',
    '愛神邱比特': '7ge16s',
    '蛇髮女墨杜沙': 'f8kbht',
    '牛人彌諾陶洛斯': '8k682m',
}

# 價差提醒只看這兩服的前三名賣單；不寫入 data.json，也不改掃單／算價。
ALERT_SERVERS = ("勝利女神雅典娜", "牛人彌諾陶洛斯")
PAGE_URL = "https://www.dd373.com/s-q0kacj-c-7mp223-khkbh6-{code}.html"

session = requests.Session()
session.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def parse_page(html):                                            # 原 83 行
    text = re.sub(r'\s+', ' ', BeautifulSoup(html, 'lxml').get_text(' '))
    head = re.search(r'为您找到 ?(\d+) ?条记录', text)
    if not head:
        raise ValueError('頁面沒有賣單列表')
    rows = []
    for block in text[head.start():].split('立即购买'):
        lot = re.search(r'起售： ?([\d.]+) ?万金 ?库存： ?([\d.]+) ?万金', block)
        price = re.search(r'1 ?万金 ?= ?([\d.]+) ?元', block)
        if not lot or not price:
            continue
        rows.append((float(price.group(1)), float(lot.group(1)), float(lot.group(2))))
    return int(head.group(1)), rows


# ---- 開頁面方式（只換這段，算價不動）----
# DD373_FETCH=browser：用本機 Chrome（Playwright channel=chrome，乾淨設定檔、不登入）開頁面，
# 等頁面出現「为您找到 N 条记录」再取 HTML 給 parse_page；沒設就照原本 requests 直接下載。
_pw = _browser = _page = None


def fetch_html(url):
    global _pw, _browser, _page
    if os.environ.get('DD373_FETCH') != 'browser':
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return r.text
    if _page is None:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        kw = {'headless': os.environ.get('DD373_HEADLESS', '1') == '1'}
        if os.environ.get('DD373_CHROME_CHANNEL', 'chrome'):
            kw['channel'] = os.environ.get('DD373_CHROME_CHANNEL', 'chrome')
        _browser = _pw.chromium.launch(**kw)
        _page = _browser.new_page()
    _page.goto(url, timeout=60000, wait_until='domcontentloaded')
    for _ in range(40):
        try:
            if re.search(r'为您找到 ?\d+ ?条记录', re.sub(r'\s+', ' ', _page.inner_text('body'))):
                break
        except Exception:
            pass
        time.sleep(1)
    try:
        return _page.content()
    except Exception:
        return ''


def close_browser():
    global _pw, _browser, _page
    try:
        if _browser:
            _browser.close()
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _pw = _browser = _page = None


def fill(rows, budget):                                          # 原 98 行
    bought, left = 0.0, budget
    for price, minimum, stock in sorted(rows):
        if left < 1:
            break
        if left < minimum * price:
            continue
        units = min(stock, int(left / price * 100) / 100)
        bought += units
        left -= units * price
    return bought, budget - left


def scan(code, budget):                                          # 原 112 行
    rows, pages, page = [], 1, 1
    while page <= pages:
        count, found = parse_page(fetch_html(URL.format(code=code, page=page)))
        rows += found
        pages = (count + 19) // 20 or 1
        bought, spent = fill(rows, budget)
        if budget - spent < 20:
            break
        page += 1
        time.sleep(PAGE_DELAY)
    if not rows or not bought:
        raise ValueError('沒有買得到的賣單')
    return min(r[0] for r in rows), bought, spent, rows


# ---- 匯率（原 read_rate / current_rate；Rate.ps1 改成 fetch_bot_rate）----
def read_rate():                                                 # 原 133 行：A2=日期, C2=現金賣出
    with open(RATE_JSON, encoding='utf-8') as f:
        d = json.load(f)
    day, sell = d['A2'], d['C2']
    if isinstance(day, str):
        day = datetime.strptime(day, '%Y/%m/%d').date()
    return day, float(sell)


def fetch_bot_rate():
    """= Rate.ps1：開 https://rate.bot.com.tw/xrt?Lang=zh-TW，等 body.innerText 出現 人民幣 與 CNY，
    從第一個「人民幣」往後取前 4 個 \\d+\\.\\d+：[0]=現金買入(B2)、[1]=現金賣出(C2)。寫入日期 = 今天 (yyyy/M/d)。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        kw = {'headless': os.environ.get('DD373_HEADLESS', '1') == '1'}
        if os.environ.get('DD373_CHROME_CHANNEL', 'chrome'):
            kw['channel'] = os.environ.get('DD373_CHROME_CHANNEL', 'chrome')
        b = p.chromium.launch(**kw)
        try:
            pg = b.new_page()
            pg.goto('https://rate.bot.com.tw/xrt?Lang=zh-TW', timeout=60000)
            body = ''
            for _ in range(30):
                time.sleep(1)
                try:
                    body = pg.evaluate('document.body ? document.body.innerText : ""')
                except Exception:
                    body = ''
                if ('人民幣' in body or 'Chinese Yuan' in body) and 'CNY' in body:
                    break
        finally:
            b.close()
    if '人民幣' in body:
        idx = body.index('人民幣')
    elif 'Chinese Yuan' in body:
        idx = body.index('Chinese Yuan')
    else:
        raise RuntimeError('臺銀頁面解析失敗，body 頭 200 字元：' + body[:200].replace('\n', ' '))
    nums = re.findall(r'\d+\.\d+', body[idx:])[:4]
    cash_buy, cash_sell = float(nums[0]), float(nums[1])
    t = date.today()
    with open(RATE_JSON, 'w', encoding='utf-8') as f:
        json.dump({'A2': f'{t.year}/{t.month}/{t.day}', 'B2': cash_buy, 'C2': cash_sell,
                   'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                   'source': 'https://rate.bot.com.tw/xrt?Lang=zh-TW 人民幣 現金賣出'},
                  f, ensure_ascii=False, indent=1)


def current_rate():                                              # 原 143 行
    day, sell = read_rate()
    opened = datetime.now().time() >= datetime.now().replace(hour=RATE_FROM[0], minute=RATE_FROM[1]).time()
    if day != date.today() and opened:
        try:
            fetch_bot_rate()          # 原：subprocess.run(['powershell', ... RATE_PS1], timeout=300)
            day, sell = read_rate()
        except Exception as e:
            log(f'匯率更新失敗: {e!r}')
    if not 3 < sell < 7:
        raise ValueError(f'匯率.xlsx 的值不合理：{sell}')
    note = f'匯率 {sell}（臺銀現金賣出 {day:%m/%d}）'
    return sell, (note + '，今天更新失敗' if day != date.today() and opened else note), day


def top_listings(rows, n=3):
    # Cheapest-first (RMB per 10k gold); alert only, not written to data.json.
    out = []
    for price, minimum, stock in sorted(rows, key=lambda r: (r[0], r[1], r[2])):
        out.append({"price": price, "min_buy": minimum, "stock": stock})
        if len(out) >= n:
            break
    return out


def write_gap_listings(info):
    path = os.environ.get("DD373_GAP_LISTINGS", "").strip()
    if not path or not info:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "servers": info}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def run_round(on_row=None, listings_out=None):                   # 原 163 行
    rate, rate_note, day = current_rate()
    errors, results = [], []
    for name, code in SERVERS.items():
        try:
            low, bought, spent, listings = scan(code, BUDGET_TWD / rate)
            avg = spent / bought
            cost = rate * avg
            res = {'name': name, 'low': low, 'avg': avg, 'bought': bought,
                   'spent_twd': spent * rate, 'rate': rate, 'cost_per_twd': 10000 / cost}
            if listings_out is not None and name in ALERT_SERVERS:
                listings_out[name] = {
                    'code': code,
                    'url': PAGE_URL.format(code=code),
                    'listings': top_listings(listings),
                }
        except Exception as e:
            errors.append(name)
            log(f'{name} 抓價失敗: {e!r}')
            res = {'name': name, 'error': str(e)}
        results.append(res)
        if on_row:
            on_row(res)
        time.sleep(PAGE_DELAY)
    status = rate_note
    if errors:
        status += f'；抓價失敗 {len(errors)} 服：{"、".join(errors)}'
    return results, status, rate, day


def set_market(r, prev, market, tags):                           # 原 App.set_market（611 行）
    name = r['name']
    if 'error' in r:
        market[name] = {'low': '抓價失敗'}
        tags[name] = 'error'
    else:
        avg = round(r['avg'], 4)
        last = prev.get(name)
        delta = avg - last if last is not None else 0.0
        prev[name] = avg
        tags[name] = 'up' if delta > 0 else 'down' if delta < 0 else ''
        market[name] = {'low': f"{r['low']:.4f}", 'avg': f'{avg:.4f}', 'rate': f"{r['rate']:g}",
                        'cost': f"{r['cost_per_twd']:,.0f}"}


def main():
    try:
        old = json.load(open(OUT_JSON, encoding='utf-8'))
    except Exception:
        old = {}
    prev = dict(old.get('prev') or {})
    market, tags = {}, {}
    now = datetime.now()
    out = {'updated_at': now.strftime('%Y-%m-%d %H:%M:%S'), 'updated_at_ts': time.time(),
           'budget_twd': BUDGET_TWD, 'interval_min': INTERVAL_MIN, 'margins': list(MARGINS)}
    try:
        try:
            listings_out = {}
            results, status, rate, day = run_round(
                on_row=lambda r: set_market(r, prev, market, tags),
                listings_out=listings_out,
            )
        finally:
            close_browser()
        if results and all('error' in r for r in results):
            # 9 服全部失敗（例如被擋）＝本輪失敗：照原程式保留上一輪表格，只改狀態列
            raise RuntimeError('全部伺服器抓價失敗：' + results[0].get('error', ''))
        out.update(ok=True, status=f"{now:%H:%M:%S}  {status}", rate=rate, rate_text=f'{rate:g}',
                   rate_day=f'{day:%Y/%m/%d}', raw=results)
        write_gap_listings(listings_out)
    except Exception as e:
        log('本輪失敗: ' + repr(e) + '\n' + traceback.format_exc())
        # 原程式：本輪失敗時表格保留上一輪的值，只改狀態列
        market = {r['name']: {k: v for k, v in r.items() if k not in ('name', 'tag')}
                  for r in old.get('rows', []) if 'name' in r}
        tags = {k: '' for k in market}
        out.update(ok=False, status=f'本輪失敗：{e}', rate=old.get('rate'), rate_text=old.get('rate_text'),
                   rate_day=old.get('rate_day'), raw=old.get('raw', []))
    out['prev'] = prev
    out['rows'] = [dict({'name': n}, **market.get(n, {}), tag=tags.get(n, '')) for n in SERVERS]
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log(out['status'])
    for r in out['rows']:
        log(f"{r['name']}  {r.get('rate','')}  {r.get('low','')}  {r.get('avg','')}  {r.get('cost','')}")
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
