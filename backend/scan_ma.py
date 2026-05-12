import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from app.database import SessionLocal
from app.models.stock import Stock, StockPrice
from sqlalchemy import func

db = SessionLocal()

symbols = [r[0] for r in db.query(StockPrice.symbol)
           .group_by(StockPrice.symbol)
           .having(func.count(StockPrice.id) >= 80)
           .all()]
print(f"Scanning {len(symbols)} stocks...")

results = []

for sym in symbols:
    rows = (db.query(StockPrice)
            .filter(StockPrice.symbol == sym)
            .order_by(StockPrice.date.desc())
            .limit(90).all())
    if len(rows) < 80:
        continue
    rows = sorted(rows, key=lambda r: r.date)

    closes  = [r.close  for r in rows]
    volumes = [r.volume for r in rows]

    ma5  = float(np.mean(closes[-5:]))
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:]))

    latest_close = closes[-1]
    latest_vol   = volumes[-1]
    avg_vol20    = float(np.mean(volumes[-21:-1])) or 1.0

    ma_spread = (max(ma5, ma20, ma60) - min(ma5, ma20, ma60)) / min(ma5, ma20, ma60)
    above_ma  = latest_close > ma5 and latest_close > ma20
    vol_ratio = latest_vol / avg_vol20
    chg       = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] else 0

    if ma_spread < 0.04 and vol_ratio >= 1.5 and above_ma:
        stock = db.query(Stock).filter(Stock.symbol == sym).first()
        if not stock:
            continue
        results.append({
            "symbol":    sym,
            "name":      stock.name,
            "market":    stock.market,
            "close":     latest_close,
            "chg":       chg * 100,
            "spread":    ma_spread * 100,
            "vol_ratio": vol_ratio,
            "ma5":       ma5,
            "ma20":      ma20,
            "ma60":      ma60,
        })

db.close()
results.sort(key=lambda x: (x["spread"], -x["vol_ratio"]))

tw = [r for r in results if r["market"] == "TW"]
us = [r for r in results if r["market"] == "US"]
print(f"Found  TW={len(tw)}  US={len(us)}")

def show(rows, limit=15):
    hdr = "{:<12} {:<10} {:>9} {:>7} {:>8} {:>7} {:>9} {:>9} {:>9}"
    print(hdr.format("Symbol","Name","Close","Chg%","Spread%","VolRatio","MA5","MA20","MA60"))
    print("-"*90)
    fmt = "{:<12} {:<10} {:>9,.1f} {:>+7.2f} {:>8.2f} {:>7.2f}x {:>9,.1f} {:>9,.1f} {:>9,.1f}"
    for r in rows[:limit]:
        print(fmt.format(
            r["symbol"], r["name"][:8],
            r["close"], r["chg"], r["spread"], r["vol_ratio"],
            r["ma5"], r["ma20"], r["ma60"]
        ))

print("\n=== 台股 (全部) ===")
show(tw, limit=50)
print("\n=== 美股 ===")
show(us, limit=50)
