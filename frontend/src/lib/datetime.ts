// 统一时间展示工具（审查 D1，红线 #10：入库 UTC，按本地时区展示）。
// 后端时间字段为带 +00:00 的 ISO 串（DateTime UTC 序列化）或 Unix 秒（EMS 状态）。
// 直接渲染 ISO 串或对其 slice 会显示 UTC，与本地时钟并排出现时差。

/** 把 ISO 串或 Unix 秒格式化为本地时区的 "YYYY/MM/DD HH:mm:ss"；空值返回占位符。 */
export function formatLocal(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  // number 视为 Unix 秒；string 视为可被 Date 解析的 ISO 串
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

/** 仅取本地时区的时分秒 "HH:mm:ss"（用于大屏等空间有限处）；空值返回占位符。 */
export function formatLocalTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

/** 把日期选择器产出的本地无时区串（"YYYY-MM-DDTHH:mm:ss"）转为带时区的 UTC ISO 串。
 * 审查 C2：后端按 UTC 入库（红线 #10），直接提交无时区串会被当成 UTC 造成 8 小时偏移。
 * `new Date(local)` 按本地时区解析，`toISOString()` 输出带 Z 的 UTC，消除偏移。空值返回 null。 */
export function toIsoUtc(local: string | null | undefined): string | null {
  if (!local) return null
  const date = new Date(local)
  if (Number.isNaN(date.getTime())) return null
  return date.toISOString()
}
