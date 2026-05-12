from sqlalchemy import Column, Integer, String, Float, Date, DateTime
from datetime import datetime
from app.database import Base


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    market = Column(String, nullable=False)  # TW or US
    sector = Column(String, nullable=True)


class StockPrice(Base):
    __tablename__ = "stock_prices"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    market = Column(String, nullable=False)
    date = Column(Date, index=True, nullable=False)
    probability = Column(Float, nullable=False)
    rsi = Column(Float)
    macd = Column(Float)
    current_price = Column(Float)
    price_change_1d = Column(Float)
    volume_ratio = Column(Float)
    # Trading suggestions for next day
    buy_low = Column(Float)       # lower bound of suggested entry range
    buy_high = Column(Float)      # upper bound (don't chase above this)
    take_profit = Column(Float)   # target exit price (+5%)
    stop_loss = Column(Float)     # stop loss price (-5%)
    created_at = Column(DateTime, default=datetime.utcnow)


class CollectorStatus(Base):
    __tablename__ = "collector_status"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="idle")  # idle / running / completed / error
    progress = Column(Integer, default=0)
    total = Column(Integer, default=0)
    message = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
