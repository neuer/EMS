import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

// 认证会话状态。仅持久化登录令牌/角色（会话凭据，非业务数据），
// 业务数据一律实时拉取，不落 localStorage（遵守红线）。
const LS_KEY = 'dcim_auth'

interface Persisted {
  token: string
  username: string
  role: string
}

function load(): Persisted {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return JSON.parse(raw) as Persisted
  } catch {
    /* ignore */
  }
  return { token: '', username: '', role: '' }
}

export const useAuthStore = defineStore('auth', () => {
  const init = load()
  const token = ref<string>(init.token)
  const username = ref<string>(init.username)
  const role = ref<string>(init.role)

  // RBAC：readonly 只读，隐藏所有写操作（后端仍强制校验）
  const canWrite = computed(() => role.value === 'operator' || role.value === 'admin')
  const isAdmin = computed(() => role.value === 'admin')

  // 角色等级：与后端 app/core/security.py 的 ROLE_LEVEL 对齐
  const ROLE_LEVEL: Record<string, number> = { readonly: 1, operator: 2, admin: 3 }
  function roleSatisfies(min: string): boolean {
    return (ROLE_LEVEL[role.value] ?? 0) >= (ROLE_LEVEL[min] ?? 99)
  }

  function persist(): void {
    localStorage.setItem(
      LS_KEY,
      JSON.stringify({ token: token.value, username: username.value, role: role.value }),
    )
  }

  function setAuth(payload: { token: string; username: string; role: string }): void {
    token.value = payload.token
    username.value = payload.username
    role.value = payload.role
    persist()
  }

  function clear(): void {
    token.value = ''
    username.value = ''
    role.value = ''
    localStorage.removeItem(LS_KEY)
  }

  return { token, username, role, canWrite, isAdmin, roleSatisfies, setAuth, clear }
})
