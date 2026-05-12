import yfinance as yf
import pandas as pd
import requests
import logging
import time
import random
from datetime import date
from sqlalchemy.orm import Session
from app.models.stock import Stock, StockPrice, CollectorStatus

logger = logging.getLogger(__name__)

# Suppress yfinance's own verbose error logging — we handle errors ourselves
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _update_status(db: Session, status: str, progress: int, total: int, message: str):
    row = db.query(CollectorStatus).first()
    if not row:
        row = CollectorStatus()
        db.add(row)
    row.status = status
    row.progress = progress
    row.total = total
    row.message = message
    from datetime import datetime
    row.updated_at = datetime.utcnow()
    db.commit()


def get_tw_stock_list() -> list[dict]:
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        stocks = []
        for item in data:
            code = item.get("Code", "")
            name = item.get("Name", "")
            # Skip ETFs (00xx) and OTC funds — Yahoo Finance doesn't support them with .TW suffix
            if code and len(code) == 4 and code.isdigit() and not code.startswith("00"):
                stocks.append({"symbol": f"{code}.TW", "name": name, "market": "TW"})
        logger.info(f"Found {len(stocks)} TW stocks")
        return stocks
    except Exception as e:
        logger.error(f"Failed to get TW stock list: {e}")
        return []


def get_us_stock_list() -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; StockBot/1.0)"}
    try:
        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=headers, timeout=30,
        )
        resp.raise_for_status()
        from io import StringIO
        tables = pd.read_html(StringIO(resp.text), attrs={"id": "constituents"})
        df = tables[0]
        stocks = []
        for _, row in df.iterrows():
            symbol = str(row["Symbol"]).replace(".", "-")
            name = str(row.get("Security", ""))
            stocks.append({"symbol": symbol, "name": name, "market": "US"})
        logger.info(f"Found {len(stocks)} US stocks")
        return stocks
    except Exception as e:
        logger.error(f"Failed to get US stock list from Wikipedia: {e}")
        # Comprehensive fallback list
        return [
            {"symbol": "AAPL", "name": "Apple Inc.", "market": "US"},
            {"symbol": "MSFT", "name": "Microsoft Corp.", "market": "US"},
            {"symbol": "NVDA", "name": "NVIDIA Corp.", "market": "US"},
            {"symbol": "GOOGL", "name": "Alphabet Inc. Class A", "market": "US"},
            {"symbol": "GOOG", "name": "Alphabet Inc. Class C", "market": "US"},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "market": "US"},
            {"symbol": "META", "name": "Meta Platforms Inc.", "market": "US"},
            {"symbol": "TSLA", "name": "Tesla Inc.", "market": "US"},
            {"symbol": "BRK-B", "name": "Berkshire Hathaway", "market": "US"},
            {"symbol": "JPM", "name": "JPMorgan Chase", "market": "US"},
            {"symbol": "V", "name": "Visa Inc.", "market": "US"},
            {"symbol": "UNH", "name": "UnitedHealth Group", "market": "US"},
            {"symbol": "XOM", "name": "Exxon Mobil", "market": "US"},
            {"symbol": "MA", "name": "Mastercard", "market": "US"},
            {"symbol": "AVGO", "name": "Broadcom Inc.", "market": "US"},
            {"symbol": "PG", "name": "Procter & Gamble", "market": "US"},
            {"symbol": "JNJ", "name": "Johnson & Johnson", "market": "US"},
            {"symbol": "HD", "name": "Home Depot", "market": "US"},
            {"symbol": "COST", "name": "Costco Wholesale", "market": "US"},
            {"symbol": "ABBV", "name": "AbbVie Inc.", "market": "US"},
            {"symbol": "MRK", "name": "Merck & Co.", "market": "US"},
            {"symbol": "WMT", "name": "Walmart Inc.", "market": "US"},
            {"symbol": "CVX", "name": "Chevron Corp.", "market": "US"},
            {"symbol": "KO", "name": "Coca-Cola Co.", "market": "US"},
            {"symbol": "PEP", "name": "PepsiCo Inc.", "market": "US"},
            {"symbol": "ADBE", "name": "Adobe Inc.", "market": "US"},
            {"symbol": "AMD", "name": "Advanced Micro Devices", "market": "US"},
            {"symbol": "INTC", "name": "Intel Corp.", "market": "US"},
            {"symbol": "QCOM", "name": "Qualcomm Inc.", "market": "US"},
            {"symbol": "NFLX", "name": "Netflix Inc.", "market": "US"},
            {"symbol": "CRM", "name": "Salesforce Inc.", "market": "US"},
            {"symbol": "ORCL", "name": "Oracle Corp.", "market": "US"},
            {"symbol": "IBM", "name": "IBM Corp.", "market": "US"},
            {"symbol": "NOW", "name": "ServiceNow Inc.", "market": "US"},
            {"symbol": "UBER", "name": "Uber Technologies", "market": "US"},
            {"symbol": "PYPL", "name": "PayPal Holdings", "market": "US"},
            {"symbol": "BAC", "name": "Bank of America", "market": "US"},
            {"symbol": "GS", "name": "Goldman Sachs", "market": "US"},
            {"symbol": "MS", "name": "Morgan Stanley", "market": "US"},
            {"symbol": "WFC", "name": "Wells Fargo", "market": "US"},
            {"symbol": "C", "name": "Citigroup Inc.", "market": "US"},
            {"symbol": "SPGI", "name": "S&P Global Inc.", "market": "US"},
            {"symbol": "BLK", "name": "BlackRock Inc.", "market": "US"},
            {"symbol": "PFE", "name": "Pfizer Inc.", "market": "US"},
            {"symbol": "LLY", "name": "Eli Lilly", "market": "US"},
            {"symbol": "TMO", "name": "Thermo Fisher Scientific", "market": "US"},
            {"symbol": "DHR", "name": "Danaher Corp.", "market": "US"},
            {"symbol": "ABT", "name": "Abbott Laboratories", "market": "US"},
        ]


