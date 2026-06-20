import { deleteJson, getJson, http, postJson, putJson } from '@/api/http'
import type { AlarmReportStats, RecipientGroup, ReportSchedule } from '@/api/types'

export function fetchAlarmReportStats(params: {
  start: number
  end: number
  granularity: 'day' | 'week' | 'month'
}): Promise<AlarmReportStats> {
  return getJson('/reports/alarm-stats', params)
}

// 文件下载（导出端点不走响应包络，直接返回二进制）
async function downloadBlob(
  url: string,
  opts: { method?: 'get' | 'post'; params?: Record<string, unknown>; body?: unknown },
  fallbackName: string,
): Promise<void> {
  const resp = await http.request({
    url,
    method: opts.method ?? 'get',
    params: opts.params,
    data: opts.body,
    responseType: 'blob',
  })
  const disposition = String(resp.headers['content-disposition'] || '')
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? decodeURIComponent(match[1]) : fallbackName
  const blobUrl = URL.createObjectURL(resp.data as Blob)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  a.click()
  URL.revokeObjectURL(blobUrl)
}

export function exportAlarms(params: {
  start: number
  end: number
  fmt: 'csv' | 'xlsx'
  level?: number
  source?: string
}): Promise<void> {
  return downloadBlob('/reports/export/alarms', { params }, `alarms.${params.fmt}`)
}

export function exportHistory(
  body: { point_ids: string[]; start: number; end: number; agg: 'raw' | '5min' | 'auto' },
  fmt: 'csv' | 'xlsx',
): Promise<void> {
  return downloadBlob(
    '/reports/export/history',
    { method: 'post', params: { fmt }, body },
    `history.${fmt}`,
  )
}

// ---- 报表计划 ----
export function fetchSchedules(): Promise<ReportSchedule[]> {
  return getJson('/reports/schedules')
}

export function createSchedule(body: {
  name?: string | null
  report_type: 'daily' | 'weekly' | 'monthly'
  cron: string
  group_ids: number[]
  enabled: boolean
}): Promise<ReportSchedule> {
  return postJson('/reports/schedules', body)
}

export function updateSchedule(
  id: number,
  body: Partial<{
    name: string | null
    report_type: 'daily' | 'weekly' | 'monthly'
    cron: string
    group_ids: number[]
    enabled: boolean
  }>,
): Promise<ReportSchedule> {
  return putJson(`/reports/schedules/${id}`, body)
}

export function deleteSchedule(id: number): Promise<unknown> {
  return deleteJson(`/reports/schedules/${id}`)
}

export function runScheduleNow(id: number): Promise<{
  sent: boolean
  reason?: string
  recipients?: number
  total: number
  subject?: string
}> {
  return postJson(`/reports/schedules/${id}/run-now`, {})
}

// 报表计划接收组选择（复用通知接收组）
export function fetchRecipientGroups(): Promise<RecipientGroup[]> {
  return getJson('/notify/groups')
}
