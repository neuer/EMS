<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { createRule, deleteRule, listRules, updateRule, type RuleInput } from '@/api/rules'
import { LEVEL_LABEL, type Rule } from '@/api/types'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const rows = ref<Rule[]>([])
const filterPoint = ref('')
const dialog = ref(false)
const editingId = ref<number | null>(null)

const OPERATORS = ['>', '<', '=', '<>', '<=', '>=']

function emptyForm(): RuleInput {
  return {
    point_id: '',
    name: null,
    enabled: true,
    operator: '>',
    operand: 0,
    operand_min: null,
    operand_max: null,
    cond_type: 'threshold',
    restore_operator: null,
    restore_operand: null,
    continuous_time: 0,
    recover_hold_time: 0,
    level: 3,
    priority: 0,
    content_tpl: null,
    suggest: null,
  }
}
const form = reactive<RuleInput>(emptyForm())

async function load(): Promise<void> {
  rows.value = await listRules(filterPoint.value || undefined)
}

function openCreate(): void {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialog.value = true
}

function openEdit(r: Rule): void {
  editingId.value = r.id
  Object.assign(form, { ...r })
  dialog.value = true
}

async function save(): Promise<void> {
  if (!form.point_id) {
    ElMessage.warning('请填写测点 ID')
    return
  }
  if (editingId.value === null) {
    await createRule({ ...form })
    ElMessage.success('规则已创建')
  } else {
    await updateRule(editingId.value, { ...form })
    ElMessage.success('规则已更新')
  }
  dialog.value = false
  load()
}

async function remove(r: Rule): Promise<void> {
  await ElMessageBox.confirm(`确认删除测点 ${r.point_id} 的规则？`, '提示', { type: 'warning' })
  await deleteRule(r.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="hd">
        <span>预警规则管理</span>
        <el-button v-if="auth.isAdmin" type="primary" size="small" @click="openCreate">
          新建规则
        </el-button>
      </div>
    </template>

    <div class="bar">
      <el-input
        v-model="filterPoint"
        placeholder="按测点 ID 过滤"
        clearable
        style="width: 240px"
        @keyup.enter="load"
        @clear="load"
      />
      <el-button @click="load">查询</el-button>
    </div>

    <el-table :data="rows" size="small" border>
      <el-table-column prop="point_id" label="测点 ID" width="150" />
      <el-table-column prop="name" label="名称" />
      <el-table-column label="条件" min-width="160">
        <template #default="{ row }">
          <span v-if="row.cond_type === 'range'">
            区间 [{{ row.operand_min }}, {{ row.operand_max }}]
          </span>
          <span v-else>{{ row.operator }} {{ row.operand }}</span>
        </template>
      </el-table-column>
      <el-table-column label="级别" width="90">
        <template #default="{ row }">{{ LEVEL_LABEL[row.level] || row.level }}</template>
      </el-table-column>
      <el-table-column label="去抖(s)" prop="continuous_time" width="80" />
      <el-table-column label="启用" width="70">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <template v-if="auth.isAdmin">
            <el-button text size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text size="small" type="danger" @click="remove(row)">删除</el-button>
          </template>
          <span v-else class="ro">只读</span>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialog"
      :title="editingId === null ? '新建规则' : '编辑规则'"
      width="560px"
    >
      <el-form label-width="100px">
        <el-form-item label="测点 ID">
          <el-input v-model="form.point_id" :disabled="editingId !== null" />
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="条件类型">
          <el-radio-group v-model="form.cond_type">
            <el-radio-button value="threshold">阈值</el-radio-button>
            <el-radio-button value="range">区间</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="form.cond_type === 'threshold'">
          <el-form-item label="运算符">
            <el-select v-model="form.operator" style="width: 120px">
              <el-option v-for="op in OPERATORS" :key="op" :label="op" :value="op" />
            </el-select>
          </el-form-item>
          <el-form-item label="阈值">
            <el-input-number v-model="form.operand" :controls="false" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="区间下限">
            <el-input-number v-model="form.operand_min" :controls="false" />
          </el-form-item>
          <el-form-item label="区间上限">
            <el-input-number v-model="form.operand_max" :controls="false" />
          </el-form-item>
        </template>
        <el-form-item label="级别">
          <el-select v-model="form.level" style="width: 160px">
            <el-option
              v-for="i in [1, 2, 3, 4, 5]"
              :key="i"
              :label="LEVEL_LABEL[i]"
              :value="i"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="去抖(秒)">
          <el-input-number v-model="form.continuous_time" :min="0" />
        </el-form-item>
        <el-form-item label="恢复保持(秒)">
          <el-input-number v-model="form.recover_hold_time" :min="0" />
        </el-form-item>
        <el-form-item label="恢复运算符">
          <el-select v-model="form.restore_operator" clearable style="width: 120px">
            <el-option v-for="op in OPERATORS" :key="op" :label="op" :value="op" />
          </el-select>
        </el-form-item>
        <el-form-item label="恢复阈值">
          <el-input-number v-model="form.restore_operand" :controls="false" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
        <el-form-item label="内容模板"><el-input v-model="form.content_tpl" /></el-form-item>
        <el-form-item label="处理建议">
          <el-input v-model="form.suggest" type="textarea" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.bar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.ro {
  color: #9ca3af;
}
</style>
