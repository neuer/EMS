import { deleteJson, getJson, postJson, putJson } from '@/api/http'
import type { MaintenanceWindow, PointMute } from '@/api/types'

// ---- 维护窗口 ----
export function listWindows(): Promise<MaintenanceWindow[]> {
  return getJson('/maintenance')
}
export function createWindow(body: {
  name?: string | null
  scope_kind: number
  scope_ids: string[]
  start_at: string
  end_at: string
  record_silenced: boolean
}): Promise<MaintenanceWindow> {
  return postJson('/maintenance', body)
}
export function updateWindow(
  id: number,
  body: Partial<Omit<MaintenanceWindow, 'id'>>,
): Promise<MaintenanceWindow> {
  return putJson(`/maintenance/${id}`, body)
}
export function deleteWindow(id: number): Promise<{ deleted: number }> {
  return deleteJson(`/maintenance/${id}`)
}

// ---- 测点屏蔽 ----
export function listMutes(point_id?: string): Promise<PointMute[]> {
  return getJson('/mute', point_id ? { point_id } : undefined)
}
export function createMute(body: {
  point_id: string
  reason?: string | null
  start_at?: string | null
  end_at?: string | null
}): Promise<PointMute> {
  return postJson('/mute', body)
}
export function disableMute(id: number): Promise<{ disabled: number }> {
  return deleteJson(`/mute/${id}`)
}