def _save_prices_from_df(db: Session, symbol: str, df: pd.DataFrame):
    if df is None or df.empty:
        return 0

    df = df.copy()
    df.columns = [c if isinstance(c, str) else c[0] for c in df.columns]

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(df.columns)):
        return 0

    df = df.dropna(subset=["Open", "High", "Low", "Close"])

    existing_dates = {
        r.date
        for r in db.query(StockPrice.date)
        .filter(StockPrice.symbol == symbol)
        .all()
    }

    added = 0
    for idx, row in df.iterrows():
        dt = idx.date() if hasattr(idx, "date") else idx
        if dt in existing_dates:
            continue
        db.add(
            StockPrice(
                symbol=symbol,
                date=dt,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
        )
        added += 1

    if added:
        db.commit()
    return added


def collect_all(db: Session):
    logger.info("Starting full data collection")
    tw_list = get_tw_stock_list()
    us_list = get_us_stock_list()
    all_stocks = tw_list + us_list

    _update_status(db, "running", 0, len(all_stocks), "正在更新股票清單...")

    # Upsert stock list
    for s in all_stocks:
        existing = db.query(Stock).filter(Stock.symbol == s["symbol"]).first()
        if not existing:
            db.add(Stock(symbol=s["symbol"], name=s["name"], market=s["market"]))
    db.commit()

    _update_status(db, "running", 0, len(all_stocks), "開始下載歷史資料...")

    # Download individually to avoid Yahoo Finance rate limits on batch requests
    done = 0
    for s in all_stocks:
        sym = s["symbol"]
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="2y", auto_adjust=True)
            if not hist.empty:
                _save_prices_from_df(db, sym, hist)
        except Exception as e:
            logger.debug(f"Skip {sym}: {e}")

        done += 1
        if done % 20 == 0:
            _update_status(
                db, "running", done, len(all_stocks),
                f"已下載 {done}/{len(all_stocks)} 支股票",
            )
        # Random delay to avoid rate limiting (0.3~0.7s per stock)
        time.sleep(random.uniform(0.3, 0.7))

    _update_status(db, "completed", len(all_stocks), len(all_stocks), "資料更新完成")
    logger.info("Data collection completed")


def collect_incremental(db: Session):
    """Smart incremental update — only downloads data since each stock's last record.
    For stocks with recent data this takes seconds instead of minutes."""
    from datetime import date as date_type
    from sqlalchemy import func as sqlfunc

    stocks = db.query(Stock).all()
    total = len(stocks)
    _update_status(db, "running", 0, total, "計算各股票需更新的日期範圍...")

    # Build a map of symbol -> latest date in DB
    latest_map = {
        row[0]: row[1]
        for row in db.query(StockPrice.symbol, sqlfunc.max(StockPrice.date))
        .group_by(StockPrice.symbol)
        .all()
    }

    today = date_type.today()
    done = 0
    skipped = 0      # already up-to-date (days_missing <= 0)
    downloaded = 0   # got new rows saved
    pending = 0      # downloaded but all rows were NaN/already-exist (data not settled yet)

    for stock in stocks:
        sym = stock.symbol
        last_date = latest_map.get(sym)

        if last_date is not None:
            days_missing = (today - last_date).days
            if days_missing < 0:
                # last_date is somehow in the future — skip
                skipped += 1
                done += 1
                continue
            # Always fetch at least 10d so gaps within the past week are filled.
            # _save_prices_from_df deduplicates by date, so re-fetching existing
            # rows is safe and free of side effects.
            period = f"{min(max(days_missing + 5, 10), 730)}d"
        else:
            period = "2y"

        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period=period, auto_adjust=True)
            if not hist.empty:
                added = _save_prices_from_df(db, sym, hist)
                if added:
                    downloaded += 1
                else:
                    # Data returned but nothing new saved (all NaN or all already in DB)
                    pending += 1
        except Exception as e:
            logger.debug(f"Skip {sym}: {e}")

        done += 1
        if done % 30 == 0:
            _update_status(
                db, "running", done, total,
                f"更新中 {done}/{total}（新資料:{downloaded} 待結算:{pending} 已最新:{skipped}）",
            )
        time.sleep(random.uniform(0.15, 0.35))

    if downloaded > 0:
        msg = f"新增 {downloaded} 支，{pending} 支今日收盤後可取得，{skipped} 支已最新"
    elif pending > 0:
        msg = f"{pending} 支股票今日收盤資料尚未結算，收盤後再按更新即可取得最新價格"
    else:
        msg = f"資料已是最新（{skipped} 支）"

    _update_status(db, "completed", total, total, msg)
    logger.info(f"Incremental update done: {downloaded} updated, {pending} pending, {skipped} current")
    return {"downloaded": downloaded, "pending": pending, "skipped": skipped, "message": msg}


def collect_market(db: Session, market: str):
    """Incremental update for a single market (TW or US)."""
    if market == "TW":
        stock_list = get_tw_stock_list()
    else:
        stock_list = get_us_stock_list()

    for s in stock_list:
        sym = s["symbol"]
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d", auto_adjust=True)
            if not hist.empty:
                _save_prices_from_df(db, sym, hist)
        except Exception as e:
            logger.debug(f"Incremental skip {sym}: {e}")
        time.sleep(random.uniform(0.2, 0.5))

    logger.info(f"Incremental update for {market} done")
