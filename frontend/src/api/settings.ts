import { getJson, putJson } from '@/api/http'
import type { EmsConfig, EmsStatus } from '@/api/types'

export function fetchEmsConfig(): Promise<EmsConfig> {
  return getJson('/settings/ems')
}

export interface EmsConfigUpdate {
  base_url?: string
  username?: string
  password?: string // 留空表示不修改；提供则后端加密更新
  recv_ip?: string
  recv_port?: string
  version_str?: string
  sync_interval_s?: number
  subscribe_data?: boolean
  subscribe_alarm?: boolean
  deadband_enabled?: boolean
}

export function updateEmsConfig(body: EmsConfigUpdate): Promise<{ restarted: boolean }> {
  return putJson('/settings/ems', body)
}

export function fetchEmsStatus(): Promise<EmsStatus> {
  return getJson('/settings/ems/status')
}
