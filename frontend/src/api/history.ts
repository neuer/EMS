import { getJson, postJson } from '@/api/http'
import type { HistoryResult, PointItem } from '@/api/types'

export function queryHistory(body: {
  point_ids: string[]
  start: number
  end: number
  agg: 'raw' | '5min' | 'auto'
}): Promise<HistoryResult> {
  return postJson('/history/query', body)
}

export function fetchLatest(ids: string[]): Promise<{ id: string; value: string | null; save_time: number | null }[]> {
  return getJson('/realtime/points', { ids: ids.join(',') })
}

// 供趋势页选点
export function searchPoints(keyword: string): Promise<PointItem[]> {
  return getJson('/points', { keyword })
}
