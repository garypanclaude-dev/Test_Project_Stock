# CLAUDE.md — Test_Project_Stock

> 此檔案由 Claude Code 維護。每次專案結構有異動（新增/刪除/移動檔案或資料夾）時，請同步更新本文件。

---

## 專案概述

**全棧股票智能分析平台**，支援台灣（TW）與美國（US）股市。  
後端使用 FastAPI + SQLite + XGBoost，前端使用 React 19 + TypeScript + Tailwind CSS。  
系統自動爬取歷史股價、訓練機器學習模型，並提供當日推薦股票與交易建議。

---

## 技術棧

| 層次 | 技術 | 版本 |
|------|------|------|
| 後端框架 | FastAPI | 0.111.0 |
| ASGI 伺服器 | Uvicorn | 0.29.0 |
| 資料庫 | SQLite + SQLAlchemy ORM | 2.0.30 |
| 機器學習 | XGBoost | 2.0.3 |
| 前端框架 | React | 19.2.5 |
| 前端語言 | TypeScript | ~6.0.2 |
| 打包工具 | Vite | 8.0.10 |
| 樣式 | Tailwind CSS | 4.2.4 |
| 路由 | React Router | 7.15.0 |
| 圖表庫 | lightweight-charts | 5.2.0 |
| HTTP 客戶端 | Axios | 1.16.0 |
| 排程 | APScheduler | 3.10.4 |

---

## 目錄結構

```
Test_Project_Stock/
├── CLAUDE.md                      # 本文件（專案結構概覽）
├── setup.bat                      # 初始安裝腳本（建立 venv、pip install）
├── start.bat                      # 啟動腳本（同時啟動後端 + 前端）
│
├── backend/                       # Python 後端
│   ├── main.py                    # FastAPI 應用入口，CORS、生命週期、DB 遷移
│   ├── requirements.txt           # Python 依賴清單
│   ├── stocks.db                  # SQLite 資料庫（OHLCV 歷史 + 預測結果）
│   ├── model/
│   │   └── xgb_model.pkl          # 訓練後的 XGBoost 模型
│   ├── venv/                      # Python 虛擬環境（不納入版本控制）
│   └── app/
│       ├── __init__.py
│       ├── database.py            # SQLAlchemy session 工廠與 ORM 基類
│       ├── api/
│       │   └── routes.py          # RESTful 端點（5 個，詳見下方）
│       ├── models/
│       │   └── stock.py           # 四個 ORM 資料表定義
│       ├── services/
│       │   ├── collector.py       # 股票資料爬取（台股證交所 + S&P 500）
│       │   └── predictor.py       # 特徵工程 + XGBoost 訓練 + 預測推薦
│       └── scheduler/
│           └── tasks.py           # APScheduler 定時任務（台/美股更新、週訓）
│
└── frontend/                      # React TypeScript 前端
    ├── index.html                 # HTML 入口
    ├── package.json               # Node.js 依賴與腳本
    ├── vite.config.ts             # Vite 配置（API proxy → localhost:8000）
    ├── tsconfig.json              # TypeScript 配置
    ├── public/
    │   ├── favicon.svg
    │   └── icons.svg
    ├── assets/
    │   └── hero.png
    ├── node_modules/              # NPM 依賴（不納入版本控制）
    └── src/
        ├── main.tsx               # React 應用啟動點
        ├── App.tsx                # 根元件，路由設定（/ 和 /stock/:symbol）
        ├── App.css
        ├── index.css              # 全局樣式（深色主題）
        ├── api/
        │   └── client.ts          # TypeScript 型別定義 + Axios API 方法
        ├── pages/
        │   ├── Dashboard.tsx      # 主儀表板（推薦列表、30 秒自動刷新、進度狀態）
        │   └── StockDetail.tsx    # 股票詳情頁（K 線圖、技術指標計算）
        └── components/
            ├── RecommendationCard.tsx  # 推薦卡片（概率、買賣建議、停利/停損）
            ├── StockChart.tsx          # K 線圖（lightweight-charts，MA5/20/60）
            └── Navbar.tsx              # 導航欄
```

---

## API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET` | `/api/recommendations` | 取得今日推薦股票（TW/US，依概率排序） |
| `GET` | `/api/stocks/search` | 模糊搜尋股票名稱或代碼 |
| `GET` | `/api/stocks/{symbol}/chart` | 取得 K 線圖資料（預設 180 天） |
| `GET` | `/api/scheduler/status` | 查詢資料收集進度 |
| `POST` | `/api/scheduler/trigger` | 手動觸發資料更新 |

---

## 資料庫資料表

| 資料表 | 說明 |
|--------|------|
| `stocks` | 股票清單（symbol、name、market、sector） |
| `stock_prices` | OHLCV 日線歷史資料 |
| `predictions` | AI 預測結果（概率、技術指標、交易建議） |
| `collector_status` | 資料收集狀態追蹤 |

---

## 機器學習特徵

- RSI(14)、MACD、布林通道、KD 隨機指標
- 移動平均距離、ATR(14)、交易量比
- **標籤定義**：5 日內上漲 3% 為正樣本
- **模型**：XGBoost（300 棵決策樹）
- **模型路徑**：`backend/model/xgb_model.pkl`

---

## 排程任務

| 時間（UTC） | 任務 |
|-------------|------|
| 09:00 每日 | 台股增量更新 + 重新預測 |
| 22:00 每日 | 美股增量更新 + 重新預測 |
| 週日 01:00 | 全量重新訓練 XGBoost 模型 |

---

## 資料流程

```
啟動 → 檢查 DB 記錄數
       ├─ < 10,000 筆 → collect_all()（下載所有股票 2 年歷史）
       └─ ≥ 10,000 筆 → collect_incremental()（僅更新最新日期之後）
               ↓
         train_model() → predict_today() → API 提供推薦
               ↓
         前端 Dashboard 每 30 秒 poll API 更新顯示
```

---

## 啟動方式

```bat
# 首次安裝
setup.bat

# 日常啟動（同時開後端 :8000 + 前端 :5173）
start.bat
```

---

## 重要路徑

| 用途 | 路徑 |
|------|------|
| SQLite 資料庫 | `backend/stocks.db` |
| XGBoost 模型 | `backend/model/xgb_model.pkl` |
| Python 虛擬環境 | `backend/venv/` |
| API 代理設定 | `frontend/vite.config.ts` |

---

*最後更新：2026-05-12*
