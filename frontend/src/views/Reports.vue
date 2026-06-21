<script setup lang="ts">
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  createSchedule,
  deleteSchedule,
  exportAlarms,
  exportHistory,
  fetchAlarmReportStats,
  fetchRecipientGroups,
  fetchSchedules,
  runScheduleNow,
  updateSchedule,
} from '@/api/reports'
import { searchPoints } from '@/api/history'
import type { AlarmReportStats, PointItem, RecipientGroup, ReportSchedule } from '@/api/types'
import { LEVEL_LABEL } from '@/api/types'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()

// ---- 统计区间 ----
const granularity = ref<'day' | 'week' | 'month'>('day')
const rangeDays = ref(7)
const stats = ref<AlarmReportStats | null>(null)
const chartEl = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const LEVEL_COLOR: Record<number, string> = {
  1: '#dc2626',
  2: '#ea580c',
  3: '#d97706',
  4: '#0891b2',
  5: '#4f46e5',
}
const SOURCE_LABEL: Record<string, string> = { platform: '平台规则', ems: 'EMS设备' }

const rangePresets = [
  { label: '近 7 天', v: 7 },
  { label: '近 30 天', v: 30 },
  { label: '近 90 天', v: 90 },
]

function currentRange(): { start: number; end: number } {
  const end = Math.floor(Date.now() / 1000)
  return { start: end - rangeDays.value * 86400, end }
}

const levelCards = computed(() =>
  [1, 2, 3, 4, 5].map((lv) => ({
    level: lv,
    label: LEVEL_LABEL[lv],
    count: stats.value?.by_level?.[String(lv)] ?? 0,
    color: LEVEL_COLOR[lv],
  })),
)

const mttaMin = computed(() =>
  stats.value?.mtta_seconds != null ? (stats.value.mtta_seconds / 60).toFixed(1) : '—',
)
const mttrMin = computed(() =>
  stats.value?.mttr_seconds != null ? (stats.value.mttr_seconds / 60).toFixed(1) : '—',
)

function onChartResize(): void {
  chart?.resize()
}

function renderChart(): void {
  if (!chart || !stats.value) return
  const buckets = stats.value.buckets
  const labels = buckets.map((b) => b.bucket)
  const series = [1, 2, 3, 4, 5].map((lv) => ({
    name: LEVEL_LABEL[lv],
    type: 'bar' as const,
    stack: 'total',
    itemStyle: { color: LEVEL_COLOR[lv] },
    data: buckets.map((b) => b.by_level?.[String(lv)] ?? 0),
  }))
  chart.setOption(
    {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { top: 0 },
      grid: { left: 48, right: 20, top: 36, bottom: 40 },
      xAxis: { type: 'category', data: labels },
      yAxis: { type: 'value', minInterval: 1 },
      series,
    },
    true,
  )
}

async function loadStats(): Promise<void> {
  const { start, end } = currentRange()
  stats.value = await fetchAlarmReportStats({ start, end, granularity: granularity.value })
  await nextTick()
  renderChart()
}

// ---- 导出 ----
async function doExportAlarms(fmt: 'csv' | 'xlsx'): Promise<void> {
  const { start, end } = currentRange()
  await exportAlarms({ start, end, fmt })
  ElMessage.success(`告警导出（${fmt.toUpperCase()}）已开始下载`)
}

// 历史数据导出（选点）
const kw = ref('')
const candidates = ref<PointItem[]>([])
const expPoints = ref<PointItem[]>([])
async function searchExpPoints(): Promise<void> {
  if (!kw.value) return
  candidates.value = await searchPoints(kw.value)
}
function addExpPoint(id: string): void {
  const p = candidates.value.find((c) => c.resource_id === id)
  if (p && !expPoints.value.find((x) => x.resource_id === id)) expPoints.value.push(p)
}
function removeExpPoint(id: string): void {
  expPoints.value = expPoints.value.filter((x) => x.resource_id !== id)
}
async function doExportHistory(fmt: 'csv' | 'xlsx'): Promise<void> {
  if (expPoints.value.length === 0) {
    ElMessage.warning('请先选择测点')
    return
  }
  const { start, end } = currentRange()
  await exportHistory(
    { point_ids: expPoints.value.map((p) => p.resource_id), start, end, agg: 'auto' },
    fmt,
  )
  ElMessage.success(`数据导出（${fmt.toUpperCase()}）已开始下载`)
}

