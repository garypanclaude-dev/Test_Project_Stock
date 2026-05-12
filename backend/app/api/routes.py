from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.stock import Stock, StockPrice, Prediction, CollectorStatus

router = APIRouter()


# ── Pydantic response schemas ──────────────────────────────────────────────

class RecommendationItem(BaseModel):
    symbol: str
    name: str
    market: str
    probability: float
    current_price: float
    price_change_1d: float
    rsi: float
    volume_ratio: float
    buy_low: Optional[float]
    buy_high: Optional[float]
    take_profit: Optional[float]
    stop_loss: Optional[float]


class RecommendationsResponse(BaseModel):
    tw: list[RecommendationItem]
    us: list[RecommendationItem]
    last_update: Optional[datetime]


class ChartPoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class ChartResponse(BaseModel):
    symbol: str
    name: str
    market: str
    data: list[ChartPoint]


class StockSearchItem(BaseModel):
    symbol: str
    name: str
    market: str


class StatusResponse(BaseModel):
    status: str
    progress: int
    total: int
    message: str
    updated_at: Optional[datetime]


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(db: Session = Depends(get_db)):
    today = date.today()
    rows = (
        db.query(Prediction)
        .filter(Prediction.date == today)
        .order_by(desc(Prediction.probability))
        .all()
    )

    # If no predictions today, return most recent available
    if not rows:
        latest = db.query(Prediction.date).order_by(desc(Prediction.date)).first()
        if latest:
            rows = (
                db.query(Prediction)
                .filter(Prediction.date == latest[0])
                .order_by(desc(Prediction.probability))
                .all()
            )

    tw = [r for r in rows if r.market == "TW"][:10]
    us = [r for r in rows if r.market == "US"][:10]

    last_update = None
    status_row = db.query(CollectorStatus).first()
    if status_row:
        last_update = status_row.updated_at

    def to_item(r) -> RecommendationItem:
        return RecommendationItem(
            symbol=r.symbol,
            name=r.name,
            market=r.market,
            probability=r.probability,
            current_price=r.current_price or 0.0,
            price_change_1d=r.price_change_1d or 0.0,
            rsi=r.rsi or 0.0,
            volume_ratio=r.volume_ratio or 0.0,
            buy_low=r.buy_low,
            buy_high=r.buy_high,
            take_profit=r.take_profit,
            stop_loss=r.stop_loss,
        )

    return RecommendationsResponse(
        tw=[to_item(r) for r in tw],
        us=[to_item(r) for r in us],
        last_update=last_update,
    )


@router.get("/stocks/search", response_model=list[StockSearchItem])
def search_stocks(q: str = "", db: Session = Depends(get_db)):
    if len(q) < 1:
        return []
    q_upper = q.upper()
    results = (
        db.query(Stock)
        .filter(
            Stock.symbol.contains(q_upper) | Stock.name.contains(q)
        )
        .limit(20)
        .all()
    )
    return [StockSearchItem(symbol=r.symbol, name=r.name, market=r.market) for r in results]


@router.get("/stocks/{symbol}/chart", response_model=ChartResponse)
def get_chart(symbol: str, days: int = 180, db: Session = Depends(get_db)):
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    prices = (
        db.query(StockPrice)
        .filter(StockPrice.symbol == symbol)
        .order_by(desc(StockPrice.date))
        .limit(days)
        .all()
    )
    prices = sorted(prices, key=lambda r: r.date)

    data = [
        ChartPoint(
            date=str(p.date),
            open=p.open or 0.0,
            high=p.high or 0.0,
            low=p.low or 0.0,
            close=p.close or 0.0,
            volume=p.volume or 0.0,
        )
        for p in prices
    ]
    return ChartResponse(symbol=stock.symbol, name=stock.name, market=stock.market, data=data)


@router.get("/scheduler/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db)):
    row = db.query(CollectorStatus).first()
    if not row:
        return StatusResponse(status="idle", progress=0, total=0, message="尚未開始", updated_at=None)
    return StatusResponse(
        status=row.status,
        progress=row.progress,
        total=row.total,
        message=row.message or "",
        updated_at=row.updated_at,
    )


@router.post("/scheduler/trigger")
def trigger_collection(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    status_row = db.query(CollectorStatus).first()
    if status_row and status_row.status == "running":
        # Only block if the run is genuinely recent (updated within last 5 minutes)
        age_seconds = (datetime.utcnow() - status_row.updated_at).total_seconds() if status_row.updated_at else 999
        if age_seconds < 300:
            return {"message": "已在執行中"}
        # Stale "running" — reset and allow a fresh trigger
        status_row.status = "idle"
        db.commit()

    def run():
        from app.database import SessionLocal
        from app.services.collector import collect_incremental
        from app.services.predictor import train_model, predict_today
        from app.models.stock import CollectorStatus as CS
        from datetime import datetime
        local_db = SessionLocal()

        def set_status(status, progress, total, message):
            row = local_db.query(CS).first()
            if not row:
                row = CS()
                local_db.add(row)
            row.status = status
            row.progress = progress
            row.total = total
            row.message = message
            row.updated_at = datetime.utcnow()
            local_db.commit()

        try:
            # Phase 1: incremental data update
            stats = collect_incremental(local_db) or {}
            data_summary = stats.get("message", "資料更新完成")

            # Phase 2: model training with per-round progress
            N_ESTIMATORS = 300
            set_status("running", 0, N_ESTIMATORS, "模型訓練中... (0 / 300 棵決策樹)")

            def training_progress(current, total):
                set_status("running", current, total,
                           f"模型訓練中... ({current} / {total} 棵決策樹)")

            train_model(local_db, progress_callback=training_progress)

            # Phase 3: generate predictions
            set_status("running", 0, 0, "正在計算今日推薦...")
            predict_today(local_db)

            set_status("completed", N_ESTIMATORS, N_ESTIMATORS, f"推薦已更新｜{data_summary}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Triggered collection failed: {e}")
            set_status("error", 0, 0, f"更新失敗：{e}")
        finally:
            local_db.close()

    background_tasks.add_task(run)
    return {"message": "資料收集已開始"}
