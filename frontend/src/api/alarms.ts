import { getJson, postJson } from '@/api/http'
import type { Alarm, AlarmDetail, AlarmStats } from '@/api/types'

export function fetchActiveAlarms(params: {
  level?: number
  event_type?: number
  source?: string
  resource_id?: string
  masked?: boolean
}): Promise<Alarm[]> {
  return getJson('/alarms/active', params)
}

export function queryAlarmHistory(body: {
  start: number
  end: number
  level?: number
  status?: string
  source?: string
  resource_id?: string
  event_type?: number
  masked?: boolean
  limit?: number
  offset?: number
}): Promise<{ total: number; items: Alarm[] }> {
  return postJson('/alarms/history', body)
}

export function fetchAlarmDetail(id: number): Promise<AlarmDetail> {
  return getJson(`/alarms/${id}`)
}

export function fetchAlarmStats(): Promise<AlarmStats> {
  return getJson('/alarms/stats')
}

export function acceptAlarm(id: number, note: string): Promise<Alarm> {
  return postJson(`/alarms/${id}/accept`, { note })
}

export function confirmAlarm(id: number, note: string): Promise<Alarm> {
  return postJson(`/alarms/${id}/confirm`, { note })
}

export function noteAlarm(id: number, note: string): Promise<unknown> {
  return postJson(`/alarms/${id}/note`, { note })
}
