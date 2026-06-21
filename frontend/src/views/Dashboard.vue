<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchActiveAlarms, fetchAlarmStats } from '@/api/alarms'
import { fetchPoints, fetchSpaceTree } from '@/api/assets'
import type { Alarm, AlarmStats, PointItem, SpaceNode } from '@/api/types'
import { LEVEL_LABEL, LEVEL_TAG } from '@/api/types'
import { formatLocal } from '@/lib/datetime'
import { useRealtimeSocket } from '@/composables/useWebSocket'

const router = useRouter()
const stats = ref<AlarmStats | null>(null)
const areas = ref<SpaceNode[]>([])
const keyPoints = ref<PointItem[]>([])
const recentAlarms = ref<Alarm[]>([])
const { latest, connected, connect, subscribe } = useRealtimeSocket()

let timer: ReturnType<typeof setInterval> | null = null

const levelCards = computed(() =>
  [1, 2, 3, 4, 5].map((lv) => ({
    level: lv,
    label: LEVEL_LABEL[lv],
    count: stats.value?.by_level?.[String(lv)] ?? 0,
  })),
)

function liveValue(p: PointItem): string {
  const l = latest.value[p.resource_id]
  const v = l ? l.value : p.value
  return v == null ? '—' : `${v}${p.unit ?? ''}`
}

async function refresh(): Promise<void> {
  stats.value = await fetchAlarmStats()
  areas.value = await fetchSpaceTree()
  recentAlarms.value = (await fetchActiveAlarms({})).slice(0, 8)
}

onMounted(async () => {
  await refresh()
  // 关键测点：取前若干个测点做实时刷新演示
  const pts = await fetchPoints({})
  keyPoints.value = pts.slice(0, 12)
  connect()
  subscribe(keyPoints.value.map((p) => p.resource_id))
  timer = setInterval(refresh, 15000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="dash">
    <!-- KPI 卡片 -->
    <el-row :gutter="12">
      <el-col :xs="8" :sm="4">
        <el-card shadow="hover" class="kpi">
          <div class="kpi-num">{{ stats?.active_total ?? 0 }}</div>
          <div class="kpi-label">活动告警</div>
        </el-card>
      </el-col>
      <el-col v-for="c in levelCards" :key="c.level" :xs="8" :sm="4">
        <el-card shadow="hover" class="kpi" :class="`lv-${c.level}`">
          <div class="kpi-num">{{ c.count }}</div>
          <div class="kpi-label">{{ c.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top: 12px">
      <!-- 区域状态 -->
      <el-col :xs="24" :md="10">
        <el-card shadow="never">
          <template #header>区域状态</template>
          <div v-for="a in areas" :key="a.resource_id">
            <div class="area-row" @click="router.push('/topology')">
              <span class="area-name">{{ a.alias || a.name }}</span>
              <el-tag
                v-if="a.active_alarms > 0"
                :type="LEVEL_TAG[a.max_level || 5]"
                size="small"
              >
                {{ a.active_alarms }} 条告警 · 最高{{ LEVEL_LABEL[a.max_level || 5] }}
              </el-tag>
              <el-tag v-else type="success" size="small">正常</el-tag>
            </div>
            <div v-for="c in a.children" :key="c.resource_id" class="area-row sub">
              <span class="area-name">└ {{ c.alias || c.name }}</span>
              <el-tag v-if="c.active_alarms > 0" :type="LEVEL_TAG[c.max_level || 5]" size="small">
                {{ c.active_alarms }} 条
              </el-tag>
              <el-tag v-else type="success" size="small">正常</el-tag>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 关键测点实时 -->
      <el-col :xs="24" :md="14">
        <el-card shadow="never">
          <template #header>
            关键测点（实时）
            <el-tag size="small" :type="connected ? 'success' : 'info'" style="margin-left: 8px">
              WS {{ connected ? '已连接' : '未连接' }}
            </el-tag>
          </template>
          <el-table :data="keyPoints" size="small" height="280">
            <el-table-column prop="name" label="测点" />
            <el-table-column label="当前值" width="120">
              <template #default="{ row }">
                <b>{{ liveValue(row) }}</b>
              </template>
            </el-table-column>
            <el-table-column label="告警" width="80">
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
        </el-card>
      </el-col>
    </el-row>

    <!-- 最新活动告警 -->
    <el-card shadow="never" style="margin-top: 12px">
      <template #header>最新活动告警</template>
      <el-table :data="recentAlarms" size="small">
        <el-table-column label="级别" width="80">
          <template #default="{ row }">
            <el-tag :type="LEVEL_TAG[row.level]" size="small">{{ LEVEL_LABEL[row.level] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="resource_id" label="资源" width="160" />
        <el-table-column prop="content" label="内容" />
        <el-table-column prop="source" label="来源" width="90" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="触发时间" width="200">
          <template #default="{ row }">{{ formatLocal(row.triggered_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.dash {
  padding: 4px;
}
.kpi {
  text-align: center;
}
.kpi-num {
  font-size: 30px;
  font-weight: 700;
  color: #111827;
}
.kpi-label {
  color: #6b7280;
  margin-top: 4px;
}
.lv-1 .kpi-num,
.lv-2 .kpi-num {
  color: #dc2626;
}
.lv-3 .kpi-num,
.lv-4 .kpi-num {
  color: #d97706;
}
.area-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  cursor: pointer;
}
.area-row.sub {
  padding-left: 12px;
  color: #6b7280;
}
.area-name {
  font-size: 14px;
}
@media (max-width: 767px) {
  .kpi-num {
    font-size: 22px;
  }
  .kpi-label {
    font-size: 12px;
  }
}
</style>
