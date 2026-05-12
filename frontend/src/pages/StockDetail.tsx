import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getChart } from '../api/client'
import type { ChartResponse } from '../api/client'
import StockChart from '../components/StockChart'

function calcRSI(closes: number[], period = 14): number {
  if (closes.length < period + 1) return 0
  const gains: number[] = [], losses: number[] = []
  for (let i = closes.length - period; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    gains.push(d > 0 ? d : 0)
    losses.push(d < 0 ? -d : 0)
  }
  const ag = gains.reduce((a, b) => a + b, 0) / period
  const al = losses.reduce((a, b) => a + b, 0) / period
  return al === 0 ? 100 : 100 - 100 / (1 + ag / al)
}

function calcMACD(closes: number[]) {
  const ema = (data: number[], span: number) => {
    const k = 2 / (span + 1)
    return data.reduce((acc: number[], v, i) => {
      acc.push(i === 0 ? v : v * k + acc[i - 1] * (1 - k))
      return acc
    }, [])
  }
  if (closes.length < 26) return { macd: 0, signal: 0, hist: 0 }
  const ema12 = ema(closes, 12)
  const ema26 = ema(closes, 26)
  const macdLine = ema12.map((v, i) => v - ema26[i])
  const signalLine = ema(macdLine.slice(-9), 9)
  const macd = macdLine[macdLine.length - 1]
  const signal = signalLine[signalLine.length - 1]
  return { macd, signal, hist: macd - signal }
}

export default function StockDetail() {
  const { symbol } = useParams<{ symbol: string }>()
  const navigate = useNavigate()
  const [chart, setChart] = useState<ChartResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    setError('')
    getChart(decodeURIComponent(symbol))
      .then(setChart)
      .catch(() => setError('無法載入資料，請稍後再試'))
      .finally(() => setLoading(false))
  }, [symbol])

  if (loading) return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center text-slate-400">
        <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        載入中...
      </div>
    </div>
  )

  if (error || !chart) return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center text-slate-400">
        <div className="text-4xl mb-4">❌</div>
        <p>{error || '找不到股票資料'}</p>
        <button onClick={() => navigate('/')} className="mt-4 text-blue-400 hover:text-blue-300">
          返回首頁
        </button>
      </div>
    </div>
  )

  const closes = chart.data.map(d => d.close)
  const latest = chart.data[chart.data.length - 1]
  const prev = chart.data[chart.data.length - 2]
  const change = prev ? ((latest.close - prev.close) / prev.close) * 100 : 0
  const rsi = calcRSI(closes)
  const { macd, signal, hist } = calcMACD(closes)
  const isUp = change >= 0

  const rsiColor = rsi > 70 ? 'text-red-400' : rsi < 40 ? 'text-blue-400' : 'text-green-400'
  const rsiLabel = rsi > 70 ? '超買' : rsi < 40 ? '超賣' : '正常'

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="max-w-5xl mx-auto px-4 py-8">

        {/* Back */}
        <button
          onClick={() => navigate('/')}
          className="text-slate-400 hover:text-white text-sm mb-6 flex items-center gap-1 transition-colors"
        >
          ← 返回推薦清單
        </button>

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold text-white font-mono">
                {chart.symbol.replace('.TW', '')}
              </h1>
              <span className={`text-xs px-2 py-1 rounded ${chart.market === 'TW' ? 'bg-green-900/50 text-green-300' : 'bg-blue-900/50 text-blue-300'}`}>
                {chart.market}
              </span>
            </div>
            <p className="text-slate-400 mt-1">{chart.name}</p>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold text-white">{latest.close.toLocaleString()}</div>
            <div className={`text-lg font-medium ${isUp ? 'text-green-400' : 'text-red-400'}`}>
              {isUp ? '▲' : '▼'} {Math.abs(change).toFixed(2)}%
            </div>
          </div>
        </div>

        {/* Chart */}
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-6">
          <h2 className="text-slate-300 text-sm font-medium mb-3">K 線圖（近 180 日）</h2>
          <StockChart data={chart.data} />
        </div>

        {/* Indicators */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {[
            { label: 'RSI (14)', value: rsi.toFixed(2), sub: rsiLabel, color: rsiColor },
            { label: 'MACD', value: macd.toFixed(4), sub: hist >= 0 ? '多頭' : '空頭', color: hist >= 0 ? 'text-green-400' : 'text-red-400' },
            { label: 'MACD Signal', value: signal.toFixed(4), sub: '', color: 'text-slate-300' },
            { label: '成交量', value: (latest.volume / 1000).toFixed(0) + 'K', sub: '今日', color: 'text-slate-300' },
          ].map(({ label, value, sub, color }) => (
            <div key={label} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
              <div className="text-slate-500 text-xs mb-1">{label}</div>
              <div className={`text-xl font-bold ${color}`}>{value}</div>
              {sub && <div className="text-slate-500 text-xs mt-1">{sub}</div>}
            </div>
          ))}
        </div>

        {/* OHLC */}
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4">
          <h2 className="text-slate-300 text-sm font-medium mb-3">今日 OHLC</h2>
          <div className="grid grid-cols-4 gap-4">
            {[
              { label: '開盤', value: latest.open },
              { label: '最高', value: latest.high },
              { label: '最低', value: latest.low },
              { label: '收盤', value: latest.close },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="text-slate-500 text-xs">{label}</div>
                <div className="text-white font-semibold mt-0.5">{value.toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
