from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "stocks.json"


def clean(value):
    try:
        if value is None:
            return None
        if hasattr(value, "item"):
            value = value.item()
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    except Exception:
        return None


def first(info, *keys):
    for key in keys:
        value = info.get(key)
        if value is not None:
            return clean(value)
    return None


def validate_market_data(price, pe, pb, roe, roa, dividend_yield, market_cap):
    errors = []

    if price is not None and not 0.01 <= price <= 500:
        errors.append("السعر غير منطقي")
    if pe is not None and not 0 < pe <= 200:
        errors.append("مكرر الأرباح غير منطقي")
    if pb is not None and not 0 < pb <= 50:
        errors.append("مكرر القيمة الدفترية غير منطقي")
    if roe is not None and not -100 <= roe <= 300:
        errors.append("ROE غير منطقي")
    if roa is not None and not -50 <= roa <= 100:
        errors.append("ROA غير منطقي")
    if dividend_yield is not None and not 0 <= dividend_yield <= 30:
        errors.append("عائد التوزيعات غير منطقي")
    if market_cap is not None and not 1_000_000 <= market_cap <= 2_000_000_000_000:
        errors.append("القيمة السوقية غير منطقية")

    return errors


def fair_value(eps, bvps, target_pe, dividend):
    values = []
    if eps and eps > 0 and bvps and bvps > 0:
        values.append(math.sqrt(22.5 * eps * bvps))
    if eps and eps > 0 and target_pe and target_pe > 0:
        values.append(eps * target_pe)
    if dividend and dividend > 0:
        values.append(dividend / 0.05)
    return sum(values) / len(values) if values else None


def score_stock(stock):
    score = 0
    pe = stock.get("pe")
    pb = stock.get("pb")
    roe = stock.get("roe")
    roa = stock.get("roa")
    dividend_yield = stock.get("dividend_yield")
    current_ratio = stock.get("current_ratio")
    debt_to_assets = stock.get("debt_to_assets")
    margin_of_safety = stock.get("margin_of_safety")
    free_cash_flow = stock.get("free_cash_flow")

    if roe is not None:
        score += 18 if roe >= 15 else 12 if roe >= 10 else 6 if roe > 0 else 0
    if roa is not None:
        score += 10 if roa >= 7 else 6 if roa >= 3 else 0
    if pe is not None and pe > 0:
        score += 15 if pe <= 15 else 9 if pe <= 22 else 3
    if pb is not None and pb > 0:
        score += 8 if pb <= 2 else 5 if pb <= 3 else 2
    if current_ratio is not None:
        score += 8 if current_ratio >= 1.5 else 5 if current_ratio >= 1 else 0
    if debt_to_assets is not None:
        score += 8 if debt_to_assets <= 35 else 4 if debt_to_assets <= 55 else 0
    if free_cash_flow is not None and free_cash_flow > 0:
        score += 8
    if dividend_yield is not None:
        score += 8 if dividend_yield >= 5 else 5 if dividend_yield >= 3 else 0
    if margin_of_safety is not None:
        score += 9 if margin_of_safety >= 20 else 6 if margin_of_safety >= 10 else 3 if margin_of_safety >= 0 else 0

    return min(100, round(score))


def recommendation(score, margin_of_safety):
    margin_of_safety = margin_of_safety if margin_of_safety is not None else -999
    if score >= 85 and margin_of_safety >= 15:
        return "شراء قوي"
    if score >= 75 and margin_of_safety >= 5:
        return "شراء تدريجي"
    if score >= 65:
        return "احتفاظ"
    if score >= 50:
        return "مراقبة"
    return "تجنب / تخفيض"


def yahoo_symbol(base):
    suffix = ".AB" if base["market"] == "ADX" else ".AE"
    return f'{base["code"]}{suffix}'


def base_output(base):
    return {
        "symbol": base.get("symbol"),
        "code": base.get("code"),
        "name_ar": base.get("name_ar"),
        "market": base.get("market"),
        "sector": base.get("sector"),
    }


