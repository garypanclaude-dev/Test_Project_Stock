import { useNavigate } from 'react-router-dom'
import type { RecommendationItem } from '../api/client'

interface Props {
  item: RecommendationItem
}

export default function RecommendationCard({ item }: Props) {
  const navigate = useNavigate()
  const pct = Math.round(item.probability * 100)
  const change = item.price_change_1d * 100
  const isUp = change >= 0

  const probColor =
    pct >= 80 ? 'text-green-400 bg-green-900/40' :
    pct >= 70 ? 'text-yellow-400 bg-yellow-900/40' :
    'text-orange-400 bg-orange-900/40'

  const rsiColor =
    item.rsi > 70 ? 'text-red-400' :
    item.rsi < 40 ? 'text-blue-400' :
    'text-slate-300'

  return (
    <div
      onClick={() => navigate(`/stock/${encodeURIComponent(item.symbol)}`)}
      className="bg-slate-800 border border-slate-700 rounded-xl p-4 cursor-pointer hover:border-blue-500 hover:bg-slate-750 transition-all duration-200 group"
    >
      {/* Header */}
      <div className="flex justify-between items-start mb-3">
        <div>
          <div className="font-mono font-bold text-white group-hover:text-blue-300 transition-colors">
            {item.symbol.replace('.TW', '')}
          </div>
          <div className="text-slate-400 text-xs mt-0.5 truncate max-w-[120px]">{item.name}</div>
        </div>
        <span className={`text-sm font-bold px-2.5 py-1 rounded-full ${probColor}`}>
          {pct}%
        </span>
      </div>

      {/* Price */}
      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-lg font-semibold text-white">
          {item.current_price.toLocaleString()}
        </span>
        <span className={`text-sm font-medium ${isUp ? 'text-green-400' : 'text-red-400'}`}>
          {isUp ? '▲' : '▼'} {Math.abs(change).toFixed(2)}%
        </span>
      </div>

      {/* Indicators */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-slate-900 rounded-lg p-2">
          <div className="text-slate-500 mb-0.5">RSI</div>
          <div className={`font-semibold ${rsiColor}`}>{item.rsi.toFixed(1)}</div>
        </div>
        <div className="bg-slate-900 rounded-lg p-2">
          <div className="text-slate-500 mb-0.5">量比</div>
          <div className={`font-semibold ${item.volume_ratio >= 1.5 ? 'text-yellow-400' : 'text-slate-300'}`}>
            {item.volume_ratio.toFixed(2)}x
          </div>
        </div>
      </div>

      {/* Probability bar */}
      <div className="mt-3">
        <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-400 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="text-slate-500 text-xs mt-1">5日上漲機率</div>
      </div>

      {/* Trading suggestions */}
      {item.buy_low != null && (
        <div className="mt-3 border-t border-slate-700 pt-3" onClick={e => e.stopPropagation()}>
          <div className="text-slate-400 text-xs font-semibold mb-2">明日操作建議</div>
          <div className="grid grid-cols-2 gap-1.5 text-xs">
            <div className="bg-blue-950/50 border border-blue-800/40 rounded-lg p-2">
              <div className="text-blue-400 mb-0.5">買入區間</div>
              <div className="text-white font-mono font-semibold">
                {item.buy_low!.toLocaleString()} – {item.buy_high!.toLocaleString()}
              </div>
            </div>
            <div className="bg-green-950/50 border border-green-800/40 rounded-lg p-2">
              {(() => {
                const tpPct = (((item.take_profit! - item.buy_high!) / item.buy_high!) * 100).toFixed(1)
                return <>
                  <div className="text-green-400 mb-0.5">停利目標 +{tpPct}%</div>
                  <div className="text-green-300 font-mono font-semibold">
                    {item.take_profit!.toLocaleString()}
                  </div>
                </>
              })()}
            </div>
            <div className="col-span-2 bg-red-950/50 border border-red-800/40 rounded-lg p-2">
              {(() => {
                const slPct = (((item.stop_loss! - item.buy_low!) / item.buy_low!) * 100).toFixed(1)
                return <>
                  <div className="text-red-400 mb-0.5">停損點 {slPct}%</div>
                  <div className="text-red-300 font-mono font-semibold">
                    {item.stop_loss!.toLocaleString()}
                  </div>
                </>
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
