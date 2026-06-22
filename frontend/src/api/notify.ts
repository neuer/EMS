import { deleteJson, getJson, postJson, putJson } from '@/api/http'
import type { NotifyChannel, NotifyLog, NotifyRoute, Recipient, RecipientGroup } from '@/api/types'

// ---- 渠道 ----
export function listChannels(): Promise<NotifyChannel[]> {
  return getJson('/notify/channels')
}
export function createChannel(body: {
  type: string
  name: string
  config: Record<string, unknown>
  enabled: boolean
}): Promise<NotifyChannel> {
  return postJson('/notify/channels', body)
}
export function updateChannel(
  id: number,
  body: { name?: string; config?: Record<string, unknown>; enabled?: boolean },
): Promise<NotifyChannel> {
  return putJson(`/notify/channels/${id}`, body)
}
export function deleteChannel(id: number): Promise<{ deleted: number }> {
  return deleteJson(`/notify/channels/${id}`)
}
export function testChannel(id: number): Promise<{ ok: boolean; detail: string }> {
  return postJson(`/notify/channels/${id}/test`)
}

// ---- 接收人 ----
export function listRecipients(): Promise<Recipient[]> {
  return getJson('/notify/recipients')
}
export function createRecipient(body: Omit<Recipient, 'id'>): Promise<Recipient> {
  return postJson('/notify/recipients', body)
}
export function updateRecipient(
  id: number,
  body: Partial<Omit<Recipient, 'id'>>,
): Promise<Recipient> {
  return putJson(`/notify/recipients/${id}`, body)
}
export function deleteRecipient(id: number): Promise<{ deleted: number }> {
  return deleteJson(`/notify/recipients/${id}`)
}

// ---- 接收组 ----
export function listGroups(): Promise<RecipientGroup[]> {
  return getJson('/notify/groups')
}
export function createGroup(body: { name: string; member_ids: number[] }): Promise<RecipientGroup> {
  return postJson('/notify/groups', body)
}
export function updateGroup(
  id: number,
  body: { name: string; member_ids: number[] },
): Promise<RecipientGroup> {
  return putJson(`/notify/groups/${id}`, body)
}
export function deleteGroup(id: number): Promise<{ deleted: number }> {
  return deleteJson(`/notify/groups/${id}`)
}

// ---- 级别路由 ----
export function listRoutes(): Promise<NotifyRoute[]> {
  return getJson('/notify/routes')
}
export function createRoute(body: Omit<NotifyRoute, 'id'>): Promise<NotifyRoute> {
  return postJson('/notify/routes', body)
}
export function updateRoute(
  id: number,
  body: Partial<Omit<NotifyRoute, 'id'>>,
): Promise<NotifyRoute> {
  return putJson(`/notify/routes/${id}`, body)
}
export function deleteRoute(id: number): Promise<{ deleted: number }> {
  return deleteJson(`/notify/routes/${id}`)
}

// ---- 发送记录 ----
export function listNotifyLogs(limit = 50): Promise<NotifyLog[]> {
  return getJson('/notify/logs', { limit })
}
