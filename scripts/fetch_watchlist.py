#!/usr/bin/env python3
"""Agentic Watchlist: fetch Yahoo Finance data for the stocks in watchlist.txt and write docs/watchlist.json.
Standard library only. Usage: python scripts/fetch_watchlist.py [output folder, default docs]"""
import json, os, re, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/csv,application/json,text/html;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}


def get(url, tries=2, timeout=10):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + i)
    raise last

def rsi14(closes):
    """Wilder RSI(14), the same smoothing TradingView uses by default."""
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for a, b in zip(closes, closes[1:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = sum(gains[:14]) / 14, sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        ag, al = (ag * 13 + g) / 14, (al * 13 + l) / 14
    return 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)

def yahoo(symbol):
    q = urllib.parse.quote(symbol)
    raw = None
    for host in ("query1", "query2"):
        try:
            raw = get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range=1y&interval=1d&includePrePost=false", tries=1)
            break
        except Exception as e:  # noqa: BLE001
            err = e
    if raw is None:
        raise err
    res = json.loads(raw)["chart"]["result"][0]
    meta = res["meta"]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    pts = [(t, c) for t, c in zip(ts, closes) if c is not None]
    last = meta.get("regularMarketPrice", pts[-1][1])
    # previous close = last completed daily close before the latest bar
    # the last daily bar is the latest session (live or final), so the one before it is the prior close
    prev = pts[-2][1] if len(pts) >= 2 else meta.get("chartPreviousClose")
    series = [c for _, c in pts]
    if series:
        series[-1] = last

    def ago(n):
        return series[-1 - n] if len(series) > n else None

    def pct(a, b):
        return None if a is None or not b else (a / b - 1) * 100

    year = datetime.now(timezone.utc).year
    ytd_base = next((c for t, c in pts if datetime.fromtimestamp(t, timezone.utc).year == year), None)
    prior = [c for t, c in pts if datetime.fromtimestamp(t, timezone.utc).year < year]
    if prior:
        ytd_base = prior[-1]
    vols_raw = res["indicators"]["quote"][0].get("volume") or []
    vols = [v for c, v in zip(closes, vols_raw) if c is not None and v is not None]
    base = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else 0
    vol_x = vols[-1] / base if base else None

    def ma(n):
        return sum(series[-n:]) / n if len(series) >= n else None

    return {
        "ma50": ma(50), "ma200": ma(200), "vol_x": vol_x, "rsi": rsi14(series),
        "symbol": symbol, "last": last, "prev": prev,
        "chg": None if prev is None else last - prev,
        "pct": pct(last, prev), "w1": pct(last, ago(5)), "m1": pct(last, ago(21)),
        "ytd": pct(last, ytd_base),
        "hi52": max(series), "lo52": min(series),
        "spark": [round(x, 4) for x in series[-45:]],
        "asof": datetime.fromtimestamp(meta.get("regularMarketTime", pts[-1][0]), timezone.utc).isoformat(),
    }

def news(name, url, limit=8):
    root = ET.fromstring(get(url))
    items = []
    for it in root.iter("item"):
        items.append({"source": name, "title": (it.findtext("title") or "").strip(),
                      "link": (it.findtext("link") or "").strip(), "time": (it.findtext("pubDate") or "").strip()})
        if len(items) >= limit:
            break
    return items

# Bloomberg country suffix -> Yahoo suffixes to try, in order (Taiwan names are on either the main
# board .TW or the over-the-counter board .TWO, so both are tried)
BBG_SUFFIX = {"TT": [".TW", ".TWO"], "JP": [".T"], "HK": [".HK"], "NO": [".OL"], "LN": [".L"], "GR": [".DE"],
              "GY": [".DE"], "FP": [".PA"], "NA": [".AS"], "SW": [".SW"], "KS": [".KS"], "AU": [".AX"],
              "CN": [".TO"], "IT": [".MI"], "SM": [".MC"], "SS": [".ST"], "DC": [".CO"], "FH": [".HE"],
              "IN": [".NS"], "SP": [".SI"]}
US_SUFFIX = ("US", "UN", "UQ", "UW", "UA")
# Yahoo suffix -> TradingView exchange prefix (for the live quotes box)
TV_EXCH = {".TW": "TWSE", ".TWO": "TPEX", ".SZ": "SZSE", ".SS": "SSE", ".T": "TSE", ".HK": "HKEX", ".OL": "OSL",
           ".L": "LSE", ".DE": "XETR", ".PA": "EURONEXT", ".AS": "EURONEXT", ".SW": "SIX", ".KS": "KRX",
           ".AX": "ASX", ".TO": "TSX", ".MI": "MIL", ".MC": "BME", ".ST": "OMXSTO", ".CO": "OMXCOP",
           ".HE": "OMXHEX", ".NS": "NSE", ".SI": "SGX"}


def yahoo_candidates(code):
    """'SHOP US' -> (['SHOP'], 'SHOP');  '2345 TT' -> (['2345.TW', '2345.TWO'], '2345 TT');  '6809 HK' -> (['6809.HK'], ...)"""
    code = code.strip().upper()
    m = re.match(r"^(.+?)\s+([A-Z]{2})$", code)
    if not m:
        return [code.replace("/", "-").replace(" ", "")], code
    base, cc = m.group(1).replace(" ", "").replace("/", "-"), m.group(2)
    if cc in US_SUFFIX:
        return [base], base
    if cc == "CH":   # mainland China: 6xxxxx = Shanghai, otherwise Shenzhen
        return [base + (".SS" if base.startswith("6") else ".SZ")], code
    if cc == "HK":
        base = base.lstrip("0").zfill(4)
    return [base + x for x in BBG_SUFFIX.get(cc, [""])], code


def tv_symbol(ysym, exch_override=""):
    base = ysym
    for sfx in sorted(TV_EXCH, key=len, reverse=True):
        if ysym.endswith(sfx):
            base, ex = ysym[: -len(sfx)], TV_EXCH[sfx]
            if ex == "HKEX":
                base = base.lstrip("0") or "0"
            return f"{exch_override or ex}:{base}"
    return f"{exch_override}:{base}" if exch_override else base


def yahoo_any(cands):
    last = None
    for c in cands:
        try:
            d = yahoo(c)
            d["ysym"] = c
            return d
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def read_watchlist(path):
    """watchlist.txt -> [{"name": basket, "items": [(yahoo candidates, company name, TradingView exchange, display code)]}]"""
    groups, cur = [], None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#")[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = {"name": line[1:-1].strip(), "items": []}
                groups.append(cur)
                continue
            if cur is None:
                cur = {"name": "Watchlist", "items": []}
                groups.append(cur)
            code, _, rest = line.partition("|")
            name, _, exch = rest.partition("|")
            if code.strip():
                cands, disp = yahoo_candidates(code)
                cur["items"].append((cands, name.strip() or disp, exch.strip().upper(), disp))
    return groups


def build_watchlist(path_in, path_out, spx):
    groups = read_watchlist(path_in)
    wl = {"generated": datetime.now(timezone.utc).isoformat(), "groups": [], "errors": [],
          "spx": {"m1": spx.get("m1"), "ytd": spx.get("ytd"), "pct": spx.get("pct")} if spx else {}}

    def safe2(fn, *a):
        try:
            return fn(*a), None
        except Exception as e:  # noqa: BLE001
            return None, f"{fn.__name__} {a[0]}: {e}"

    with ThreadPoolExecutor(max_workers=8) as ex:
        jobs, cache = [], {}
        for g in groups:
            for cands, name, exch, disp in g["items"]:
                key = tuple(cands)
                if key not in cache:   # a stock in two baskets (e.g. Cisco) is fetched once
                    feed = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(cands[0])}&region=US&lang=en-US"
                    cache[key] = (ex.submit(safe2, yahoo_any, list(cands)), ex.submit(safe2, news, disp, feed, 3))
                jobs.append((g["name"], cands, name, exch, disp, cache[key]))
        by = {g["name"]: {"name": g["name"], "rows": []} for g in groups}
        for gname, cands, name, exch, disp, (qf, nf) in jobs:
            q, err = qf.result()
            nw, _ = nf.result()   # missing headlines (common for non-US names) are not an error
            if err:
                wl["errors"].append(err)
                by[gname]["rows"].append({"symbol": disp, "label": name, "missing": True, "tv": tv_symbol(cands[0], exch)})
                continue
            q = dict(q)
            q["symbol"] = disp
            q["label"] = name
            q["tv"] = tv_symbol(q.get("ysym", cands[0]), exch)
            q["news"] = [{"title": n["title"], "link": n["link"], "time": n["time"]} for n in (nw or [])]
            by[gname]["rows"].append(q)
    wl["groups"] = [by[g["name"]] for g in groups]
    total = sum(len(g["rows"]) for g in wl["groups"])
    if total and all(r.get("missing") for g in wl["groups"] for r in g["rows"]):
        for e in wl["errors"][:10]:
            print("WARN watchlist", e)
        print("No stock could be fetched; keeping the previously published data.", file=sys.stderr)
        sys.exit(1)
    with open(path_out, "w") as f:
        json.dump(wl, f, separators=(",", ":"))
    n = sum(len(g["rows"]) for g in wl["groups"])
    bad = sum(1 for g in wl["groups"] for r in g["rows"] if r.get("missing"))
    print(f"wrote {path_out}: {n} stocks in {len(groups)} baskets, {bad} without data")
    for e in wl["errors"]:
        print("WARN watchlist", e)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "docs"
    os.makedirs(out_dir, exist_ok=True)
    spx = {}
    try:   # S&P 500 is the yardstick for the "vs S&P 1M" column
        spx = yahoo("^GSPC")
    except Exception as e:  # noqa: BLE001
        print("WARN S&P 500 reference unavailable:", e)
    wl_in = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "watchlist.txt")
    build_watchlist(wl_in, os.path.join(out_dir, "watchlist.json"), spx)


if __name__ == "__main__":
    main()
