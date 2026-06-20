<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchPointDetail } from '@/api/assets'
import { queryHistory } from '@/api/history'
import type { PointDetail } from '@/api/types'
import { LEVEL_LABEL, LEVEL_TAG } from '@/api/types'
import LineChart, { type Series } from '@/components/LineChart.vue'
import { useRealtimeSocket } from '@/composables/useWebSocket'

const route = useRoute()
const router = useRouter()
const pointId = route.params.id as string

const detail = ref<PointDetail | null>(null)
const series = ref<Series[]>([])
const rangeSec = ref(3600)
const layer = ref('')
const { latest, connect, subscribe } = useRealtimeSocket()

const liveValue = computed(() => {
  const l = latest.value[pointId]
  const v = l ? l.value : detail.value?.value
  return v == null ? '—' : `${v}${detail.value?.unit ?? ''}`
})

const ranges = [
  { label: '近1时', v: 3600 },
  { label: '近6时', v: 21600 },
  { label: '近24时', v: 86400 },
  { label: '近7天', v: 604800 },
]

async function loadHistory(): Promise<void> {
  const now = Math.floor(Date.now() / 1000)
  const res = await queryHistory({
    point_ids: [pointId],
    start: now - rangeSec.value,
    end: now,
    agg: 'auto',
  })
  layer.value = res.layer
  const s = res.series[0]
  const data: [number, number | null][] =
    res.layer === 'raw'
      ? (s.raw || []).map((p) => [p.ts * 1000, p.value])
      : (s.agg || []).map((p) => [p.ts * 1000, p.avg])
  series.value = [{ name: detail.value?.name || pointId, data }]
}

// WS 实时点追加到曲线尾部
watch(
  () => latest.value[pointId],
  (l) => {
    if (l && series.value[0] && l.value != null) {
      const point: [number, number | null] = [Date.now(), Number(l.value)]
      const merged: [number, number | null][] = [...series.value[0].data, point]
      series.value = [{ name: series.value[0].name, data: merged.slice(-2000) }]
    }
  },
)

onMounted(async () => {
  detail.value = await fetchPointDetail(pointId)
  await loadHistory()
  connect()
  subscribe([pointId])
})

onUnmounted(() => {
  /* socket 在 composable onUnmounted 关闭 */
})
</script>

<template>
  <div v-if="detail">
    <el-page-header :content="detail.name" @back="router.back()" />
    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :xs="24" :md="8">
        <el-card shadow="never">
          <template #header>当前状态</template>
          <div class="big-value">{{ liveValue }}</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="测点ID">{{ detail.resource_id }}</el-descriptions-item>
            <el-descriptions-item label="所属设备">{{ detail.device_id }}</el-descriptions-item>
            <el-descriptions-item label="单位">{{ detail.unit || '—' }}</el-descriptions-item>
            <el-descriptions-item label="别名">{{ detail.alias || '—' }}</el-descriptions-item>
            <el-descriptions-item label="分组">{{ detail.group_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="重要度">{{ detail.importance ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="活动告警">{{ detail.active_alarms }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :xs="24" :md="16" class="chart-col">
        <el-card shadow="never">
          <template #header>
            实时 / 历史曲线
            <el-radio-group v-model="rangeSec" size="small" style="margin-left: 12px" @change="loadHistory">
              <el-radio-button v-for="r in ranges" :key="r.v" :value="r.v">{{ r.label }}</el-radio-button>
            </el-radio-group>
            <el-tag size="small" style="margin-left: 8px">命中层：{{ layer }}</el-tag>
          </template>
          <LineChart :series="series" :y-unit="detail.unit || ''" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-top: 12px">
      <template #header>预警规则</template>
      <el-table :data="detail.rules" size="small" border>
        <el-table-column prop="name" label="规则名" />
        <el-table-column label="条件" width="200">
          <template #default="{ row }">
            <span v-if="row.cond_type === 'range'">区间 [{{ row.operand_min }}, {{ row.operand_max }}]</span>
            <span v-else>{{ row.operator }} {{ row.operand }}</span>
          </template>
        </el-table-column>
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag :type="LEVEL_TAG[row.level]" size="small">{{ LEVEL_LABEL[row.level] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="detail.rules.length === 0" description="暂无规则" :image-size="60" />
    </el-card>
  </div>
</template>

<style scoped>
.big-value {
  font-size: 34px;
  font-weight: 700;
  color: #2563eb;
  margin-bottom: 12px;
}
@media (max-width: 767px) {
  .chart-col {
    margin-top: 12px;
  }
}
</style>
