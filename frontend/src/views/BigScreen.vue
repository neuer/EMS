<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchActiveAlarms, fetchAlarmStats } from '@/api/alarms'
import { fetchPoints, fetchSpaceTree } from '@/api/assets'
import { queryHistory } from '@/api/history'
import type { Alarm, AlarmStats, PointItem, SpaceNode } from '@/api/types'
import { LEVEL_LABEL } from '@/api/types'
import { useRealtimeSocket } from '@/composables/useWebSocket'
import { formatLocalTime } from '@/lib/datetime'

// 设计基准分辨率（值班墙 1920×1080），运行时按视口等比缩放自适应
const BASE_W = 1920
const BASE_H = 1080
const AREA_PAGE_SIZE = 4
const KEY_POINT_COUNT = 6

const router = useRouter()
const scale = ref(1)
const now = ref(new Date())
const stats = ref<AlarmStats | null>(null)
const alarms = ref<Alarm[]>([])
const areas = ref<SpaceNode[]>([])
const keyPoints = ref<PointItem[]>([])
const areaPage = ref(0)
const { latest, connected, connect, subscribe } = useRealtimeSocket()

const chartEl = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const LEVEL_COLOR: Record<number, string> = {
  1: '#ff4d4f',
  2: '#ff7a45',
  3: '#faad14',
  4: '#36cfc9',
  5: '#597ef7',
}

let clockTimer: ReturnType<typeof setInterval> | null = null
let dataTimer: ReturnType<typeof setInterval> | null = null
let alarmTimer: ReturnType<typeof setInterval> | null = null
let areaTimer: ReturnType<typeof setInterval> | null = null

const wrapStyle = computed(() => ({
  width: `${BASE_W}px`,
  height: `${BASE_H}px`,
  transform: `translate(-50%, -50%) scale(${scale.value})`,
}))

const clockText = computed(() =>
  now.value.toLocaleString('zh-CN', { hour12: false }),
)

const levelCards = computed(() =>
  [1, 2, 3, 4, 5].map((lv) => ({
    level: lv,
    label: LEVEL_LABEL[lv],
    count: stats.value?.by_level?.[String(lv)] ?? 0,
    color: LEVEL_COLOR[lv],
  })),
)

// 实时告警滚动：取活动告警，按级别优先，列表循环滚动展示
const scrollAlarms = computed(() => alarms.value)

const areaPages = computed(() => {
  const pages: SpaceNode[][] = []
  for (let i = 0; i < areas.value.length; i += AREA_PAGE_SIZE) {
    pages.push(areas.value.slice(i, i + AREA_PAGE_SIZE))
  }
  return pages.length ? pages : [[]]
})

const currentAreaPage = computed(() => areaPages.value[areaPage.value % areaPages.value.length])

function onChartResize(): void {
  chart?.resize()
}

function fitScale(): void {
  scale.value = Math.min(window.innerWidth / BASE_W, window.innerHeight / BASE_H)
}

function liveValue(p: PointItem): string {
  const l = latest.value[p.resource_id]
  const v = l ? l.value : p.value
  return v == null ? '—' : `${v}${p.unit ?? ''}`
}

function renderChart(series: { name: string; data: [number, number | null][] }[]): void {
  if (!chart) return
  chart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', top: 0, textStyle: { color: '#cbd5e1' } },
      grid: { left: 56, right: 24, top: 40, bottom: 36 },
      xAxis: {
        type: 'time',
        axisLabel: { color: '#94a3b8' },
        axisLine: { lineStyle: { color: '#334155' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: series.map((s) => ({
        name: s.name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: s.data,
      })),
    },
    true,
  )
}

async function loadCurves(): Promise<void> {
  if (keyPoints.value.length === 0) return
  const end = Math.floor(Date.now() / 1000)
  const res = await queryHistory({
    point_ids: keyPoints.value.map((p) => p.resource_id),
    start: end - 1800,
    end,
    agg: 'auto',
  })
  const nameOf = (id: string) =>
    keyPoints.value.find((p) => p.resource_id === id)?.name || id
  renderChart(
    res.series.map((s) => ({
      name: nameOf(s.point_id),
      data:
        res.layer === 'raw'
          ? (s.raw || []).map((p) => [p.ts * 1000, p.value] as [number, number | null])
          : (s.agg || []).map((p) => [p.ts * 1000, p.avg] as [number, number | null]),
    })),
  )
}

async function refresh(): Promise<void> {
  stats.value = await fetchAlarmStats()
  alarms.value = (await fetchActiveAlarms({})).slice(0, 30)
  areas.value = await fetchSpaceTree()
}

function rotateAlarms(): void {
  if (alarms.value.length > 6) {
    alarms.value = [...alarms.value.slice(1), alarms.value[0]]
  }
}

onMounted(async () => {
  fitScale()
  window.addEventListener('resize', fitScale)
  clockTimer = setInterval(() => (now.value = new Date()), 1000)

  await refresh()
  const pts = await fetchPoints({})
  keyPoints.value = pts.slice(0, KEY_POINT_COUNT)

  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    // 审查 D2：具名回调，便于 onUnmounted 对称移除，避免匿名监听泄漏
    window.addEventListener('resize', onChartResize)
  }
  await loadCurves()

  connect()
  subscribe(keyPoints.value.map((p) => p.resource_id))

  dataTimer = setInterval(async () => {
    await refresh()
    await loadCurves()
  }, 10000)
  alarmTimer = setInterval(rotateAlarms, 2500)
  areaTimer = setInterval(() => (areaPage.value += 1), 5000)
})

