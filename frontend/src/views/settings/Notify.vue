<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createChannel,
  createGroup,
  createRecipient,
  createRoute,
  deleteChannel,
  deleteGroup,
  deleteRecipient,
  deleteRoute,
  listChannels,
  listGroups,
  listNotifyLogs,
  listRecipients,
  listRoutes,
  testChannel,
  updateChannel,
  updateGroup,
  updateRecipient,
  updateRoute,
} from '@/api/notify'
import {
  CHANNEL_LABEL,
  LEVEL_LABEL,
  type NotifyChannel,
  type NotifyLog,
  type NotifyRoute,
  type Recipient,
  type RecipientGroup,
} from '@/api/types'
import { formatLocal } from '@/lib/datetime'
import { handleErr } from '@/lib/errors'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const tab = ref('channels')

const channels = ref<NotifyChannel[]>([])
const recipients = ref<Recipient[]>([])
const groups = ref<RecipientGroup[]>([])
const routes = ref<NotifyRoute[]>([])
const logs = ref<NotifyLog[]>([])

const CHANNEL_TYPES = ['sms', 'email', 'dingtalk', 'wecom', 'voice', 'webhook']

async function loadAll(): Promise<void> {
  ;[channels.value, recipients.value, groups.value, routes.value] = await Promise.all([
    listChannels(),
    listRecipients(),
    listGroups(),
    listRoutes(),
  ])
}
async function loadLogs(): Promise<void> {
  logs.value = await listNotifyLogs(100)
}

// ---------------- 渠道 ----------------
const chDialog = ref(false)
const chEditId = ref<number | null>(null)
const chForm = reactive({ type: 'sms', name: '', configText: '{}', enabled: true })

function openCh(c?: NotifyChannel): void {
  if (c) {
    chEditId.value = c.id
    chForm.type = c.type
    chForm.name = c.name
    chForm.configText = JSON.stringify(c.config, null, 2)
    chForm.enabled = c.enabled
  } else {
    chEditId.value = null
    Object.assign(chForm, { type: 'sms', name: '', configText: '{}', enabled: true })
  }
  chDialog.value = true
}
async function saveCh(): Promise<void> {
  let config: Record<string, unknown>
  try {
    config = JSON.parse(chForm.configText)
  } catch {
    ElMessage.error('配置不是合法 JSON')
    return
  }
  try {
    if (chEditId.value === null) {
      await createChannel({ type: chForm.type, name: chForm.name, config, enabled: chForm.enabled })
    } else {
      await updateChannel(chEditId.value, { name: chForm.name, config, enabled: chForm.enabled })
    }
    ElMessage.success('已保存')
    chDialog.value = false
    loadAll()
  } catch (e) {
    handleErr(e)
  }
}
async function testCh(c: NotifyChannel): Promise<void> {
  try {
    const r = await testChannel(c.id)
    if (r.ok) ElMessage.success(`连通正常：${r.detail}`)
    else ElMessage.error(`连通失败：${r.detail}`)
  } catch (e) {
    handleErr(e)
  }
}
async function removeCh(c: NotifyChannel): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除渠道 ${c.name}？`, '提示', { type: 'warning' })
    await deleteChannel(c.id)
    loadAll()
  } catch (e) {
    if (e !== 'cancel') handleErr(e)
  }
}

// ---------------- 接收人 ----------------
const rcDialog = ref(false)
const rcEditId = ref<number | null>(null)
const rcForm = reactive({
  name: '',
  phone: '',
  email: '',
  dingtalk_id: '',
  wecom_id: '',
  enabled: true,
})
function openRc(r?: Recipient): void {
  if (r) {
    rcEditId.value = r.id
    Object.assign(rcForm, {
      name: r.name,
      phone: r.phone || '',
      email: r.email || '',
      dingtalk_id: r.dingtalk_id || '',
      wecom_id: r.wecom_id || '',
      enabled: r.enabled,
    })
  } else {
    rcEditId.value = null
    Object.assign(rcForm, {
      name: '',
      phone: '',
      email: '',
      dingtalk_id: '',
      wecom_id: '',
      enabled: true,
    })
  }
  rcDialog.value = true
}
async function saveRc(): Promise<void> {
  const body = {
    name: rcForm.name,
    phone: rcForm.phone || null,
    email: rcForm.email || null,
    dingtalk_id: rcForm.dingtalk_id || null,
    wecom_id: rcForm.wecom_id || null,
    enabled: rcForm.enabled,
  }
  try {
    if (rcEditId.value === null) await createRecipient(body)
    else await updateRecipient(rcEditId.value, body)
    ElMessage.success('已保存')
    rcDialog.value = false
    loadAll()
  } catch (e) {
    handleErr(e)
  }
}
async function removeRc(r: Recipient): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除接收人 ${r.name}？`, '提示', { type: 'warning' })
    await deleteRecipient(r.id)
    loadAll()
  } catch (e) {
    if (e !== 'cancel') handleErr(e)
  }
}

