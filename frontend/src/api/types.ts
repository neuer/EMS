// 与后端输出模型对应的前端类型（手写，因本项目未启用 openapi 生成链路）

export interface SpaceNode {
  resource_id: string
  name: string
  parent_id: string | null
  space_type: number | null
  alias: string | null
  active_alarms: number
  max_level: number | null
  children: SpaceNode[]
}

export interface DeviceItem {
  resource_id: string
  name: string
  device_type: string | null
  parent_id: string | null
  location: string | null
  is_active: boolean
  alias: string | null
  group_name: string | null
  status: number | null
  active_alarms: number
}

export interface PointItem {
  resource_id: string
  name: string
  device_id: string
  spot_type: number | null
  unit: string | null
  is_active: boolean
  alias: string | null
  group_name: string | null
  importance: number | null
  value: string | null
  save_time: number | null
  active_alarms: number
}

export interface RuleBrief {
  id: number
  name: string | null
  operator: string
  operand: number | null
  operand_min: number | null
  operand_max: number | null
  cond_type: string
  level: number
  enabled: boolean
}

export interface AssetMeta {
  resource_id: string
  asset_kind: number
  alias: string | null
  group_name: string | null
  tags: string[] | null
  importance: number | null
  custom_unit: string | null
  remark: string | null
}

export interface DeviceDetail extends DeviceItem {
  points: PointItem[]
}

export interface PointDetail extends PointItem {
  mapper: string | null
  access: string | null
  meta: AssetMeta | null
  rules: RuleBrief[]
}

export interface Alarm {
  id: number
  source: string
  guid: string | null
  rule_id: number | null
  resource_id: string
  resource_kind: number
  event_type: number | null
  level: number
  status: string
  trigger_value: number | null
  content: string | null
  suggest: string | null
  masked: boolean
  silenced_reason: string | null
  merge_count: number
  triggered_at: string
  accepted_at: string | null
  confirmed_at: string | null
  recovered_at: string | null
}

export interface AlarmEvent {
  id: number
  event: string
  operator_id: number | null
  note: string | null
  snapshot: number | null
  occurred_at: string
}

export interface AlarmDetail extends Alarm {
  events: AlarmEvent[]
}

export interface AlarmStats {
  active_total: number
  by_level: Record<string, number>
  by_status: Record<string, number>
  by_source: Record<string, number>
}

export interface HistorySeries {
  point_id: string
  layer: 'raw' | '5min'
  raw?: { ts: number; value: number | null }[]
  agg?: { ts: number; avg: number | null; min: number | null; max: number | null; count: number }[]
}

export interface HistoryResult {
  layer: 'raw' | '5min'
  start: number
  end: number
  series: HistorySeries[]
}

// ---- 报表（Sprint 6）----
export interface ReportStatBucket {
  bucket: string
  total: number
  by_level: Record<string, number>
  by_source: Record<string, number>
}

export interface ReportTopResource {
  resource_id: string
  name: string | null
  count: number
}

export interface AlarmReportStats {
  granularity: 'day' | 'week' | 'month'
  start: number
  end: number
  total: number
  by_level: Record<string, number>
  by_source: Record<string, number>
  by_event_type: Record<string, number>
  buckets: ReportStatBucket[]
  top_resources: ReportTopResource[]
  mtta_seconds: number | null
  mttr_seconds: number | null
}

export interface ReportSchedule {
  id: number
  name: string | null
  report_type: 'daily' | 'weekly' | 'monthly'
  cron: string
  group_ids: number[]
  enabled: boolean
  next_run: string | null
}

export interface RecipientGroup {
  id: number
  name: string
  member_ids: number[]
}

// ---- 系统设置（Sprint 7）----
export interface EmsConfig {
  base_url: string
  username: string
  password_masked: string
  recv_ip: string
  recv_port: string
  version_str: string
  sync_interval_s: number
  subscribe_data: boolean
  subscribe_alarm: boolean
  deadband_enabled: boolean
}

export interface EmsStatus {
  state: string
  last_heart: number | null
  last_push: number | null
  token_ok: boolean
  reconnects: number
}

export interface Rule {
  id: number
  point_id: string
  name: string | null
  enabled: boolean
  operator: string
  operand: number | null
  operand_min: number | null
  operand_max: number | null
  cond_type: string
  restore_operator: string | null
  restore_operand: number | null
  continuous_time: number
  recover_hold_time: number
  level: number
  priority: number
  content_tpl: string | null
  suggest: string | null
}

export interface NotifyChannel {
  id: number
  type: string
  name: string
  config: Record<string, unknown>
  enabled: boolean
}

export interface Recipient {
  id: number
  name: string
  phone: string | null
  email: string | null
  dingtalk_id: string | null
  wecom_id: string | null
  enabled: boolean
}

export interface NotifyRoute {
  id: number
  level: number
  channel_ids: number[]
  group_ids: number[]
  notify_on_recover: boolean
  enabled: boolean
}

export interface NotifyLog {
  id: number
  alarm_id: number | null
  channel_id: number | null
  recipient: string | null
  trigger: string | null
  status: string
  error: string | null
  retry_count: number
  sent_at: string
}

export interface MaintenanceWindow {
  id: number
  name: string | null
  scope_kind: number
  scope_ids: string[]
  start_at: string
  end_at: string
  record_silenced: boolean
}

export interface PointMute {
  id: number
  point_id: string
  reason: string | null
  start_at: string
  end_at: string | null
  enabled: boolean
}

export interface UserAdmin {
  id: number
  username: string
  role: string
  display_name: string | null
  enabled: boolean
  created_at: string
}

export const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  operator: '操作员',
  readonly: '只读',
}

export const CHANNEL_LABEL: Record<string, string> = {
  sms: '短信',
  email: '邮件',
  dingtalk: '钉钉',
  wecom: '企业微信',
  voice: '电话语音',
  webhook: '通用 Webhook',
}

export const LEVEL_LABEL: Record<number, string> = {
  1: '紧急',
  2: '严重',
  3: '重要',
  4: '次要',
  5: '提示',
}

export const LEVEL_TAG: Record<number, string> = {
  1: 'danger',
  2: 'danger',
  3: 'warning',
  4: 'warning',
  5: 'info',
}
