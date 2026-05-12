import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export interface RecommendationItem {
  symbol: string
  name: string
  market: string
  probability: number
  current_price: number
  price_change_1d: number
  rsi: number
  volume_ratio: number
  buy_low: number | null
  buy_high: number | null
  take_profit: number | null
  stop_loss: number | null
}

export interface RecommendationsResponse {
  tw: RecommendationItem[]
  us: RecommendationItem[]
  last_update: string | null
}

export interface ChartPoint {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface ChartResponse {
  symbol: string
  name: string
  market: string
  data: ChartPoint[]
}

export interface StockSearchItem {
  symbol: string
  name: string
  market: string
}

export interface StatusResponse {
  status: string
  progress: number
  total: number
  message: string
  updated_at: string | null
}

export const getRecommendations = () =>
  api.get<RecommendationsResponse>('/recommendations').then(r => r.data)

export const getChart = (symbol: string, days = 180) =>
  api.get<ChartResponse>(`/stocks/${encodeURIComponent(symbol)}/chart`, { params: { days } }).then(r => r.data)

export const searchStocks = (q: string) =>
  api.get<StockSearchItem[]>('/stocks/search', { params: { q } }).then(r => r.data)

export const getStatus = () =>
  api.get<StatusResponse>('/scheduler/status').then(r => r.data)

export const triggerCollection = () =>
  api.post('/scheduler/trigger').then(r => r.data)
