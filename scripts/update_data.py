from __future__ import annotations
import json, math, time
from datetime import datetime, timezone
from pathlib import Path
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "stocks.json"

def clean(v):
    try:
        if v is None:
            return None
        if hasattr(v, "item"):
            v = v.item()
        v = float(v)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None

def first(info, *keys):
    for k in keys:
        v = info.get(k)
        if v is not None:
            return clean(v)
    return None

def fair_value(eps, bvps, target_pe, dividend, price):
    values = []
    if eps and eps > 0 and bvps and bvps > 0:
        values.append(math.sqrt(22.5 * eps * bvps))
    if eps and eps > 0 and target_pe and target_pe > 0:
        values.append(eps * target_pe)
    # Dividend capitalization at a conservative 5% required yield.
    if dividend and dividend > 0:
        values.append(dividend / 0.05)
    if not values:
        return None
    return sum(values) / len(values)

def score_stock(x):
    score = 0
    pe=x.get("pe"); pb=x.get("pb"); roe=x.get("roe"); roa=x.get("roa")
    dy=x.get("dividend_yield"); cr=x.get("current_ratio"); da=x.get("debt_to_assets")
    mos=x.get("margin_of_safety"); fcf=x.get("free_cash_flow")
    if roe is not None:
        score += 18 if roe >= 15 else 12 if roe >= 10 else 6 if roe > 0 else 0
    if roa is not None:
        score += 10 if roa >= 7 else 6 if roa >= 3 else 0
    if pe is not None and pe > 0:
        score += 15 if pe <= 15 else 9 if pe <= 22 else 3
    if pb is not None and pb > 0:
        score += 8 if pb <= 2 else 5 if pb <= 3 else 2
    if cr is not None:
        score += 8 if cr >= 1.5 else 5 if cr >= 1 else 0
    if da is not None:
        score += 8 if da <= 35 else 4 if da <= 55 else 0
    if fcf is not None and fcf > 0:
        score += 8
    if dy is not None:
        score += 8 if dy >= 5 else 5 if dy >= 3 else 0
    if mos is not None:
        score += 9 if mos >= 20 else 6 if mos >= 10 else 3 if mos >= 0 else 0
    return min(100, round(score))

def recommendation(score, mos):
    mos = mos if mos is not None else -999
    if score >= 85 and mos >= 15:
        return "شراء قوي"
    if score >= 75 and mos >= 5:
        return "شراء تدريجي"
    if score >= 65:
        return "احتفاظ"
    if score >= 50:
        return "مراقبة"
    return "تجنب / تخفيض"

def update_one(base):
symbol = f'{base["code"]}.AB' if base["market"] == "ADX" else f'{base["code"]}.AE'    out = dict(base)
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        hist = t.history(period="5d", auto_adjust=False)
        price = first(info, "currentPrice", "regularMarketPrice", "previousClose")
        if price is None and not hist.empty:
            price = clean(hist["Close"].dropna().iloc[-1])

        eps = first(info, "trailingEps")
        bvps = first(info, "bookValue")
        pe = first(info, "trailingPE")
        pb = first(info, "priceToBook")
        roe_raw = first(info, "returnOnEquity")
        roa_raw = first(info, "returnOnAssets")
        roe = roe_raw * 100 if roe_raw is not None and abs(roe_raw) <= 2 else roe_raw
        roa = roa_raw * 100 if roa_raw is not None and abs(roa_raw) <= 2 else roa_raw
        div_yield_raw = first(info, "dividendYield")
        div_yield = div_yield_raw * 100 if div_yield_raw is not None and div_yield_raw <= 1 else div_yield_raw
        dividend = first(info, "dividendRate", "trailingAnnualDividendRate")
        current_ratio = first(info, "currentRatio")
        total_debt = first(info, "totalDebt")
        total_assets = first(info, "totalAssets")
        debt_to_assets = (total_debt / total_assets * 100) if total_debt and total_assets else None
        fcf = first(info, "freeCashflow")
        market_cap = first(info, "marketCap")
        target_pe = 15.0
        fair = fair_value(eps, bvps, target_pe, dividend, price)
        mos = ((fair-price)/fair*100) if fair and price else None

        out.update({
            "status":"ok" if price is not None else "partial",
            "price":price, "currency":info.get("currency","AED"),
            "market_cap":market_cap, "eps":eps, "book_value_per_share":bvps,
            "pe":pe, "pb":pb, "roe":roe, "roa":roa,
            "current_ratio":current_ratio, "total_debt":total_debt,
            "total_assets":total_assets, "debt_to_assets":debt_to_assets,
            "free_cash_flow":fcf, "dividend_per_share":dividend,
            "dividend_yield":div_yield, "fair_value":fair,
            "margin_of_safety":mos,
            "company_name":info.get("longName") or info.get("shortName") or base["name_ar"],
            "data_timestamp": datetime.now(timezone.utc).isoformat()
        })
        if price is None:
    out["score"] = None
    out["recommendation"] = "غير متوفر"
else:
    out["score"] = score_stock(out)
    out["recommendation"] = recommendation(out["score"], mos)
    except Exception as e:
        out.update({"status":"error","error":str(e)[:240]})
    return out

def main():
    payload=json.loads(DATA_FILE.read_text(encoding="utf-8"))
    updated=[]
    for stock in payload["stocks"]:
        updated.append(update_one(stock))
        time.sleep(0.35)
    payload["stocks"]=updated
    payload["updated_at"]=datetime.now(timezone.utc).isoformat()
    DATA_FILE.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    ok=sum(1 for x in updated if x.get("status") in ("ok","partial"))
    print(f"Updated {ok}/{len(updated)} stocks")

if __name__ == "__main__":
    main()
