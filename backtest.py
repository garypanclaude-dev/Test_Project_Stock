"""
Walk-forward backtest — v2 (mirrors updated predictor.py)

Changes from v1:
  1. Time-based train/test split (no random shuffle of time-series)
  2. Label: 5th-day closing price > entry close * 1.02  (was: max-high * 1.03)
  3. XGBoost early stopping (rounds=30), max_depth 6->5, n_estimators 300->500 cap
  4. 4 new features: atr14_pct, ma20_slope, above_ma60, change_10d
  5. Take-profit: 1.5:1 risk-reward, capped at +25%  (was: 2:1, +40%)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score

# ── Universe ──────────────────────────────────────────────────────────────────
SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "JPM", "COST", "NFLX",
    "AMD",  "AVGO",
]

FEATURE_COLS = [
    "rsi", "macd", "macd_signal", "macd_hist",
    "bb_position", "k", "d",
    "ma5_dist", "ma20_dist", "ma60_dist",
    "change_1d", "change_3d", "change_5d", "change_10d",
    "vol_ratio",
    "atr14_pct",
    "ma20_slope",
    "above_ma60",
]

PROB_THRESHOLD = 0.60
RSI_LO, RSI_HI = 35, 78
VOL_RATIO_MIN  = 0.8
FORWARD_DAYS   = 5
LABEL_THRESH   = 0.02   # 5th-day close > 2%
TP_RATIO       = 1.5    # 1.5:1 risk-reward
TP_CAP         = 1.25   # +25% max


# ── Feature engineering (mirrors updated predictor.py) ────────────────────────
def calc_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    delta = df["close"].diff()
    gain  = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + gain / (loss + 1e-10)))

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    for p in [5, 10, 20, 60]:
        df[f"ma{p}"] = df["close"].rolling(p).mean()
    df["ma5_dist"]  = (df["close"] - df["ma5"])  / (df["ma5"]  + 1e-10)
    df["ma20_dist"] = (df["close"] - df["ma20"]) / (df["ma20"] + 1e-10)
    df["ma60_dist"] = (df["close"] - df["ma60"]) / (df["ma60"] + 1e-10)

    bb_mid = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    bb_up  = bb_mid + 2 * bb_std
    bb_dn  = bb_mid - 2 * bb_std
    df["bb_position"] = (df["close"] - bb_dn) / (bb_up - bb_dn + 1e-10)

    low14  = df["low"].rolling(14).min()
    high14 = df["high"].rolling(14).max()
    df["k"] = 100 * (df["close"] - low14) / (high14 - low14 + 1e-10)
    df["d"] = df["k"].rolling(3).mean()

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"]     = tr.rolling(14).mean()
    df["atr14_pct"] = df["atr14"] / (df["close"] + 1e-10)

    df["vol_ratio"]  = df["volume"] / (df["volume"].rolling(5).mean() + 1e-10)
    df["change_1d"]  = df["close"].pct_change(1)
    df["change_3d"]  = df["close"].pct_change(3)
    df["change_5d"]  = df["close"].pct_change(5)
    df["change_10d"] = df["close"].pct_change(10)

    df["ma20_slope"] = (df["ma20"] - df["ma20"].shift(5)) / (df["ma20"].shift(5) + 1e-10)
    df["above_ma60"] = (df["close"] > df["ma60"]).astype(float)
    return df


def create_labels(df: pd.DataFrame) -> pd.DataFrame:
    closes = df["close"].values
    labels = []
    for i in range(len(closes)):
        if i + FORWARD_DAYS >= len(closes):
            labels.append(np.nan)
        else:
            future_close = closes[i + FORWARD_DAYS]
            labels.append(1 if future_close > closes[i] * (1 + LABEL_THRESH) else 0)
    df["label"] = labels
    return df


# ── Download ───────────────────────────────────────────────────────────────────
def download_all(symbols, start="2020-01-01") -> dict:
    print(f"Downloading {len(symbols)} tickers ...")
    data = {}
    for sym in symbols:
        try:
            raw = yf.download(sym, start=start, auto_adjust=True, progress=False)
            if raw.empty or len(raw) < 200:
                continue
            raw.columns = [c if isinstance(c, str) else c[0] for c in raw.columns]
            data[sym] = raw
            print(f"  {sym}: {len(raw)} rows")
        except Exception as e:
            print(f"  {sym}: SKIP ({e})")
    return data


# ── Walk-forward backtest ──────────────────────────────────────────────────────
def run_backtest(raw_data: dict):
    all_dates = sorted({idx for df in raw_data.values() for idx in df.index})
    end_dt    = all_dates[-1]

    TRAIN_MONTHS = 18
    TEST_MONTHS  = 3

    periods = []
    t = pd.Timestamp("2021-07-01")
    while True:
        train_end = t + pd.DateOffset(months=TRAIN_MONTHS)
        test_end  = train_end + pd.DateOffset(months=TEST_MONTHS)
        if test_end > end_dt:
            break
        periods.append((t, train_end, test_end))
        t += pd.DateOffset(months=TEST_MONTHS)

    all_trades  = []
    fold_aucs   = []

    for fold_i, (tr_start, tr_end, te_end) in enumerate(periods):
        # Build training set
        train_frames = []
        for sym, df in raw_data.items():
            sub = df[(df.index >= tr_start) & (df.index < tr_end)].copy()
            if len(sub) < 120:
                continue
            sub = calc_features(sub)
            sub = create_labels(sub)
            sub["symbol"] = sym
            sub["date"] = sub.index.date   # preserve date for time-based split
            train_frames.append(sub)

        if not train_frames:
            continue
        combined = pd.concat(train_frames, ignore_index=True)
        combined = combined.dropna(subset=FEATURE_COLS + ["label"])
        if len(combined) < 200:
            continue

        # [改善 1] Time-based split within this fold's training window
        combined = combined.sort_values("date").reset_index(drop=True)
        split_idx = int(len(combined) * 0.8)
        X_tr = combined.iloc[:split_idx][FEATURE_COLS]
        y_tr = combined.iloc[:split_idx]["label"].astype(int)
        X_va = combined.iloc[split_idx:][FEATURE_COLS]
        y_va = combined.iloc[split_idx:]["label"].astype(int)

        # [改善 3] Early stopping, max_depth=5
        model = XGBClassifier(
            n_estimators=500, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            eval_metric="logloss", early_stopping_rounds=30,
            random_state=42, n_jobs=-1,
        )
        model.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)

        val_auc = roc_auc_score(y_va, model.predict_proba(X_va)[:, 1])
        best_iter = getattr(model, "best_iteration", 500)

        # Generate signals on test window
        for sym, df in raw_data.items():
            lookback_start = tr_end - pd.DateOffset(days=90)
            full_sub = df[(df.index >= lookback_start) & (df.index <= te_end)].copy()
            full_sub = calc_features(full_sub)
            full_sub["in_test"] = full_sub.index >= tr_end

            rows_list = full_sub.to_dict("records")
            idx_list  = list(full_sub.index)

            for i, (idx, row) in enumerate(zip(idx_list, rows_list)):
                if not row["in_test"]:
                    continue
                if any(pd.isna(row.get(c, np.nan)) for c in FEATURE_COLS):
                    continue

                prob  = float(model.predict_proba(pd.DataFrame([{c: row[c] for c in FEATURE_COLS}]))[0][1])
                rsi_v = float(row["rsi"])
                vol_r = float(row["vol_ratio"])

                if prob < PROB_THRESHOLD:
                    continue
                if not (RSI_LO <= rsi_v <= RSI_HI):
                    continue
                if vol_r < VOL_RATIO_MIN:
                    continue

                close_p = float(row["close"])
                atr     = float(row["atr14"]) if not pd.isna(row.get("atr14", np.nan)) else close_p * 0.02

                recent_lows = [rows_list[max(0, i-k)]["low"] for k in range(3)]
                buy_low  = min(min(recent_lows), close_p * 0.995)
                buy_high = close_p

                raw_stop  = buy_low - 1.5 * atr
                stop_loss = max(buy_low * 0.80, min(raw_stop, buy_low * 0.97))
                risk      = buy_low - stop_loss

                # [改善 5] 1.5:1 TP, +25% cap
                raw_tp      = buy_high + TP_RATIO * risk
                take_profit = min(raw_tp, buy_high * TP_CAP)

                if i + 1 >= len(idx_list):
                    continue
                entry_price = float(rows_list[i + 1]["open"])
                if pd.isna(entry_price) or entry_price <= 0:
                    continue

                exit_price  = None
                exit_reason = "timeout"
                for j in range(i + 1, min(i + 1 + FORWARD_DAYS, len(idx_list))):
                    bar      = rows_list[j]
                    bar_high = float(bar.get("high", np.nan))
                    bar_low  = float(bar.get("low", np.nan))
                    if pd.isna(bar_high) or pd.isna(bar_low):
                        continue
                    if bar_low <= stop_loss:
                        exit_price  = stop_loss
                        exit_reason = "stop_loss"
                        break
                    if bar_high >= take_profit:
                        exit_price  = take_profit
                        exit_reason = "take_profit"
                        break

                if exit_price is None:
                    last_j     = min(i + FORWARD_DAYS, len(idx_list) - 1)
                    exit_price = float(rows_list[last_j]["close"])

                pnl_pct = (exit_price - entry_price) / entry_price

                all_trades.append({
                    "fold":        fold_i + 1,
                    "symbol":      sym,
                    "signal_date": str(idx.date()),
                    "entry_price": round(entry_price, 4),
                    "exit_price":  round(exit_price, 4),
                    "stop_loss":   round(stop_loss, 4),
                    "take_profit": round(take_profit, 4),
                    "prob":        round(prob, 4),
                    "rsi":         round(rsi_v, 2),
                    "exit_reason": exit_reason,
                    "pnl_pct":     round(pnl_pct, 6),
                })

        fold_aucs.append(val_auc)
        print(f"  Fold {fold_i+1}: {tr_start.date()} to {tr_end.date()} "
              f"| val-AUC={val_auc:.4f} best_iter={best_iter} "
              f"| signals so far={len(all_trades)}")

    return pd.DataFrame(all_trades), fold_aucs


# ── Metrics ────────────────────────────────────────────────────────────────────
def compute_metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    r    = trades["pnl_pct"]
    wins = (r > 0).sum()
    total = len(r)
    losses = total - wins

    avg_win  = r[r > 0].mean() if wins   else 0.0
    avg_loss = r[r <= 0].mean() if losses else 0.0
    win_rate = wins / total

    kelly = (win_rate / (-avg_loss / avg_win) - (1 - win_rate)) if avg_loss != 0 and avg_win != 0 else np.nan

    equity = (1 + r).cumprod()
    max_dd = ((equity.cummax() - equity) / equity.cummax()).max()
    sharpe = (r.mean() / (r.std() + 1e-10)) * np.sqrt(252 / FORWARD_DAYS)

    return {
        "total_trades":     total,
        "win_rate":         round(win_rate * 100, 2),
        "avg_win_pct":      round(avg_win * 100, 2),
        "avg_loss_pct":     round(avg_loss * 100, 2),
        "expectancy_pct":   round(r.mean() * 100, 4),
        "total_return_pct": round((equity.iloc[-1] - 1) * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio":     round(sharpe, 3),
        "kelly_pct":        round(kelly * 100, 2) if not np.isnan(kelly) else "N/A",
        "exit_counts":      trades["exit_reason"].value_counts().to_dict(),
    }


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raw_data = download_all(SYMBOLS)
    if not raw_data:
        print("ERROR: no data.")
        sys.exit(1)

    print(f"\nRunning walk-forward backtest (v2) on {len(raw_data)} symbols ...\n")
    trades, fold_aucs = run_backtest(raw_data)

    SEP = "=" * 62
    print(f"\n{SEP}")
    print("BACKTEST v2 RESULTS")
    print(SEP)

    if trades.empty:
        print("No trades generated.")
        sys.exit(0)

    m = compute_metrics(trades)
    print(f"Total Trades        : {m['total_trades']}")
    print(f"Win Rate            : {m['win_rate']}%")
    print(f"Avg Win             : +{m['avg_win_pct']}%")
    print(f"Avg Loss            : {m['avg_loss_pct']}%")
    print(f"Expectancy/trade    : {m['expectancy_pct']}%")
    print(f"Compounded Return   : {m['total_return_pct']}%")
    print(f"Max Drawdown        : -{m['max_drawdown_pct']}%")
    print(f"Sharpe (annualised) : {m['sharpe_ratio']}")
    print(f"Kelly Fraction      : {m['kelly_pct']}%")
    print(f"\nExit breakdown:")
    for reason, cnt in m["exit_counts"].items():
        pct = cnt / m["total_trades"] * 100
        print(f"  {reason:<15}: {cnt:>4}  ({pct:.1f}%)")

    print(f"\nVal-AUC per fold    : {[round(a,4) for a in fold_aucs]}")
    print(f"Mean val-AUC        : {np.mean(fold_aucs):.4f}")

    if "fold" in trades.columns:
        print(f"\nPer-fold summary:")
        print(f"{'Fold':<6} {'Trades':<8} {'WinRate%':<10} {'Expect%':<10} {'MaxDD%':<10}")
        for fid, g in trades.groupby("fold"):
            fm = compute_metrics(g)
            print(f"{fid:<6} {fm['total_trades']:<8} {fm['win_rate']:<10} {fm['expectancy_pct']:<10} {fm['max_drawdown_pct']:<10}")

    print(f"\nPer-symbol summary:")
    print(f"{'Symbol':<8} {'Trades':<8} {'WinRate%':<10} {'Expect%':<10}")
    for sym, g in trades.groupby("symbol"):
        fm = compute_metrics(g)
        print(f"{sym:<8} {fm['total_trades']:<8} {fm['win_rate']:<10} {fm['expectancy_pct']:<10}")

    out = os.path.join(os.path.dirname(__file__), "backtest_trades_v2.csv")
    trades.to_csv(out, index=False)
    print(f"\nTrade log saved: {out}")
