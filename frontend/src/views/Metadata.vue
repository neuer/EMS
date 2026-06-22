<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { fetchDevices, fetchMeta, fetchPoints, saveMeta } from '@/api/assets'
import type { DeviceItem, PointItem } from '@/api/types'
import { handleErr } from '@/lib/errors'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const kind = ref<'point' | 'device'>('point')
const keyword = ref('')
const rows = ref<(PointItem | DeviceItem)[]>([])

const dialog = ref(false)
const editing = ref('')
const form = reactive({
  alias: '',
  group_name: '',
  tagsText: '',
  importance: undefined as number | undefined,
  custom_unit: '',
  remark: '',
})

async function load(): Promise<void> {
  const params = { keyword: keyword.value || undefined }
  rows.value =
    kind.value === 'point' ? await fetchPoints(params) : await fetchDevices(params)
}

async function openEdit(id: string): Promise<void> {
  editing.value = id
  const m = await fetchMeta(id)
  form.alias = m?.alias || ''
  form.group_name = m?.group_name || ''
  form.tagsText = (m?.tags || []).join(',')
  form.importance = m?.importance ?? undefined
  form.custom_unit = m?.custom_unit || ''
  form.remark = m?.remark || ''
  dialog.value = true
}

async function save(): Promise<void> {
  try {
    await saveMeta(editing.value, {
      alias: form.alias || null,
      group_name: form.group_name || null,
      tags: form.tagsText ? form.tagsText.split(',').map((s) => s.trim()).filter(Boolean) : null,
      importance: form.importance ?? null,
      custom_unit: form.custom_unit || null,
      remark: form.remark || null,
    })
    ElMessage.success('元数据已保存')
    dialog.value = false
    load()
  } catch (e) {
    handleErr(e)
  }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>元数据增强管理</template>
    <div class="bar">
      <el-radio-group v-model="kind" @change="load">
        <el-radio-button value="point">测点</el-radio-button>
        <el-radio-button value="device">设备</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="keyword"
        placeholder="按名称/ID 搜索"
        clearable
        style="width: 240px"
        @keyup.enter="load"
        @clear="load"
      />
      <el-button type="primary" @click="load">搜索</el-button>
    </div>

    <el-table :data="rows" size="small" border>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="resource_id" label="ID" width="160" />
      <el-table-column prop="alias" label="别名" width="140" />
      <el-table-column prop="group_name" label="分组" width="120" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button
            v-if="auth.canWrite"
            text
            size="small"
            @click="openEdit(row.resource_id)"
          >
            编辑
          </el-button>
          <span v-else class="ro">只读</span>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="编辑元数据增强" width="480px">
      <el-form label-width="80px">
        <el-form-item label="别名"><el-input v-model="form.alias" /></el-form-item>
        <el-form-item label="分组"><el-input v-model="form.group_name" /></el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tagsText" placeholder="逗号分隔，如 核心,温度" />
        </el-form-item>
        <el-form-item label="重要度">
          <el-select v-model="form.importance" clearable style="width: 160px">
            <el-option v-for="i in [1, 2, 3, 4, 5]" :key="i" :label="`重要度 ${i}`" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item label="自定义单位"><el-input v-model="form.custom_unit" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}
.ro {
  color: #9ca3af;
}
</style>
