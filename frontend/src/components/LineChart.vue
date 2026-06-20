<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

export interface Series {
  name: string
  // [timestampMs, value]
  data: [number, number | null][]
}

const props = defineProps<{ series: Series[]; height?: string; yUnit?: string }>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render(): void {
  if (!chart) return
  chart.setOption(
    {
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', top: 0 },
      grid: { left: 50, right: 20, top: 36, bottom: 40 },
      xAxis: { type: 'time' },
      yAxis: { type: 'value', name: props.yUnit || '' },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 8 }],
      series: props.series.map((s) => ({
        name: s.name,
        type: 'line',
        showSymbol: false,
        connectNulls: false,
        data: s.data,
      })),
    },
    true,
  )
}

function resize(): void {
  chart?.resize()
}

onMounted(() => {
  if (el.value) {
    chart = echarts.init(el.value)
    render()
    window.addEventListener('resize', resize)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})

watch(() => props.series, render, { deep: true })
</script>

<template>
  <div ref="el" :style="{ width: '100%', height: height || '320px' }" />
</template>