// ---------------- 接收组 ----------------
const grDialog = ref(false)
const grEditId = ref<number | null>(null)
const grForm = reactive({ name: '', member_ids: [] as number[] })
function openGr(g?: RecipientGroup): void {
  if (g) {
    grEditId.value = g.id
    grForm.name = g.name
    grForm.member_ids = [...g.member_ids]
  } else {
    grEditId.value = null
    grForm.name = ''
    grForm.member_ids = []
  }
  grDialog.value = true
}
async function saveGr(): Promise<void> {
  const body = { name: grForm.name, member_ids: grForm.member_ids }
  try {
    if (grEditId.value === null) await createGroup(body)
    else await updateGroup(grEditId.value, body)
    ElMessage.success('已保存')
    grDialog.value = false
    loadAll()
  } catch (e) {
    handleErr(e)
  }
}
async function removeGr(g: RecipientGroup): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除接收组 ${g.name}？`, '提示', { type: 'warning' })
    await deleteGroup(g.id)
    loadAll()
  } catch (e) {
    if (e !== 'cancel') handleErr(e)
  }
}

// ---------------- 级别路由 ----------------
const rtDialog = ref(false)
const rtEditId = ref<number | null>(null)
const rtForm = reactive({
  level: 1,
  channel_ids: [] as number[],
  group_ids: [] as number[],
  notify_on_recover: true,
  enabled: true,
})
function openRt(r?: NotifyRoute): void {
  if (r) {
    rtEditId.value = r.id
    Object.assign(rtForm, {
      level: r.level,
      channel_ids: [...r.channel_ids],
      group_ids: [...r.group_ids],
      notify_on_recover: r.notify_on_recover,
      enabled: r.enabled,
    })
  } else {
    rtEditId.value = null
    Object.assign(rtForm, {
      level: 1,
      channel_ids: [],
      group_ids: [],
      notify_on_recover: true,
      enabled: true,
    })
  }
  rtDialog.value = true
}
async function saveRt(): Promise<void> {
  const body = { ...rtForm }
  try {
    if (rtEditId.value === null) await createRoute(body)
    else await updateRoute(rtEditId.value, body)
    ElMessage.success('已保存')
    rtDialog.value = false
    loadAll()
  } catch (e) {
    handleErr(e)
  }
}
async function removeRt(r: NotifyRoute): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除 ${LEVEL_LABEL[r.level]} 路由？`, '提示', { type: 'warning' })
    await deleteRoute(r.id)
    loadAll()
  } catch (e) {
    if (e !== 'cancel') handleErr(e)
  }
}

function channelName(id: number): string {
  return channels.value.find((c) => c.id === id)?.name || `#${id}`
}
function groupName(id: number): string {
  return groups.value.find((g) => g.id === id)?.name || `#${id}`
}

onMounted(loadAll)
</script>