onUnmounted(() => {
  window.removeEventListener('resize', fitScale)
  window.removeEventListener('resize', onChartResize)
  if (clockTimer) clearInterval(clockTimer)
  if (dataTimer) clearInterval(dataTimer)
  if (alarmTimer) clearInterval(alarmTimer)
  if (areaTimer) clearInterval(areaTimer)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="screen-root">
    <div class="screen" :style="wrapStyle">
      <!-- 顶栏 -->
      <header class="bs-header">
        <span class="dot" :class="{ on: connected }" />
        <h1>数据中心动环监控预警 · NOC 值班大屏</h1>
        <div class="clock">{{ clockText }}</div>
        <el-button class="exit-btn" size="small" @click="router.push('/dashboard')">退出大屏</el-button>
      </header>

      <div class="bs-body">
        <!-- 左：级别统计 -->
        <section class="panel level-panel">
          <div class="panel-title">告警级别统计</div>
          <div class="total-card">
            <div class="total-num">{{ stats?.active_total ?? 0 }}</div>
            <div class="total-label">活动告警总数</div>
          </div>
          <div class="level-grid">
            <div v-for="c in levelCards" :key="c.level" class="level-card">
              <div class="level-num" :style="{ color: c.color }">{{ c.count }}</div>
              <div class="level-label">{{ c.label }}</div>
            </div>
          </div>
        </section>

        <!-- 中：关键曲线 -->
        <section class="panel chart-panel">
          <div class="panel-title">关键测点趋势（近 30 分钟）</div>
          <div ref="chartEl" class="chart"></div>
          <div class="kp-strip">
            <div v-for="p in keyPoints" :key="p.resource_id" class="kp">
              <span class="kp-name">{{ p.name }}</span>
              <span class="kp-val">{{ liveValue(p) }}</span>
            </div>
          </div>
        </section>

        <!-- 右：实时告警滚动 -->
        <section class="panel alarm-panel">
          <div class="panel-title">实时告警</div>
          <div class="alarm-list">
            <transition-group name="roll">
              <div v-for="a in scrollAlarms" :key="a.id" class="alarm-row">
                <span class="badge" :style="{ background: LEVEL_COLOR[a.level] }">
                  {{ LEVEL_LABEL[a.level] }}
                </span>
                <span class="a-res">{{ a.resource_id }}</span>
                <span class="a-content">{{ a.content }}</span>
                <span class="a-time">{{ formatLocalTime(a.triggered_at) }}</span>
              </div>
            </transition-group>
            <div v-if="scrollAlarms.length === 0" class="empty">暂无活动告警</div>
          </div>
        </section>
      </div>

      <!-- 底：区域状态轮播 -->
      <footer class="bs-footer">
        <div class="panel-title">
          区域状态轮播
          <span class="page-dots">
            <i
              v-for="(_, i) in areaPages"
              :key="i"
              :class="{ active: i === areaPage % areaPages.length }"
            />
          </span>
        </div>
        <transition name="fade" mode="out-in">
          <div class="area-row" :key="areaPage % areaPages.length">
            <div
              v-for="a in currentAreaPage"
              :key="a.resource_id"
              class="area-card"
              :class="{ alarming: a.active_alarms > 0 }"
            >
              <div class="area-name">{{ a.alias || a.name }}</div>
              <div class="area-stat">
                <template v-if="a.active_alarms > 0">
                  <span class="area-count" :style="{ color: LEVEL_COLOR[a.max_level || 5] }">
                    {{ a.active_alarms }}
                  </span>
                  <span class="area-tag">告警 · 最高{{ LEVEL_LABEL[a.max_level || 5] }}</span>
                </template>
                <span v-else class="area-ok">正常</span>
              </div>
            </div>
          </div>
        </transition>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.screen-root {
  position: fixed;
  inset: 0;
  background: #0a0f1f;
  overflow: hidden;
}
.screen {
  position: absolute;
  top: 50%;
  left: 50%;
  transform-origin: center center;
  color: #e2e8f0;
  background: radial-gradient(circle at 50% 0%, #122042 0%, #0a0f1f 60%);
  display: flex;
  flex-direction: column;
  padding: 20px 24px;
  box-sizing: border-box;
}
.bs-header {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 64px;
  border-bottom: 2px solid #1e3a8a55;
  margin-bottom: 16px;
}
.bs-header h1 {
  flex: 1;
  text-align: center;
  font-size: 38px;
  letter-spacing: 4px;
  margin: 0;
  color: #fff;
  text-shadow: 0 0 16px #2563eb88;
}
.clock {
  font-size: 24px;
  font-variant-numeric: tabular-nums;
  color: #93c5fd;
}
.exit-btn {
  margin-left: 8px;
}
.dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #475569;
}
.dot.on {
  background: #22c55e;
  box-shadow: 0 0 12px #22c55e;
}
.bs-body {
  flex: 1;
  display: grid;
  grid-template-columns: 380px 1fr 460px;
  gap: 16px;
  min-height: 0;
}
.panel {
  background: #0f1c3a99;
  border: 1px solid #1e3a8a55;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.panel-title {
  font-size: 20px;
  font-weight: 600;
  color: #93c5fd;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.total-card {
  text-align: center;
  padding: 12px 0 18px;
}
.total-num {
  font-size: 80px;
  font-weight: 800;
  line-height: 1;
  color: #f8fafc;
  text-shadow: 0 0 20px #3b82f6aa;
}
.total-label {
  color: #94a3b8;
  margin-top: 8px;
  font-size: 18px;
}
.level-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.level-card {
  background: #0b1530;
  border: 1px solid #1e293b;
  border-radius: 6px;
  text-align: center;
  padding: 14px 0;
}
.level-num {
  font-size: 44px;
  font-weight: 800;
  line-height: 1;
}
.level-label {
  color: #cbd5e1;
  margin-top: 6px;
  font-size: 17px;
}
.chart-panel {
  min-width: 0;
}
.chart {
  flex: 1;
  min-height: 0;
}
.kp-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
}
.kp {
  background: #0b1530;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 6px 12px;
  display: flex;
  gap: 8px;
  align-items: baseline;
}
.kp-name {
  color: #94a3b8;
  font-size: 16px;
}
.kp-val {
  font-size: 20px;
  font-weight: 700;
  color: #38bdf8;
}
.alarm-panel {
  min-width: 0;
}
.alarm-list {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.alarm-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #0b1530;
  border-left: 4px solid #1e293b;
  border-radius: 4px;
  padding: 9px 12px;
  font-size: 17px;
}
.badge {
  color: #fff;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 15px;
  flex-shrink: 0;
}
.a-res {
  color: #e2e8f0;
  width: 150px;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.a-content {
  flex: 1;
  color: #cbd5e1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.a-time {
  color: #64748b;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.empty {
  color: #64748b;
  text-align: center;
  margin-top: 40px;
  font-size: 18px;
}
.bs-footer {
  height: 200px;
  margin-top: 16px;
  background: #0f1c3a99;
  border: 1px solid #1e3a8a55;
  border-radius: 8px;
  padding: 12px 16px;
}
.page-dots {
  display: flex;
  gap: 6px;
}
.page-dots i {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #334155;
}
.page-dots i.active {
  background: #3b82f6;
}
.area-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.area-card {
  background: #0b1530;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 16px;
  height: 110px;
  box-sizing: border-box;
}
.area-card.alarming {
  border-color: #ff4d4f88;
  box-shadow: 0 0 16px #ff4d4f33 inset;
}
.area-name {
  font-size: 20px;
  color: #e2e8f0;
  margin-bottom: 14px;
}
.area-count {
  font-size: 40px;
  font-weight: 800;
}
.area-tag {
  color: #94a3b8;
  margin-left: 8px;
  font-size: 16px;
}
.area-ok {
  color: #22c55e;
  font-size: 24px;
  font-weight: 700;
}
.roll-move {
  transition: transform 0.6s ease;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.4s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