def update_one(base):
    symbol = yahoo_symbol(base)
    output = base_output(base)
    output["yahoo_symbol"] = symbol

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        history = ticker.history(period="5d", auto_adjust=False)

        price = first(info, "currentPrice", "regularMarketPrice", "previousClose")
        if price is None and not history.empty:
            closes = history["Close"].dropna()
            if not closes.empty:
                price = clean(closes.iloc[-1])

        eps = first(info, "trailingEps")
        bvps = first(info, "bookValue")
        pe = first(info, "trailingPE")
        pb = first(info, "priceToBook")

        roe_raw = first(info, "returnOnEquity")
        roa_raw = first(info, "returnOnAssets")
        roe = roe_raw * 100 if roe_raw is not None and abs(roe_raw) <= 2 else roe_raw
        roa = roa_raw * 100 if roa_raw is not None and abs(roa_raw) <= 2 else roa_raw

        dividend_yield_raw = first(info, "dividendYield")
        dividend_yield = (
            dividend_yield_raw * 100
            if dividend_yield_raw is not None and dividend_yield_raw <= 1
            else dividend_yield_raw
        )

        dividend = first(info, "dividendRate", "trailingAnnualDividendRate")
        current_ratio = first(info, "currentRatio")
        total_debt = first(info, "totalDebt")
        total_assets = first(info, "totalAssets")
        debt_to_assets = (
            total_debt / total_assets * 100
            if total_debt is not None and total_assets not in (None, 0)
            else None
        )
        free_cash_flow = first(info, "freeCashflow")
        market_cap = first(info, "marketCap")

        estimated_fair_value = fair_value(eps, bvps, 15.0, dividend)
        margin_of_safety = (
            (estimated_fair_value - price) / estimated_fair_value * 100
            if estimated_fair_value not in (None, 0) and price is not None
            else None
        )

        quality_errors = validate_market_data(
            price, pe, pb, roe, roa, dividend_yield, market_cap
        )

        if quality_errors:
            output.update({
                "status": "invalid",
                "quality_status": "مرفوض",
                "quality_errors": quality_errors,
                "price": None,
                "market_cap": None,
                "eps": None,
                "book_value_per_share": None,
                "pe": None,
                "pb": None,
                "roe": None,
                "roa": None,
                "current_ratio": None,
                "total_debt": None,
                "total_assets": None,
                "debt_to_assets": None,
                "free_cash_flow": None,
                "dividend_per_share": None,
                "dividend_yield": None,
                "fair_value": None,
                "margin_of_safety": None,
                "score": None,
                "recommendation": "بيانات غير موثوقة",
                "company_name": base.get("name_ar"),
                "data_timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return output

        output.update({
            "status": "ok" if price is not None else "partial",
            "quality_status": "مقبول" if price is not None else "ناقص",
            "quality_errors": [],
            "price": price,
            "currency": info.get("currency", "AED"),
            "market_cap": market_cap,
            "eps": eps,
            "book_value_per_share": bvps,
            "pe": pe,
            "pb": pb,
            "roe": roe,
            "roa": roa,
            "current_ratio": current_ratio,
            "total_debt": total_debt,
            "total_assets": total_assets,
            "debt_to_assets": debt_to_assets,
            "free_cash_flow": free_cash_flow,
            "dividend_per_share": dividend,
            "dividend_yield": dividend_yield,
            "fair_value": estimated_fair_value,
            "margin_of_safety": margin_of_safety,
            "company_name": info.get("longName") or info.get("shortName") or base["name_ar"],
            "data_timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if price is None:
            output["score"] = None
            output["recommendation"] = "غير متوفر"
        else:
            output["score"] = score_stock(output)
            output["recommendation"] = recommendation(output["score"], margin_of_safety)

    except Exception as error:
        output.update({
            "status": "error",
            "quality_status": "خطأ",
            "score": None,
            "recommendation": "غير متوفر",
            "error": str(error)[:240],
        })

    return output


def main():
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    updated_stocks = []

    for stock in payload["stocks"]:
        updated_stocks.append(update_one(stock))
        time.sleep(0.35)

    payload["stocks"] = updated_stocks
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    DATA_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    available = sum(1 for stock in updated_stocks if stock.get("status") == "ok")
    invalid = sum(1 for stock in updated_stocks if stock.get("status") == "invalid")
    print(
        f"Valid stocks: {available}/{len(updated_stocks)}; "
        f"Rejected by quality filter: {invalid}"
    )


if __name__ == "__main__":
    main()