// ---- 报表计划 ----
const schedules = ref<ReportSchedule[]>([])
const groups = ref<RecipientGroup[]>([])
const dialog = ref(false)
const editing = ref<ReportSchedule | null>(null)
const form = ref({
  name: '',
  report_type: 'daily' as 'daily' | 'weekly' | 'monthly',
  cron: '0 8 * * *',
  group_ids: [] as number[],
  enabled: true,
})
const cronPresets = [
  { label: '每日 08:00', v: '0 8 * * *' },
  { label: '每周一 08:00', v: '0 8 * * 1' },
  { label: '每月1日 08:00', v: '0 8 1 * *' },
]
const TYPE_LABEL: Record<string, string> = { daily: '日报', weekly: '周报', monthly: '月报' }

async function loadSchedules(): Promise<void> {
  if (!auth.isAdmin) return
  schedules.value = await fetchSchedules()
  groups.value = await fetchRecipientGroups()
}

function openCreate(): void {
  editing.value = null
  form.value = { name: '', report_type: 'daily', cron: '0 8 * * *', group_ids: [], enabled: true }
  dialog.value = true
}
function openEdit(s: ReportSchedule): void {
  editing.value = s
  form.value = {
    name: s.name || '',
    report_type: s.report_type,
    cron: s.cron,
    group_ids: [...s.group_ids],
    enabled: s.enabled,
  }
  dialog.value = true
}
async function saveSchedule(): Promise<void> {
  const payload = {
    name: form.value.name || null,
    report_type: form.value.report_type,
    cron: form.value.cron,
    group_ids: form.value.group_ids,
    enabled: form.value.enabled,
  }
  if (editing.value) {
    await updateSchedule(editing.value.id, payload)
    ElMessage.success('已更新报表计划')
  } else {
    await createSchedule(payload)
    ElMessage.success('已创建报表计划')
  }
  dialog.value = false
  await loadSchedules()
}
async function toggleEnabled(s: ReportSchedule): Promise<void> {
  await updateSchedule(s.id, { enabled: !s.enabled })
  await loadSchedules()
}
async function removeSchedule(s: ReportSchedule): Promise<void> {
  await ElMessageBox.confirm(`确认删除报表计划「${s.name || s.id}」？`, '删除', { type: 'warning' })
  await deleteSchedule(s.id)
  ElMessage.success('已删除')
  await loadSchedules()
}
async function runNow(s: ReportSchedule): Promise<void> {
  const r = await runScheduleNow(s.id)
  if (r.sent) {
    ElMessage.success(`已发送给 ${r.recipients} 个收件人（共 ${r.total} 条告警）`)
  } else {
    ElMessage.warning(`未发送：${r.reason}（统计 ${r.total} 条）`)
  }
  await loadSchedules()
}

watch(granularity, loadStats)

