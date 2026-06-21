<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'

import {
  acceptAlarm,
  confirmAlarm,
  fetchActiveAlarms,
  fetchAlarmDetail,
  noteAlarm,
  queryAlarmHistory,
} from '@/api/alarms'
import type { Alarm, AlarmDetail } from '@/api/types'
import { LEVEL_LABEL, LEVEL_TAG } from '@/api/types'
import { useAuthStore } from '@/store/auth'
import { formatLocal } from '@/lib/datetime'

const auth = useAuthStore()
const isMobile = ref(false)
function onResizeAlarm(): void {
  isMobile.value = window.innerWidth < 768
}
onMounted(() => {
  onResizeAlarm()
  window.addEventListener('resize', onResizeAlarm)
})
onUnmounted(() => window.removeEventListener('resize', onResizeAlarm))
const drawerSize = computed(() => (isMobile.value ? '92%' : '46%'))
const tab = ref('active')
const list = ref<Alarm[]>([])
const fLevel = ref<number | undefined>(undefined)
const fSource = ref<string | undefined>(undefined)
const fMasked = ref<boolean | undefined>(undefined)
const histDays = ref(1)

const drawer = ref(false)
const detail = ref<AlarmDetail | null>(null)

async function loadActive(): Promise<void> {
  list.value = await fetchActiveAlarms({
    level: fLevel.value,
    source: fSource.value,
    masked: fMasked.value,
  })
}

async function loadHistory(): Promise<void> {
  const now = Math.floor(Date.now() / 1000)
  const res = await queryAlarmHistory({
    start: now - histDays.value * 86400,
    end: now,
    level: fLevel.value,
    source: fSource.value,
  })
  list.value = res.items
}

function reload(): void {
  tab.value === 'active' ? loadActive() : loadHistory()
}

async function openDetail(row: Alarm): Promise<void> {
  detail.value = await fetchAlarmDetail(row.id)
  drawer.value = true
}

async function doAccept(): Promise<void> {
  if (!detail.value) return
  const { value } = await ElMessageBox.prompt('受理备注', '受理', { inputValue: '已派单处理' })
  await acceptAlarm(detail.value.id, value || '')
  ElMessage.success('已受理')
  detail.value = await fetchAlarmDetail(detail.value.id)
  reload()
}

async function doConfirm(): Promise<void> {
  if (!detail.value) return
  const { value } = await ElMessageBox.prompt('确认备注', '确认', { inputValue: '已处理完成' })
  await confirmAlarm(detail.value.id, value || '')
  ElMessage.success('已确认')
  detail.value = await fetchAlarmDetail(detail.value.id)
  reload()
}

async function doNote(): Promise<void> {
  if (!detail.value) return
  const { value } = await ElMessageBox.prompt('追加备注', '备注', { inputValue: '' })
  if (!value) return
  await noteAlarm(detail.value.id, value)
  ElMessage.success('已备注')
  detail.value = await fetchAlarmDetail(detail.value.id)
}

const EVENT_LABEL: Record<string, string> = {
  raise: '产生',
  accept: '受理',
  confirm: '确认',
  recover: '恢复',
  note: '备注',
  merge: '合并',
}

onMounted(loadActive)
</script>

<template>
  <el-card shadow="never">
    <el-tabs v-model="tab" @tab-change="reload">
      <el-tab-pane label="活动告警" name="active" />
      <el-tab-pane label="历史告警" name="history" />
    </el-tabs>

    <div class="bar">
      <el-select v-model="fLevel" placeholder="级别" clearable style="width: 110px">
        <el-option v-for="i in [1, 2, 3, 4, 5]" :key="i" :label="LEVEL_LABEL[i]" :value="i" />
      </el-select>
      <el-select v-model="fSource" placeholder="来源" clearable style="width: 120px">
        <el-option label="平台" value="platform" />
        <el-option label="EMS" value="ems" />
      </el-select>
      <el-select
        v-if="tab === 'active'"
        v-model="fMasked"
        placeholder="屏蔽态"
        clearable
        style="width: 120px"
      >
        <el-option label="仅未屏蔽" :value="false" />
        <el-option label="仅已屏蔽" :value="true" />
      </el-select>
      <el-select v-if="tab === 'history'" v-model="histDays" style="width: 120px">
        <el-option :label="'近 1 天'" :value="1" />
        <el-option :label="'近 7 天'" :value="7" />
        <el-option :label="'近 30 天'" :value="30" />
      </el-select>
      <el-button type="primary" @click="reload">查询</el-button>
    </div>

    <el-table :data="list" size="small" border @row-click="openDetail">
      <el-table-column label="级别" width="80">
        <template #default="{ row }">
          <el-tag :type="LEVEL_TAG[row.level]" size="small">{{ LEVEL_LABEL[row.level] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="resource_id" label="资源" width="150" />
      <el-table-column prop="content" label="内容" show-overflow-tooltip />
      <el-table-column prop="source" label="来源" width="80" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="屏蔽" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.masked" type="info" size="small">{{ row.silenced_reason }}</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="merge_count" label="合并" width="70" />
      <el-table-column label="触发时间" width="200">
        <template #default="{ row }">{{ formatLocal(row.triggered_at) }}</template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawer" title="告警详情" :size="drawerSize">
      <div v-if="detail">
        <el-descriptions :column="isMobile ? 1 : 2" border size="small">
          <el-descriptions-item label="级别">{{ LEVEL_LABEL[detail.level] }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="资源">{{ detail.resource_id }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ detail.source }}</el-descriptions-item>
          <el-descriptions-item label="触发值">{{ detail.trigger_value ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="合并次数">{{ detail.merge_count }}</el-descriptions-item>
          <el-descriptions-item label="内容" :span="2">{{ detail.content }}</el-descriptions-item>
          <el-descriptions-item label="建议" :span="2">{{ detail.suggest || '—' }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="auth.canWrite && detail.status !== 'recovered'" class="actions">
          <el-button type="primary" size="small" @click="doAccept">受理</el-button>
          <el-button type="success" size="small" @click="doConfirm">确认</el-button>
          <el-button size="small" @click="doNote">备注</el-button>
        </div>
        <el-alert
          v-else-if="!auth.canWrite"
          title="只读角色：不可处理告警"
          type="info"
          :closable="false"
          style="margin: 12px 0"
        />

        <h4>生命周期</h4>
        <el-timeline>
          <el-timeline-item
            v-for="ev in detail.events"
            :key="ev.id"
            :timestamp="formatLocal(ev.occurred_at)"
          >
            <b>{{ EVENT_LABEL[ev.event] || ev.event }}</b>
            <span v-if="ev.note"> — {{ ev.note }}</span>
            <span v-if="ev.snapshot != null"> （值 {{ ev.snapshot }}）</span>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.actions {
  margin: 14px 0;
  display: flex;
  gap: 8px;
}
h4 {
  margin: 14px 0 8px;
}
</style>
