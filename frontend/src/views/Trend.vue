<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

import { queryHistory, searchPoints } from '@/api/history'
import type { HistoryResult, PointItem } from '@/api/types'
import LineChart, { type Series } from '@/components/LineChart.vue'

const keyword = ref('')
const candidates = ref<PointItem[]>([])
const selected = ref<PointItem[]>([])
const agg = ref<'auto' | 'raw' | '5min'>('auto')
const rangeSec = ref(3600)
const layer = ref('')
const series = ref<Series[]>([])
let lastResult: HistoryResult | null = null

const ranges = [
  { label: '近1时', v: 3600 },
  { label: '近6时', v: 21600 },
  { label: '近24时', v: 86400 },
  { label: '近7天', v: 604800 },
  { label: '近30天', v: 2592000 },
]

async function doSearch(): Promise<void> {
  if (!keyword.value) return
  candidates.value = await searchPoints(keyword.value)
}

function addPoint(p: PointItem): void {
  if (!selected.value.find((x) => x.resource_id === p.resource_id)) {
    selected.value.push(p)
  }
}

function removePoint(id: string): void {
  selected.value = selected.value.filter((x) => x.resource_id !== id)
}

async function runQuery(): Promise<void> {
  if (selected.value.length === 0) {
    ElMessage.warning('请先选择测点')
    return
  }
  const now = Math.floor(Date.now() / 1000)
  const res = await queryHistory({
    point_ids: selected.value.map((p) => p.resource_id),
    start: now - rangeSec.value,
    end: now,
    agg: agg.value,
  })
  lastResult = res
  layer.value = res.layer
  const nameOf = (id: string) => selected.value.find((p) => p.resource_id === id)?.name || id
  series.value = res.series.map((s) => ({
    name: nameOf(s.point_id),
    data:
      res.layer === 'raw'
        ? (s.raw || []).map((p) => [p.ts * 1000, p.value] as [number, number | null])
        : (s.agg || []).map((p) => [p.ts * 1000, p.avg] as [number, number | null]),
  }))
}

function exportCsv(): void {
  if (!lastResult) {
    ElMessage.warning('请先查询')
    return
  }
  const rows: string[] = ['point_id,time,value']
  for (const s of lastResult.series) {
    if (lastResult.layer === 'raw') {
      for (const p of s.raw || [])
        rows.push(`${s.point_id},${new Date(p.ts * 1000).toISOString()},${p.value ?? ''}`)
    } else {
      for (const p of s.agg || [])
        rows.push(`${s.point_id},${new Date(p.ts * 1000).toISOString()},${p.avg ?? ''}`)
    }
  }
  const blob = new Blob([`﻿${rows.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `trend_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <el-card shadow="never">
    <template #header>历史趋势查询</template>
    <div class="picker">
      <el-input
        v-model="keyword"
        placeholder="搜索测点加入对比"
        style="width: 240px"
        @keyup.enter="doSearch"
      />
      <el-button @click="doSearch">搜索</el-button>
      <el-select
        placeholder="选择加入"
        style="width: 240px"
        @change="(id: string) => { const p = candidates.find(c => c.resource_id === id); if (p) addPoint(p) }"
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
        v-for="p in selected"
        :key="p.resource_id"
        closable
        style="margin-right: 6px"
        @close="removePoint(p.resource_id)"
      >
        {{ p.name }}
      </el-tag>
      <span v-if="selected.length === 0" class="hint">未选择测点</span>
    </div>

    <div class="controls">
      <el-radio-group v-model="rangeSec" size="small">
        <el-radio-button v-for="r in ranges" :key="r.v" :value="r.v">{{ r.label }}</el-radio-button>
      </el-radio-group>
      <el-select v-model="agg" size="small" style="width: 120px">
        <el-option label="自动选层" value="auto" />
        <el-option label="原始层" value="raw" />
        <el-option label="5min聚合" value="5min" />
      </el-select>
      <el-button type="primary" size="small" @click="runQuery">查询</el-button>
      <el-button size="small" @click="exportCsv">导出 CSV</el-button>
      <el-tag v-if="layer" size="small">命中层：{{ layer }}</el-tag>
    </div>

    <LineChart :series="series" height="420px" />
  </el-card>
</template>

<style scoped>
.picker {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.selected {
  margin-bottom: 10px;
  min-height: 28px;
}
.hint {
  color: #9ca3af;
}
.controls {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}
</style>
