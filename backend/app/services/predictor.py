import pandas as pd
import numpy as np
import logging
import os
import joblib
from datetime import date
from typing import Callable, Optional
from sqlalchemy.orm import Session
from xgboost import XGBClassifier
import xgboost as xgb
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH = os.path.join(BASE_DIR, "model", "xgb_model.pkl")

# [改善 4] 新增 4 個市場情境特徵：atr14_pct, ma20_slope, above_ma60, change_10d
FEATURE_COLS = [
    "rsi", "macd", "macd_signal", "macd_hist",
    "bb_position", "k", "d",
    "ma5_dist", "ma20_dist", "ma60_dist",
    "change_1d", "change_3d", "change_5d", "change_10d",
    "vol_ratio",
    "atr14_pct",   # ATR14 占收盤價比例（標準化波動率）
    "ma20_slope",  # MA20 的 5 日斜率（趨勢方向）
    "above_ma60",  # 收盤是否高於 MA60（長期趨勢判斷，0/1）
]


def _calc_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # RSI(14)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Moving averages & distance
    for p in [5, 10, 20, 60]:
        df[f"ma{p}"] = df["close"].rolling(p).mean()
    df["ma5_dist"]  = (df["close"] - df["ma5"])  / (df["ma5"]  + 1e-10)
    df["ma20_dist"] = (df["close"] - df["ma20"]) / (df["ma20"] + 1e-10)
    df["ma60_dist"] = (df["close"] - df["ma60"]) / (df["ma60"] + 1e-10)

    # Bollinger Bands position (0=lower band, 1=upper band)
    bb_mid = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    df["bb_position"] = (df["close"] - bb_lower) / (bb_upper - bb_lower + 1e-10)

    # KD Stochastic
    low14  = df["low"].rolling(14).min()
    high14 = df["high"].rolling(14).max()
    df["k"] = 100 * (df["close"] - low14) / (high14 - low14 + 1e-10)
    df["d"] = df["k"].rolling(3).mean()

    # ATR(14)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"]     = tr.rolling(14).mean()
    df["atr14_pct"] = df["atr14"] / (df["close"] + 1e-10)   # 新增

    # Volume ratio
    df["vol_ratio"] = df["volume"] / (df["volume"].rolling(5).mean() + 1e-10)

    # Price changes
    df["change_1d"]  = df["close"].pct_change(1)
    df["change_3d"]  = df["close"].pct_change(3)
    df["change_5d"]  = df["close"].pct_change(5)
    df["change_10d"] = df["close"].pct_change(10)             # 新增

    # MA20 slope: 5-day rate of change of the trend line
    df["ma20_slope"] = (df["ma20"] - df["ma20"].shift(5)) / (df["ma20"].shift(5) + 1e-10)  # 新增

    # Long-term trend regime (1 = price above MA60, 0 = below)
    df["above_ma60"] = (df["close"] > df["ma60"]).astype(float)  # 新增

    return df


def _create_labels(df: pd.DataFrame, forward_days: int = 5, threshold: float = 0.02) -> pd.DataFrame:
    """[改善 2] 標籤改為第 5 日收盤 > 入場收盤 × 1.02，閾值從 3% 降至 2%。
    原本用 5 日內最高價會讓標籤偏樂觀，導致模型學到無法獲利的訊號。"""
    closes = df["close"].values
    labels = []
    for i in range(len(closes)):
        if i + forward_days >= len(closes):
            labels.append(np.nan)
        else:
            future_close = closes[i + forward_days]
            labels.append(1 if future_close > closes[i] * (1 + threshold) else 0)
    df["label"] = labels
    return df


class _ProgressCallback(xgb.callback.TrainingCallback):
    def __init__(self, fn: Callable[[int, int], None], total: int, every: int = 30):
        self._fn = fn
        self._total = total
        self._every = every

    def after_iteration(self, model, epoch, evals_log):
        if (epoch + 1) % self._every == 0 or epoch + 1 == self._total:
            self._fn(epoch + 1, self._total)
        return False


