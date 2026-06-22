import { ElMessage } from 'element-plus'

// 统一把后端结构化错误（{code,msg} 或旧 {detail}）友好呈现给用户（审查 I7）。
// ElMessageBox 取消会 reject 字符串 'cancel'，调用方需先排除再传入。
export function handleErr(e: unknown): void {
  const data = (e as { response?: { data?: { msg?: string; detail?: string } } })?.response?.data
  const msg = data?.msg || data?.detail
  if (msg) ElMessage.error(msg)
  else ElMessage.error('操作失败，请稍后重试')
}
