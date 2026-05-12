import { useEffect, useState } from 'react'
import { getRecommendations, getStatus, triggerCollection } from '../api/client'
import type { RecommendationsResponse, StatusResponse } from '../api/client'
import RecommendationCard from '../components/RecommendationCard'

export default function Dashboard() {
  const [data, setData] = useState<RecommendationsResponse | null>(null)
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [tab, setTab] = useState<'TW' | 'US'>('TW')
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)

  const load = async () => {
    try {
      const [rec, st] = await Promise.all([getRecommendations(), getStatus()])
      setData(rec)
      setStatus(st)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      await triggerCollection()
      setTimeout(load, 2000)
    } finally {
      setTriggering(false)
    }
  }

  // Treat "running" as stale if updated_at hasn't changed in >5 minutes
  const isStaleRunning = status?.status === 'running' && !!status.updated_at &&
    (Date.now() - new Date(status.updated_at).getTime()) > 5 * 60 * 1000
  const isRunning = status?.status === 'running' && !isStaleRunning
  const hasData = (data?.tw?.length ?? 0) > 0 || (data?.us?.length ?? 0) > 0
  const isInitializing = isRunning && !hasData
  const items = tab === 'TW' ? data?.tw ?? [] : data?.us ?? []

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="max-w-7xl mx-auto px-4 py-8">

        {/* Title */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-white">今日推薦股票</h1>
            <p className="text-slate-400 mt-1 text-sm">
              基於技術指標與 AI 模型，篩選 5 日內有機會上漲的股票
            </p>
          </div>
          <button
            onClick={handleTrigger}
            disabled={triggering || isRunning}
            className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            {triggering ? '啟動中...' : isRunning ? '更新中...' : '手動更新資料'}
          </button>
        </div>

        {/* Status bar */}
        {status && (
          <div className={`mb-6 rounded-xl p-4 border ${
            isRunning
              ? 'bg-blue-950/40 border-blue-700'
              : status.status === 'completed'
              ? 'bg-green-950/40 border-green-800'
              : status.status === 'error'
              ? 'bg-red-950/40 border-red-800'
              : 'bg-slate-800/40 border-slate-700'
          }`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {isRunning && (
                  <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                )}
                <span className="text-sm text-slate-300">{status.message || '資料狀態未知'}</span>
              </div>
              {isRunning && status.total > 0 && (
                <span className="text-sm text-slate-400">
                  {status.progress} / {status.total}
                </span>
              )}
            </div>
            {isRunning && status.total > 0 && (
              <div className="mt-2 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all duration-500"
                  style={{ width: `${Math.round((status.progress / status.total) * 100)}%` }}
                />
              </div>
            )}
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          {(['TW', 'US'] as const).map(market => (
            <button
              key={market}
              onClick={() => setTab(market)}
              className={`px-5 py-2 rounded-lg font-medium text-sm transition-colors ${
                tab === market
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-white'
              }`}
            >
              {market === 'TW' ? '🇹🇼 台股' : '🇺🇸 美股'}
              <span className="ml-2 text-xs opacity-70">
                ({(market === 'TW' ? data?.tw : data?.us)?.length ?? 0})
              </span>
            </button>
          ))}
        </div>

        {/* Last update */}
        {data?.last_update && (
          <p className="text-slate-500 text-xs mb-4">
            最後更新：{new Date(data.last_update).toLocaleString('zh-TW')}
          </p>
        )}

        {/* Grid */}
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-slate-400 text-center">
              <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              <p>載入中...</p>
            </div>
          </div>
        ) : isInitializing ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-slate-400 text-center">
              <div className="text-4xl mb-4">⏳</div>
              <p className="text-lg font-medium text-white mb-2">正在初始化資料庫</p>
              <p className="text-sm">首次啟動需要下載台股與美股歷史資料，約需 15~30 分鐘</p>
              <p className="text-sm mt-1">完成後頁面會自動顯示推薦</p>
            </div>
          </div>
        ) : items.length === 0 ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-slate-400 text-center">
              <div className="text-4xl mb-4">📭</div>
              <p className="text-lg text-white mb-2">今日暫無推薦</p>
              <p className="text-sm">目前市場條件下無符合條件的股票，或資料尚未更新</p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {items.map(item => (
              <RecommendationCard key={item.symbol} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