def train_model(db: Session, progress_callback: Optional[Callable[[int, int], None]] = None):
    from app.models.stock import StockPrice

    logger.info("Starting model training...")
    symbols = [r[0] for r in db.query(StockPrice.symbol).distinct().all()]
    all_frames = []

    for sym in symbols:
        rows = (
            db.query(StockPrice)
            .filter(StockPrice.symbol == sym)
            .order_by(StockPrice.date)
            .all()
        )
        if len(rows) < 120:
            continue

        df = pd.DataFrame(
            [{"date": r.date, "open": r.open, "high": r.high,
              "low": r.low, "close": r.close, "volume": r.volume}
             for r in rows]
        )
        df = _calc_features(df)
        df = _create_labels(df)
        all_frames.append(df)

    if not all_frames:
        logger.error("No data available for training")
        return None

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.dropna(subset=FEATURE_COLS + ["label"])

    if len(combined) < 500:
        logger.error("Not enough training samples")
        return None

    # [改善 1] 時序切分：按 date 排序後取後 20% 作驗證集，避免 look-ahead bias。
    # 原本的 train_test_split(random_state=42) 會讓較晚的資料（含標籤所需的未來價格）
    # 出現在訓練集，導致 AUC 虛高到 0.997。
    combined = combined.sort_values("date").reset_index(drop=True)
    split_idx = int(len(combined) * 0.8)

    X_train = combined.iloc[:split_idx][FEATURE_COLS]
    y_train = combined.iloc[:split_idx]["label"].astype(int)
    X_test  = combined.iloc[split_idx:][FEATURE_COLS]
    y_test  = combined.iloc[split_idx:]["label"].astype(int)

    # [改善 3] n_estimators 上限 500，early_stopping_rounds=30 自動找最佳棵數；
    # max_depth 從 6 降至 5 減少過擬合。
    n_estimators = 500
    callbacks = []
    if progress_callback:
        callbacks.append(_ProgressCallback(progress_callback, n_estimators, every=30))

    model = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        early_stopping_rounds=30,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
        callbacks=callbacks if callbacks else None,
    )

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    from sklearn.metrics import roc_auc_score
    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    best_iter = getattr(model, "best_iteration", n_estimators)
    logger.info(f"Model trained — AUC: {auc:.4f}, best_iteration: {best_iter}, samples: {len(combined)}")
    return model


def predict_today(db: Session):
    from app.models.stock import Stock, StockPrice, Prediction

    if os.path.exists(MODEL_PATH):
        model = joblib.load(MODEL_PATH)
    else:
        model = train_model(db)
        if model is None:
            return

    today = date.today()
    stocks = db.query(Stock).all()
    predictions = []

    for stock in stocks:
        rows = (
            db.query(StockPrice)
            .filter(StockPrice.symbol == stock.symbol)
            .order_by(StockPrice.date.desc())
            .limit(200)
            .all()
        )
        if len(rows) < 65:
            continue

        rows = sorted(rows, key=lambda r: r.date)
        df = pd.DataFrame(
            [{"open": r.open, "high": r.high, "low": r.low,
              "close": r.close, "volume": r.volume}
             for r in rows]
        )
        df = _calc_features(df)
        latest = df.iloc[-1]

        if any(pd.isna(latest[c]) for c in FEATURE_COLS):
            continue

        X = pd.DataFrame([latest[FEATURE_COLS]])
        prob = float(model.predict_proba(X)[0][1])

        rsi_val       = float(latest["rsi"])
        vol_ratio_val = float(latest["vol_ratio"])

        # Quality filters
        if prob < 0.60:
            continue
        if rsi_val < 35 or rsi_val > 78:
            continue
        if vol_ratio_val < 0.8:
            continue

        close_price = round(float(latest["close"]), 2)
        atr = float(latest["atr14"]) if not pd.isna(latest.get("atr14", float("nan"))) else close_price * 0.02

        # Buy range: recent 3-day intraday low → today's close
        recent_low_3d = float(df["low"].iloc[-3:].min())
        buy_low  = round(min(recent_low_3d, close_price * 0.995), 2)
        buy_high = round(close_price, 2)

        # Stop loss: 1.5× ATR below the support; clamp to [-3%, -20%]
        raw_stop = buy_low - 1.5 * atr
        stop_low_bound  = buy_low * 0.80
        stop_high_bound = buy_low * 0.97
        stop_loss = round(max(stop_low_bound, min(raw_stop, stop_high_bound)), 2)

        # [改善 5] Take profit: 1.5:1 risk-reward（原本 2:1），上限改為 +25%（原本 +40%）。
        # 原本 TP 觸及率僅 3.9%，降低目標後更容易在有利狀況出場。
        risk = buy_low - stop_loss
        raw_tp = buy_high + 1.5 * risk
        take_profit = round(min(raw_tp, buy_high * 1.25), 2)

        predictions.append(
            {
                "symbol": stock.symbol,
                "name": stock.name,
                "market": stock.market,
                "date": today,
                "probability": round(prob, 4),
                "rsi": round(rsi_val, 2),
                "macd": round(float(latest["macd"]), 4),
                "current_price": close_price,
                "price_change_1d": round(float(latest["change_1d"]) if not pd.isna(latest["change_1d"]) else 0.0, 4),
                "volume_ratio": round(vol_ratio_val, 2),
                "buy_low": buy_low,
                "buy_high": buy_high,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
            }
        )

    predictions.sort(key=lambda x: x["probability"], reverse=True)

    db.query(Prediction).filter(Prediction.date == today).delete()
    for p in predictions:
        db.add(Prediction(**p))
    db.commit()

    tw_count = sum(1 for p in predictions if p["market"] == "TW")
    us_count = sum(1 for p in predictions if p["market"] == "US")
    logger.info(f"Predictions saved — TW: {tw_count}, US: {us_count}")
