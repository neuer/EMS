import { deleteJson, getJson, postJson, putJson } from '@/api/http'
import type { UserAdmin } from '@/api/types'

export function listUsers(): Promise<UserAdmin[]> {
  return getJson('/users')
}

export function createUser(body: {
  username: string
  password: string
  role: string
  display_name?: string | null
  enabled: boolean
}): Promise<UserAdmin> {
  return postJson('/users', body)
}

export function updateUser(
  id: number,
  body: { role?: string; display_name?: string | null; enabled?: boolean },
): Promise<UserAdmin> {
  return putJson(`/users/${id}`, body)
}

export function resetPassword(id: number, password: string): Promise<{ reset: number }> {
  return postJson(`/users/${id}/reset-password`, { password })
}

export function deleteUser(id: number): Promise<{ deleted: number }> {
  return deleteJson(`/users/${id}`)
}
