"""
Model evaluation + backtest script.
Run: python backtest.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import os, joblib
import pandas as pd
import numpy as np
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score,
    confusion_matrix, classification_report
)
from sklearn.model_selection import train_test_split
from app.database import SessionLocal
from app.models.stock import StockPrice, Stock
from app.services.predictor import _calc_features, _create_labels, FEATURE_COLS

MODEL_PATH = "model/xgb_model.pkl"

# ── 1. Load model ──────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Loading model")
print("=" * 60)
model = joblib.load(MODEL_PATH)
print(f"Model: {type(model).__name__}  |  Trees: {model.n_estimators}")

# ── 2. Rebuild dataset for evaluation ──────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2 — Building evaluation dataset")
print("=" * 60)

db = SessionLocal()
symbols = [r[0] for r in db.query(StockPrice.symbol).distinct().all()]

all_frames = []
price_cache = {}   # symbol -> sorted DataFrame (for backtest)

for sym in symbols:
    rows = db.query(StockPrice).filter(
        StockPrice.symbol == sym
    ).order_by(StockPrice.date).all()

    if len(rows) < 120:
        continue

    df = pd.DataFrame([{
        "date": r.date, "open": r.open, "high": r.high,
        "low": r.low, "close": r.close, "volume": r.volume
    } for r in rows])

    df = _calc_features(df)
    df = _create_labels(df)
    df["symbol"] = sym
    all_frames.append(df)
    price_cache[sym] = df.reset_index(drop=True)

db.close()

combined = pd.concat(all_frames, ignore_index=True)
combined = combined.dropna(subset=FEATURE_COLS + ["label"])
X = combined[FEATURE_COLS]
y = combined["label"].astype(int)

print(f"Total samples : {len(combined):,}")
print(f"Stocks used   : {combined['symbol'].nunique():,}")
print(f"Label=1 (up)  : {int(y.sum()):,}  ({y.mean()*100:.1f}%)")
print(f"Label=0 (flat): {int((y==0).sum()):,}  ({(y==0).mean()*100:.1f}%)")

# ── 3. Model evaluation (same 80/20 split as training) ─────────────────────
print("\n" + "=" * 60)
print("STEP 3 — Model evaluation on 20% held-out test set")
print("=" * 60)

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

y_prob = model.predict_proba(X_test)[:, 1]
y_pred = (y_prob >= 0.60).astype(int)   # same threshold as production

auc     = roc_auc_score(y_test, y_prob)
prec    = precision_score(y_test, y_pred, zero_division=0)
recall  = recall_score(y_test, y_pred, zero_division=0)
f1      = f1_score(y_test, y_pred, zero_division=0)
cm      = confusion_matrix(y_test, y_pred)

print(f"\nTest set size : {len(y_test):,} samples")
print(f"AUC-ROC       : {auc:.4f}   (1.0=perfect, 0.5=random)")
print(f"Precision     : {prec:.4f}   (當模型說「會漲」，實際漲的比例)")
print(f"Recall        : {recall:.4f}   (實際漲的股票，被抓到的比例)")
print(f"F1 Score      : {f1:.4f}")
print(f"\nConfusion Matrix (threshold=0.60):")
print(f"                 Predicted 0   Predicted 1")
print(f"  Actual 0 (no rise)  {cm[0,0]:>7,}       {cm[0,1]:>7,}")
print(f"  Actual 1 (rise)     {cm[1,0]:>7,}       {cm[1,1]:>7,}")

# ── 4. Backtest ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 4 — Backtest simulation (2024-05 ~ 2026-05)")
print("=" * 60)
print("Rules:")
print("  Entry  : Buy at next day OPEN when model prob >= 0.60")
print("  Exit 1 : Take profit at +5% above entry price (any intraday high)")
print("  Exit 2 : Stop loss  at -5% below entry price (any intraday low)")
print("  Exit 3 : Force sell at close on day 5 if neither triggered")
print("  Cost   : 0.3% per round-trip (commission + slippage)")

PROB_THRESHOLD = 0.60
TAKE_PROFIT    = 0.05
STOP_LOSS      = -0.05
HOLD_DAYS      = 5
COST           = 0.003

trades = []

for sym, df in price_cache.items():
    df = df.copy()
    df = _calc_features(df)
    df = df.reset_index(drop=True)

    if len(df) < 120:
        continue

    # Get features for each row
    feat_ok = df[FEATURE_COLS].notna().all(axis=1)
    X_all = df.loc[feat_ok, FEATURE_COLS]
    if len(X_all) == 0:
        continue

    probs = model.predict_proba(X_all)[:, 1]
    df.loc[feat_ok, "prob"] = probs

    for i in range(len(df) - HOLD_DAYS - 1):
        if pd.isna(df.loc[i, "prob"]):
            continue
        if df.loc[i, "prob"] < PROB_THRESHOLD:
            continue

        # Entry: next day's open
        entry_idx = i + 1
        if entry_idx >= len(df):
            continue

        entry_price = df.loc[entry_idx, "open"]
        if pd.isna(entry_price) or entry_price <= 0:
            continue

        tp_price = entry_price * (1 + TAKE_PROFIT)
        sl_price = entry_price * (1 + STOP_LOSS)

        exit_price = None
        exit_day   = None

        for j in range(entry_idx, min(entry_idx + HOLD_DAYS, len(df))):
            high = df.loc[j, "high"]
            low  = df.loc[j, "low"]
            close= df.loc[j, "close"]

            if pd.isna(high) or pd.isna(low):
                continue

            # Check TP first (assume TP hit before SL if both in same day)
            if high >= tp_price:
                exit_price = tp_price
                exit_day   = j - entry_idx
                break
            if low <= sl_price:
                exit_price = sl_price
                exit_day   = j - entry_idx
                break

            # Force exit on last day
            if j == entry_idx + HOLD_DAYS - 1:
                exit_price = close
                exit_day   = j - entry_idx

        if exit_price is None:
            continue

        ret = (exit_price - entry_price) / entry_price - COST
        trades.append({
            "symbol"    : sym,
            "market"    : sym.split(".")[-1] if "." in sym else "US",
            "entry_date": df.loc[entry_idx, "date"],
            "entry"     : entry_price,
            "exit"      : exit_price,
            "hold_days" : exit_day + 1,
            "return"    : ret,
            "prob"      : df.loc[i, "prob"],
        })

trades_df = pd.DataFrame(trades)
print(f"\nTotal signals generated : {len(trades_df):,}")

if len(trades_df) == 0:
    print("No trades — cannot backtest.")
    sys.exit(0)

wins = trades_df[trades_df["return"] > 0]
losses = trades_df[trades_df["return"] < 0]

print(f"Win trades              : {len(wins):,}  ({len(wins)/len(trades_df)*100:.1f}%)")
print(f"Loss trades             : {len(losses):,}  ({len(losses)/len(trades_df)*100:.1f}%)")
print(f"\nAvg return per trade    : {trades_df['return'].mean()*100:+.2f}%")
print(f"Avg win                 : {wins['return'].mean()*100:+.2f}%")
print(f"Avg loss                : {losses['return'].mean()*100:+.2f}%")
print(f"Best trade              : {trades_df['return'].max()*100:+.2f}%")
print(f"Worst trade             : {trades_df['return'].min()*100:+.2f}%")
print(f"Avg hold days           : {trades_df['hold_days'].mean():.1f} days")

# Per-market breakdown
print("\n--- By Market ---")
for mkt in ["TW", "US"]:
    m = trades_df[trades_df["market"] == mkt]
    if len(m) == 0:
        continue
    wr = (m["return"] > 0).mean()
    print(f"{mkt}: {len(m):,} trades | WinRate {wr*100:.1f}% | AvgRet {m['return'].mean()*100:+.2f}%")

# Monthly return distribution
trades_df["month"] = pd.to_datetime(trades_df["entry_date"]).dt.to_period("M")
monthly = trades_df.groupby("month")["return"].mean() * 100
print("\n--- Monthly Avg Return (last 12 months) ---")
for period, val in monthly.tail(12).items():
    bar = "█" * int(abs(val) * 4)
    sign = "+" if val >= 0 else "-"
    print(f"  {period}  {val:+5.2f}%  {sign}{bar}")

# Probability bucket analysis
print("\n--- Return by Probability Bucket ---")
trades_df["bucket"] = pd.cut(trades_df["prob"], bins=[0.60, 0.65, 0.70, 0.75, 0.80, 1.01],
                              labels=["60-65%","65-70%","70-75%","75-80%","80%+"])
bucket_stats = trades_df.groupby("bucket", observed=True).agg(
    count=("return","count"),
    win_rate=("return", lambda x: (x>0).mean()),
    avg_ret=("return","mean")
)
for bucket, row in bucket_stats.iterrows():
    print(f"  Prob {bucket}: {int(row['count']):>5} trades | WinRate {row['win_rate']*100:.1f}% | AvgRet {row['avg_ret']*100:+.2f}%")

# Top performing symbols
print("\n--- Top 10 Stocks by Avg Return ---")
sym_stats = trades_df.groupby("symbol").agg(
    count=("return","count"), avg_ret=("return","mean")
).query("count >= 5").sort_values("avg_ret", ascending=False).head(10)
for sym, row in sym_stats.iterrows():
    name_short = sym.replace(".TW","")
    print(f"  {name_short:<12} {int(row['count']):>3} trades | AvgRet {row['avg_ret']*100:+.2f}%")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
