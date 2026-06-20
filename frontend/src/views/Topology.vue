<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchSpaceChildren, fetchSpaceTree } from '@/api/assets'
import type { DeviceItem, SpaceNode } from '@/api/types'
import { LEVEL_LABEL, LEVEL_TAG } from '@/api/types'

const router = useRouter()
const tree = ref<SpaceNode[]>([])
const treeProps = { children: 'children', label: 'name' }
const current = ref<string>('')
const childSpaces = ref<{ resource_id: string; name: string; alias: string | null }[]>([])
const childDevices = ref<DeviceItem[]>([])

async function onNodeClick(node: SpaceNode): Promise<void> {
  current.value = node.alias || node.name
  const res = await fetchSpaceChildren(node.resource_id)
  childSpaces.value = res.spaces
  childDevices.value = res.devices
}

function statusTag(s: number | null): { type: string; text: string } {
  if (s === 0) return { type: 'danger', text: '通信中断' }
  if (s === 1) return { type: 'success', text: '正常' }
  return { type: 'info', text: '未知' }
}

onMounted(async () => {
  tree.value = await fetchSpaceTree()
})
</script>

<template>
  <el-row :gutter="12">
    <el-col :span="9">
      <el-card shadow="never">
        <template #header>空间拓扑（下钻）</template>
        <el-tree
          :data="tree"
          :props="treeProps"
          node-key="resource_id"
          default-expand-all
          highlight-current
          @node-click="onNodeClick"
        >
          <template #default="{ data }">
            <span class="node">
              <span>{{ data.alias || data.name }}</span>
              <el-tag
                v-if="data.active_alarms > 0"
                :type="LEVEL_TAG[data.max_level || 5]"
                size="small"
              >
                {{ data.active_alarms }} · {{ LEVEL_LABEL[data.max_level || 5] }}
              </el-tag>
            </span>
          </template>
        </el-tree>
      </el-card>
    </el-col>
    <el-col :span="15">
      <el-card shadow="never">
        <template #header>{{ current || '选择空间节点查看下属设备' }}</template>
        <div v-if="childSpaces.length">
          <h4>子空间</h4>
          <el-tag v-for="s in childSpaces" :key="s.resource_id" style="margin: 0 6px 6px 0">
            {{ s.alias || s.name }}
          </el-tag>
        </div>
        <h4 v-if="childDevices.length">设备</h4>
        <el-table :data="childDevices" size="small" border>
          <el-table-column prop="name" label="设备" />
          <el-table-column prop="device_type" label="类型" width="120" />
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
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button text size="small" @click="router.push(`/devices?d=${row.resource_id}`)">
                查看测点
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="!childSpaces.length && !childDevices.length"
          description="无下属节点或未选择"
          :image-size="80"
        />
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
.node {
  display: flex;
  align-items: center;
  gap: 8px;
}
h4 {
  margin: 10px 0 6px;
  color: #374151;
}
</style>
