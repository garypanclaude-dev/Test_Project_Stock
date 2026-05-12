import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, SessionLocal
from app.models.stock import Base
from app.api.routes import router
from app.scheduler.tasks import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _initial_collection():
    from app.models.stock import StockPrice, CollectorStatus
    from app.services.collector import collect_all, collect_incremental
    from app.services.predictor import train_model, predict_today
    from datetime import datetime

    db = SessionLocal()
    try:
        price_count = db.query(StockPrice).count()
        if price_count >= 10000:
            logger.info(f"DB has {price_count} price records — running incremental catch-up")
            # Reset any stale "running" status left over from a previous interrupted run
            row = db.query(CollectorStatus).first()
            if row and row.status == "running":
                row.status = "completed"
                row.message = "資料已是最新"
                row.updated_at = datetime.utcnow()
                db.commit()
                logger.info("Reset stale 'running' status to 'completed'")
            # Catch up any days missed while the backend was offline
            collect_incremental(db)
            predict_today(db)
            return
        logger.info(f"DB has {price_count} records — starting data collection (15~60 min)")
        collect_all(db)
        train_model(db)
        predict_today(db)
    except Exception as e:
        logger.error(f"Initial collection error: {e}", exc_info=True)
    finally:
        db.close()


def _migrate_db():
    """Add any missing columns to existing tables (SQLite doesn't support ALTER TABLE ADD COLUMN idempotently via ORM)."""
    new_cols = [
        ("predictions", "buy_low", "FLOAT"),
        ("predictions", "buy_high", "FLOAT"),
        ("predictions", "take_profit", "FLOAT"),
        ("predictions", "stop_loss", "FLOAT"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in new_cols:
            try:
                conn.execute(__import__("sqlalchemy").text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
                logger.info(f"Migration: added {table}.{col}")
            except Exception:
                pass  # Column already exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    _migrate_db()

    # Start background scheduler
    start_scheduler()

    # Run initial data collection in background thread
    t = threading.Thread(target=_initial_collection, daemon=True)
    t.start()

    yield

    stop_scheduler()


app = FastAPI(
    title="股票分析平台 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"message": "股票分析平台 API 運行中", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
