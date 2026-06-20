import { getJson, putJson } from '@/api/http'
import type {
  AssetMeta,
  DeviceDetail,
  DeviceItem,
  PointDetail,
  PointItem,
  SpaceNode,
} from '@/api/types'

export function fetchSpaceTree(): Promise<SpaceNode[]> {
  return getJson('/tree/spaces')
}

export function fetchSpaceChildren(
  spaceId: string,
): Promise<{ spaces: { resource_id: string; name: string; space_type: number | null; alias: string | null }[]; devices: DeviceItem[] }> {
  return getJson(`/spaces/${spaceId}/children`)
}

export function fetchDevices(params: {
  space?: string
  group?: string
  tag?: string
  keyword?: string
}): Promise<DeviceItem[]> {
  return getJson('/devices', params)
}

export function fetchDeviceDetail(id: string): Promise<DeviceDetail> {
  return getJson(`/devices/${id}`)
}

export function fetchPoints(params: {
  device?: string
  space?: string
  group?: string
  tag?: string
  keyword?: string
  importance?: number
}): Promise<PointItem[]> {
  return getJson('/points', params)
}

export function fetchPointDetail(id: string): Promise<PointDetail> {
  return getJson(`/points/${id}`)
}

export function fetchMeta(id: string): Promise<AssetMeta | null> {
  return getJson(`/assets/${id}/meta`)
}

export function saveMeta(id: string, body: Partial<AssetMeta>): Promise<AssetMeta> {
  return putJson(`/assets/${id}/meta`, body)
}