onMounted(async () => {
  await loadStats()
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    renderChart()
    // 审查 D2：具名回调，便于 onBeforeUnmount 对称移除，避免匿名监听泄漏
    window.addEventListener('resize', onChartResize)
  }
  await loadSchedules()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onChartResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="reports">
    <!-- 统计 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>告警统计报表</span>
          <div class="controls">
            <el-radio-group v-model="rangeDays" size="small" @change="loadStats">
              <el-radio-button v-for="r in rangePresets" :key="r.v" :value="r.v">
                {{ r.label }}
              </el-radio-button>
            </el-radio-group>
            <el-select v-model="granularity" size="small" style="width: 110px">
              <el-option label="按日" value="day" />
              <el-option label="按周" value="week" />
              <el-option label="按月" value="month" />
            </el-select>
            <el-button size="small" type="primary" @click="loadStats">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="kpi-row">
        <div class="kpi total">
          <div class="kpi-num">{{ stats?.total ?? 0 }}</div>
          <div class="kpi-label">告警总数</div>
        </div>
        <div v-for="c in levelCards" :key="c.level" class="kpi">
          <div class="kpi-num" :style="{ color: c.color }">{{ c.count }}</div>
          <div class="kpi-label">{{ c.label }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-num">{{ mttaMin }}</div>
          <div class="kpi-label">MTTA(分)</div>
        </div>
        <div class="kpi">
          <div class="kpi-num">{{ mttrMin }}</div>
          <div class="kpi-label">MTTR(分)</div>
        </div>
      </div>

      <div ref="chartEl" class="chart"></div>

      <el-row :gutter="12" class="below">
        <el-col :xs="24" :md="12">
          <div class="sub-title">按来源</div>
          <div v-for="(cnt, src) in stats?.by_source || {}" :key="src" class="src-row">
            <span>{{ SOURCE_LABEL[src] || src }}</span>
            <b>{{ cnt }}</b>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="sub-title">Top 告警资源</div>
          <el-table :data="stats?.top_resources || []" size="small" max-height="220">
            <el-table-column label="资源">
              <template #default="{ row }">{{ row.name || row.resource_id }}</template>
            </el-table-column>
            <el-table-column prop="count" label="次数" width="90" />
          </el-table>
        </el-col>
      </el-row>
    </el-card>

    <!-- 导出 -->
    <el-card shadow="never" class="mt">
      <template #header>数据 / 告警导出</template>
      <div class="export-block">
        <div class="export-label">告警明细（当前统计区间）：</div>
        <el-button size="small" @click="doExportAlarms('csv')">导出告警 CSV</el-button>
        <el-button size="small" @click="doExportAlarms('xlsx')">导出告警 Excel</el-button>
      </div>
      <el-divider />
      <div class="export-block">
        <div class="export-label">历史数据：</div>
        <el-input
          v-model="kw"
          placeholder="搜索测点"
          size="small"
          style="width: 200px"
          @keyup.enter="searchExpPoints"
        />
        <el-button size="small" @click="searchExpPoints">搜索</el-button>
        <el-select
          size="small"
          placeholder="加入"
          style="width: 200px"
          @change="addExpPoint"
        >
          <el-option
            v-for="c in candidates"
            :key="c.resource_id"
            :label="`${c.name} (${c.resource_id})`"
            :value="c.resource_id"
          />
        </el-select>
      </div>
      <div class="selected">
        <el-tag
          v-for="p in expPoints"
          :key="p.resource_id"
          closable
          style="margin: 0 6px 6px 0"
          @close="removeExpPoint(p.resource_id)"
        >
          {{ p.name }}
        </el-tag>
        <span v-if="expPoints.length === 0" class="hint">未选择测点</span>
      </div>
      <div class="export-block">
        <el-button size="small" @click="doExportHistory('csv')">导出数据 CSV</el-button>
        <el-button size="small" @click="doExportHistory('xlsx')">导出数据 Excel</el-button>
      </div>
    </el-card>

    <!-- 报表计划（仅管理员） -->
    <el-card v-if="auth.isAdmin" shadow="never" class="mt">
      <template #header>
        <div class="card-head">
          <span>定时邮件报表计划</span>
          <el-button size="small" type="primary" @click="openCreate">新建计划</el-button>
        </div>
      </template>
      <el-table :data="schedules" size="small" border>
        <el-table-column prop="name" label="名称" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ TYPE_LABEL[row.report_type] }}</template>
        </el-table-column>
        <el-table-column prop="cron" label="Cron" width="140" />
        <el-table-column label="接收组" width="90">
          <template #default="{ row }">{{ row.group_ids.length }} 组</template>
        </el-table-column>
        <el-table-column prop="next_run" label="下次触发" width="180" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button text size="small" @click="runNow(row)">立即发送</el-button>
            <el-button text size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text size="small" type="danger" @click="removeSchedule(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="schedules.length === 0" description="暂无报表计划" />
    </el-card>

    <!-- 计划编辑弹窗 -->
    <el-dialog v-model="dialog" :title="editing ? '编辑报表计划' : '新建报表计划'" width="520px">
      <el-form label-width="92px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：机房日报" />
        </el-form-item>
        <el-form-item label="报表类型">
          <el-select v-model="form.report_type" style="width: 160px">
            <el-option label="日报" value="daily" />
            <el-option label="周报" value="weekly" />
            <el-option label="月报" value="monthly" />
          </el-select>
        </el-form-item>
        <el-form-item label="Cron 表达式">
          <el-input v-model="form.cron" placeholder="分 时 日 月 周，如 0 8 * * *" />
          <div class="preset-row">
            <el-button
              v-for="p in cronPresets"
              :key="p.v"
              size="small"
              text
              @click="form.cron = p.v"
            >
              {{ p.label }}
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="接收组">
          <el-select v-model="form.group_ids" multiple style="width: 100%">
            <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="saveSchedule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.kpi-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}
.kpi {
  flex: 1;
  min-width: 92px;
  text-align: center;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 8px;
  padding: 12px 4px;
}
.kpi.total .kpi-num {
  color: #111827;
}
.kpi-num {
  font-size: 28px;
  font-weight: 800;
  line-height: 1;
}
.kpi-label {
  color: #6b7280;
  margin-top: 6px;
  font-size: 13px;
}
.chart {
  height: 340px;
}
.below {
  margin-top: 12px;
}
.sub-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: #374151;
}
.src-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 4px;
  border-bottom: 1px dashed #eef2f7;
}
.mt {
  margin-top: 12px;
}
.export-block {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 6px 0;
}
.export-label {
  color: #374151;
}
.selected {
  margin: 8px 0;
  min-height: 26px;
}
.hint {
  color: #9ca3af;
}
.preset-row {
  margin-top: 4px;
}
</style>