<template>
  <el-card shadow="never">
    <template #header>通知配置</template>
    <el-tabs v-model="tab" @tab-change="(n: string | number) => n === 'logs' && loadLogs()">
      <!-- 渠道 -->
      <el-tab-pane label="渠道" name="channels">
        <el-button v-if="auth.isAdmin" type="primary" size="small" class="mb" @click="openCh()">
          新建渠道
        </el-button>
        <el-table :data="channels" size="small" border>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">{{ CHANNEL_LABEL[row.type] || row.type }}</template>
          </el-table-column>
          <el-table-column prop="name" label="名称" />
          <el-table-column label="启用" width="70">
            <template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <template v-if="auth.isAdmin">
                <el-button text size="small" @click="openCh(row)">编辑</el-button>
                <el-button text size="small" @click="testCh(row)">测试</el-button>
                <el-button text size="small" type="danger" @click="removeCh(row)">删除</el-button>
              </template>
              <span v-else class="ro">只读</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 接收人 -->
      <el-tab-pane label="接收人" name="recipients">
        <el-button v-if="auth.isAdmin" type="primary" size="small" class="mb" @click="openRc()">
          新建接收人
        </el-button>
        <el-table :data="recipients" size="small" border>
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="phone" label="手机" width="140" />
          <el-table-column prop="email" label="邮箱" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <template v-if="auth.isAdmin">
                <el-button text size="small" @click="openRc(row)">编辑</el-button>
                <el-button text size="small" type="danger" @click="removeRc(row)">删除</el-button>
              </template>
              <span v-else class="ro">只读</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 接收组 -->
      <el-tab-pane label="接收组" name="groups">
        <el-button v-if="auth.isAdmin" type="primary" size="small" class="mb" @click="openGr()">
          新建接收组
        </el-button>
        <el-table :data="groups" size="small" border>
          <el-table-column prop="name" label="组名" width="160" />
          <el-table-column label="成员">
            <template #default="{ row }">
              {{ row.member_ids.length }} 人：
              {{ row.member_ids.map((id: number) => recipients.find((r) => r.id === id)?.name || id).join(', ') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <template v-if="auth.isAdmin">
                <el-button text size="small" @click="openGr(row)">编辑</el-button>
                <el-button text size="small" type="danger" @click="removeGr(row)">删除</el-button>
              </template>
              <span v-else class="ro">只读</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 级别路由 -->
      <el-tab-pane label="级别路由" name="routes">
        <el-button v-if="auth.isAdmin" type="primary" size="small" class="mb" @click="openRt()">
          新建路由
        </el-button>
        <el-table :data="routes" size="small" border>
          <el-table-column label="级别" width="90">
            <template #default="{ row }">{{ LEVEL_LABEL[row.level] || row.level }}</template>
          </el-table-column>
          <el-table-column label="渠道">
            <template #default="{ row }">{{ row.channel_ids.map(channelName).join(', ') }}</template>
          </el-table-column>
          <el-table-column label="接收组">
            <template #default="{ row }">{{ row.group_ids.map(groupName).join(', ') }}</template>
          </el-table-column>
          <el-table-column label="恢复通知" width="90">
            <template #default="{ row }">{{ row.notify_on_recover ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <template v-if="auth.isAdmin">
                <el-button text size="small" @click="openRt(row)">编辑</el-button>
                <el-button text size="small" type="danger" @click="removeRt(row)">删除</el-button>
              </template>
              <span v-else class="ro">只读</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 发送记录 -->
      <el-tab-pane label="发送记录" name="logs">
        <el-button size="small" class="mb" @click="loadLogs">刷新</el-button>
        <el-table :data="logs" size="small" border>
          <el-table-column label="时间" width="180">
            <template #default="{ row }">{{ formatLocal(row.sent_at) }}</template>
          </el-table-column>
          <el-table-column prop="recipient" label="接收方" />
          <el-table-column prop="trigger" label="触发" width="90" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="error" label="错误" />
          <el-table-column prop="retry_count" label="重试" width="70" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 渠道弹窗 -->
    <el-dialog v-model="chDialog" :title="chEditId === null ? '新建渠道' : '编辑渠道'" width="520px">
      <el-form label-width="80px">
        <el-form-item label="类型">
          <el-select v-model="chForm.type" :disabled="chEditId !== null" style="width: 200px">
            <el-option v-for="t in CHANNEL_TYPES" :key="t" :label="CHANNEL_LABEL[t]" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="chForm.name" /></el-form-item>
        <el-form-item label="配置">
          <el-input
            v-model="chForm.configText"
            type="textarea"
            :rows="6"
            placeholder='JSON，如 {"gateway_url":"...","api_key":"..."}'
          />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="chForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="chDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCh">保存</el-button>
      </template>
    </el-dialog>

    <!-- 接收人弹窗 -->
    <el-dialog v-model="rcDialog" :title="rcEditId === null ? '新建接收人' : '编辑接收人'" width="460px">
      <el-form label-width="90px">
        <el-form-item label="姓名"><el-input v-model="rcForm.name" /></el-form-item>
        <el-form-item label="手机"><el-input v-model="rcForm.phone" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="rcForm.email" /></el-form-item>
        <el-form-item label="钉钉 ID"><el-input v-model="rcForm.dingtalk_id" /></el-form-item>
        <el-form-item label="企微 ID"><el-input v-model="rcForm.wecom_id" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="rcForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rcDialog = false">取消</el-button>
        <el-button type="primary" @click="saveRc">保存</el-button>
      </template>
    </el-dialog>

    <!-- 接收组弹窗 -->
    <el-dialog v-model="grDialog" :title="grEditId === null ? '新建接收组' : '编辑接收组'" width="460px">
      <el-form label-width="80px">
        <el-form-item label="组名"><el-input v-model="grForm.name" /></el-form-item>
        <el-form-item label="成员">
          <el-select v-model="grForm.member_ids" multiple style="width: 100%">
            <el-option v-for="r in recipients" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="grDialog = false">取消</el-button>
        <el-button type="primary" @click="saveGr">保存</el-button>
      </template>
    </el-dialog>

    <!-- 路由弹窗 -->
    <el-dialog v-model="rtDialog" :title="rtEditId === null ? '新建路由' : '编辑路由'" width="460px">
      <el-form label-width="90px">
        <el-form-item label="级别">
          <el-select v-model="rtForm.level" :disabled="rtEditId !== null" style="width: 160px">
            <el-option v-for="i in [1, 2, 3, 4, 5]" :key="i" :label="LEVEL_LABEL[i]" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="rtForm.channel_ids" multiple style="width: 100%">
            <el-option v-for="c in channels" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="接收组">
          <el-select v-model="rtForm.group_ids" multiple style="width: 100%">
            <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="恢复通知"><el-switch v-model="rtForm.notify_on_recover" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="rtForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rtDialog = false">取消</el-button>
        <el-button type="primary" @click="saveRt">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.mb {
  margin-bottom: 12px;
}
.ro {
  color: #9ca3af;
}
</style>
