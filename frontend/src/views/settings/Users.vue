<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { createUser, deleteUser, listUsers, resetPassword, updateUser } from '@/api/users'
import { ROLE_LABEL, type UserAdmin } from '@/api/types'
import { useAuthStore } from '@/store/auth'
import { formatLocal } from '@/lib/datetime'

const auth = useAuthStore()
const rows = ref<UserAdmin[]>([])

const dialog = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  username: '',
  password: '',
  role: 'readonly',
  display_name: '',
  enabled: true,
})

const pwdDialog = ref(false)
const pwdTarget = ref<UserAdmin | null>(null)
const newPwd = ref('')

const ROLES = ['admin', 'operator', 'readonly']

async function load(): Promise<void> {
  rows.value = await listUsers()
}

function openCreate(): void {
  editingId.value = null
  Object.assign(form, {
    username: '',
    password: '',
    role: 'readonly',
    display_name: '',
    enabled: true,
  })
  dialog.value = true
}

function openEdit(u: UserAdmin): void {
  editingId.value = u.id
  Object.assign(form, {
    username: u.username,
    password: '',
    role: u.role,
    display_name: u.display_name || '',
    enabled: u.enabled,
  })
  dialog.value = true
}

async function save(): Promise<void> {
  try {
    if (editingId.value === null) {
      if (!form.username || form.password.length < 6) {
        ElMessage.warning('用户名必填，密码至少 6 位')
        return
      }
      await createUser({
        username: form.username,
        password: form.password,
        role: form.role,
        display_name: form.display_name || null,
        enabled: form.enabled,
      })
      ElMessage.success('用户已创建')
    } else {
      await updateUser(editingId.value, {
        role: form.role,
        display_name: form.display_name || null,
        enabled: form.enabled,
      })
      ElMessage.success('用户已更新')
    }
    dialog.value = false
    load()
  } catch (e) {
    handleErr(e)
  }
}

function openReset(u: UserAdmin): void {
  pwdTarget.value = u
  newPwd.value = ''
  pwdDialog.value = true
}

async function doReset(): Promise<void> {
  if (!pwdTarget.value || newPwd.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  await resetPassword(pwdTarget.value.id, newPwd.value)
  ElMessage.success('密码已重置')
  pwdDialog.value = false
}

async function remove(u: UserAdmin): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除用户 ${u.username}？`, '提示', { type: 'warning' })
    await deleteUser(u.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    if (e !== 'cancel') handleErr(e)
  }
}

// 将后端结构化错误（如「必须至少保留一个启用的管理员」）友好呈现
function handleErr(e: unknown): void {
  const msg =
    (e as { response?: { data?: { msg?: string; detail?: string } } })?.response?.data?.msg ||
    (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (msg) ElMessage.error(msg)
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="hd">
        <span>用户与角色管理</span>
        <el-button v-if="auth.isAdmin" type="primary" size="small" @click="openCreate">
          新建用户
        </el-button>
      </div>
    </template>

    <el-table :data="rows" size="small" border>
      <el-table-column prop="username" label="用户名" width="160" />
      <el-table-column label="角色" width="110">
        <template #default="{ row }">
          <el-tag size="small">{{ ROLE_LABEL[row.role] || row.role }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="display_name" label="显示名" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">{{ formatLocal(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <template v-if="auth.isAdmin">
            <el-button text size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text size="small" @click="openReset(row)">重置密码</el-button>
            <el-button text size="small" type="danger" @click="remove(row)">删除</el-button>
          </template>
          <span v-else class="ro">只读</span>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialog"
      :title="editingId === null ? '新建用户' : '编辑用户'"
      width="460px"
    >
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="editingId !== null" />
        </el-form-item>
        <el-form-item v-if="editingId === null" label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 200px">
            <el-option v-for="r in ROLES" :key="r" :label="ROLE_LABEL[r]" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdDialog" title="重置密码" width="400px">
      <p class="muted">用户：{{ pwdTarget?.username }}</p>
      <el-input v-model="newPwd" type="password" show-password placeholder="新密码（至少 6 位）" />
      <template #footer>
        <el-button @click="pwdDialog = false">取消</el-button>
        <el-button type="primary" @click="doReset">确定</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ro {
  color: #9ca3af;
}
.muted {
  color: #6b7280;
  margin: 0 0 10px;
}
</style>
