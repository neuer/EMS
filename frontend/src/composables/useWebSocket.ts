import { onUnmounted, ref } from 'vue'

import { router } from '@/router'
import { useAuthStore } from '@/store/auth'

// 服务端实时帧：{ type:'realtime', points:[{id,value,ts}] }
export interface RealtimePoint {
  id: string
  value: number | null
  ts: number
}

interface RealtimeFrame {
  type: string
  points?: RealtimePoint[]
}

/**
 * 实时 WebSocket 订阅（/ws/realtime）。
 * - 自动携带 JWT（query token）。
 * - 断线自动重连（指数退避，上限 30s）。
 * - latest：响应式最新值表，key 为测点 id。
 */
export function useRealtimeSocket() {
  const latest = ref<Record<string, RealtimePoint>>({})
  const connected = ref(false)

  let ws: WebSocket | null = null
  let pointIds: string[] = []
  let backoff = 1000
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let closedByUser = false
  // 监控场景：瞬时断线（后端重启/反代抖动）应持续重连（退避封顶 30s，不设永久上限），
  // 仅在鉴权失败（服务端 1008）时彻底停连并登出（审查 F + 复审 I1/I2）。

  function buildUrl(): string {
    const auth = useAuthStore()
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const token = encodeURIComponent(auth.token)
    return `${proto}://${window.location.host}/ws/realtime?token=${token}`
  }

  function sendSubscribe(): void {
    if (ws && ws.readyState === WebSocket.OPEN && pointIds.length > 0) {
      ws.send(JSON.stringify({ action: 'subscribe', point_ids: pointIds }))
    }
  }

  function connect(): void {
    // 审查 F：已有连接（连接中/已连）时不重复建立，避免误用造成双连接
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return
    }
    // 审查 I8：token 为空时不建连——空 token 必被后端以 1008 拒绝并触发登出，
    // 形成「刚进页面就被踢」。等鉴权就绪后由调用方再次 connect。
    if (!useAuthStore().token) {
      return
    }
    closedByUser = false
    ws = new WebSocket(buildUrl())

    ws.onopen = () => {
      connected.value = true
      backoff = 1000 // 连接成功重置退避
      sendSubscribe()
    }

    ws.onmessage = (ev: MessageEvent<string>) => {
      try {
        const frame = JSON.parse(ev.data) as RealtimeFrame
        if (frame.type === 'realtime' && frame.points) {
          const next = { ...latest.value }
          for (const p of frame.points) {
            next[p.id] = p
          }
          latest.value = next
        }
      } catch {
        // 忽略非法帧
      }
    }

    ws.onclose = (ev: CloseEvent) => {
      connected.value = false
      // 鉴权失败（服务端 WS_1008_POLICY_VIOLATION）→ 停止重连、登出并跳登录，避免「假在线」
      if (ev.code === 1008) {
        closedByUser = true
        useAuthStore().clear()
        void router.push('/login')
        return
      }
      // 其余断线（瞬时网络/后端重启）持续重连，由退避封顶控制频率
      if (!closedByUser) {
        scheduleReconnect()
      }
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function scheduleReconnect(): void {
    if (reconnectTimer) {
      return
    }
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, backoff)
    backoff = Math.min(backoff * 2, 30000)
  }

  function subscribe(ids: string[]): void {
    pointIds = ids
    sendSubscribe()
  }

  function close(): void {
    closedByUser = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws?.close()
    ws = null
  }

  onUnmounted(close)

  return { latest, connected, connect, subscribe, close }
}
