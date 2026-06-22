<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchDevices, fetchPoints } from '@/api/assets'
import type { DeviceItem, PointItem } from '@/api/types'

const router = useRouter()
const route = useRoute()
const tab = ref('devices')
const devices = ref<DeviceItem[]>([])
const points = ref<PointItem[]>([])

const devKeyword = ref('')
const ptKeyword = ref('')
const ptDevice = ref('')
const ptImportance = ref<number | undefined>(undefined)

async function loadDevices(): Promise<void> {
  devices.value = await fetchDevices({ keyword: devKeyword.value || undefined })
}

async function loadPoints(): Promise<void> {
  points.value = await fetchPoints({
    keyword: ptKeyword.value || undefined,
    device: ptDevice.value || undefined,
    importance: ptImportance.value,
  })
}

function viewDevicePoints(d: DeviceItem): void {
  ptDevice.value = d.resource_id
  tab.value = 'points'
  loadPoints()
}

function statusTag(s: number | null): { type: string; text: string } {
  if (s === 0) return { type: 'danger', text: '通信中断' }
  if (s === 1) return { type: 'success', text: '正常' }
  return { type: 'info', text: '未知' }
}

onMounted(() => {
  // 审查 I9：从拓扑「查看测点」跳转携带 ?d=<resource_id> 时，按该设备过滤并切到测点标签
  const d = route.query.d
  if (typeof d === 'string' && d) {
    ptDevice.value = d
    tab.value = 'points'
  }
  loadDevices()
  loadPoints()
})
</script>

<template>
  <el-card shadow="never">
    <el-tabs v-model="tab">
      <el-tab-pane label="设备" name="devices">
        <div class="bar">
          <el-input
            v-model="devKeyword"
            placeholder="按名称/ID 搜索设备"
            clearable
            style="width: 260px"
            @keyup.enter="loadDevices"
            @clear="loadDevices"
          />
          <el-button type="primary" @click="loadDevices">搜索</el-button>
        </div>
        <el-table :data="devices" size="small" border>
          <el-table-column prop="name" label="设备名称" />
          <el-table-column prop="device_type" label="类型" width="120" />
          <el-table-column prop="resource_id" label="ID" width="140" />
          <el-table-column label="通信状态" width="110">
            <template #default="{ row }">
              <el-tag :type="statusTag(row.status).type" size="small">
                {{ statusTag(row.status).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="活动告警" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.active_alarms > 0" type="danger" size="small">
                {{ row.active_alarms }}
              </el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button text size="small" @click="viewDevicePoints(row)">查看测点</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="测点" name="points">
        <div class="bar">
          <el-input
            v-model="ptKeyword"
            placeholder="按名称/ID 搜索测点"
            clearable
            style="width: 240px"
            @keyup.enter="loadPoints"
            @clear="loadPoints"
          />
          <el-input
            v-model="ptDevice"
            placeholder="设备ID过滤"
            clearable
            style="width: 160px"
            @clear="loadPoints"
          />
          <el-select
            v-model="ptImportance"
            placeholder="重要度"
            clearable
            style="width: 120px"
            @change="loadPoints"
          >
            <el-option v-for="i in [1, 2, 3, 4, 5]" :key="i" :label="`重要度 ${i}`" :value="i" />
          </el-select>
          <el-button type="primary" @click="loadPoints">搜索</el-button>
        </div>
        <el-table :data="points" size="small" border>
          <el-table-column prop="name" label="测点名称" />
          <el-table-column prop="resource_id" label="ID" width="160" />
          <el-table-column prop="device_id" label="所属设备" width="120" />
          <el-table-column label="当前值" width="110">
            <template #default="{ row }">
              {{ row.value == null ? '—' : `${row.value}${row.unit ?? ''}` }}
            </template>
          </el-table-column>
          <el-table-column prop="importance" label="重要度" width="80" />
          <el-table-column label="告警" width="70">
            <template #default="{ row }">
              <el-tag v-if="row.active_alarms > 0" type="danger" size="small">
                {{ row.active_alarms }}
              </el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button text size="small" @click="router.push(`/points/${row.resource_id}`)">
                详情
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<style scoped>
.bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
</style>
