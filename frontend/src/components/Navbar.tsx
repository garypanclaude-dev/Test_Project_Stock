import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchStocks } from '../api/client'
import type { StockSearchItem } from '../api/client'

export default function Navbar() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<StockSearchItem[]>([])
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (query.length < 1) { setResults([]); setOpen(false); return }
    const id = setTimeout(async () => {
      try {
        const data = await searchStocks(query)
        setResults(data)
        setOpen(data.length > 0)
      } catch { setResults([]) }
    }, 300)
    return () => clearTimeout(id)
  }, [query])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const pick = (item: StockSearchItem) => {
    setQuery('')
    setOpen(false)
    navigate(`/stock/${encodeURIComponent(item.symbol)}`)
  }

  return (
    <nav className="bg-slate-900 border-b border-slate-700 px-6 py-4 flex items-center justify-between sticky top-0 z-50">
      <button
        onClick={() => navigate('/')}
        className="text-xl font-bold text-blue-400 hover:text-blue-300 transition-colors"
      >
        📈 股票分析平台
      </button>

      <div ref={ref} className="relative w-72">
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="搜尋股票代號或名稱..."
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
        />
        {open && (
          <div className="absolute top-full mt-1 w-full bg-slate-800 border border-slate-600 rounded-lg shadow-xl z-50 max-h-60 overflow-y-auto">
            {results.map(item => (
              <button
                key={item.symbol}
                onClick={() => pick(item)}
                className="w-full text-left px-4 py-2 hover:bg-slate-700 flex justify-between items-center text-sm"
              >
                <span className="font-mono text-blue-300">{item.symbol}</span>
                <span className="text-slate-300 truncate ml-2">{item.name}</span>
                <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${item.market === 'TW' ? 'bg-green-900 text-green-300' : 'bg-blue-900 text-blue-300'}`}>
                  {item.market}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </nav>
  )
}
