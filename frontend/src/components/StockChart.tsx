import { useEffect, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, ColorType } from 'lightweight-charts'
import type { ChartPoint } from '../api/client'

interface Props {
  data: ChartPoint[]
}

function calcMA(data: ChartPoint[], period: number) {
  return data.map((_, i) => {
    if (i < period - 1) return null
    const avg = data.slice(i - period + 1, i + 1).reduce((s, d) => s + d.close, 0) / period
    return { time: data[i].date as any, value: avg }
  }).filter(Boolean) as { time: any; value: number }[]
}

export default function StockChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return

    const chart = createChart(containerRef.current, {
      width: containerRef.current.offsetWidth,
      height: 380,
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    candleSeries.setData(
      data.map(d => ({
        time: d.date as any,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }))
    )

    const colors = ['#3b82f6', '#f59e0b', '#a855f7']
    const periods = [5, 20, 60]
    periods.forEach((p, i) => {
      const ma = calcMA(data, p)
      if (ma.length === 0) return
      const line = chart.addSeries(LineSeries, {
        color: colors[i],
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      })
      line.setData(ma)
    })

    chart.timeScale().fitContent()

    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current!.offsetWidth })
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [data])

  return (
    <div>
      <div ref={containerRef} className="w-full" />
      <div className="flex gap-4 mt-2 text-xs text-slate-400">
        <span><span className="text-blue-400">—</span> MA5</span>
        <span><span className="text-yellow-400">—</span> MA20</span>
        <span><span className="text-purple-400">—</span> MA60</span>
      </div>
    </div>
  )
}
