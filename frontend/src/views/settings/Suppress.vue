<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createMute,
  createWindow,
  deleteWindow,
  disableMute,
  listMutes,
  listWindows,
} from '@/api/suppress'
import type { MaintenanceWindow, PointMute } from '@/api/types'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const windows = ref<MaintenanceWindow[]>([])
const mutes = ref<PointMute[]>([])

const SCOPE_LABEL: Record<number, string> = { 5: '空间', 2: '设备', 3: '测点' }

// 维护窗口
const winDialog = ref(false)
const winForm = reactive({
  name: '',
  scope_kind: 3,
  scope_ids_text: '',
  range: [] as string[],
  record_silenced: true,
})

// 测点屏蔽
const muteDialog = ref(false)
const muteForm = reactive({ point_id: '', reason: '', range: [] as string[] })

async function load(): Promise<void> {
  windows.value = await listWindows()
  mutes.value = await listMutes()
}

function openWin(): void {
  Object.assign(winForm, {
    name: '',
    scope_kind: 3,
    scope_ids_text: '',
    range: [],
    record_silenced: true,
  })
  winDialog.value = true
}

async function saveWin(): Promise<void> {
  const ids = winForm.scope_ids_text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  if (ids.length === 0 || winForm.range.length !== 2) {
    ElMessage.warning('请填写适用范围 ID 与起止时间')
    return
  }
  await createWindow({
    name: winForm.name || null,
    scope_kind: winForm.scope_kind,
    scope_ids: ids,
    start_at: winForm.range[0],
    end_at: winForm.range[1],
    record_silenced: winForm.record_silenced,
  })
  ElMessage.success('维护窗口已创建')
  winDialog.value = false
  load()
}

async function removeWin(w: MaintenanceWindow): Promise<void> {
  await ElMessageBox.confirm('确认删除该维护窗口？', '提示', { type: 'warning' })
  await deleteWindow(w.id)
  ElMessage.success('已删除')
  load()
}

function openMute(): void {
  Object.assign(muteForm, { point_id: '', reason: '', range: [] })
  muteDialog.value = true
}

async function saveMute(): Promise<void> {
  if (!muteForm.point_id) {
    ElMessage.warning('请填写测点 ID')
    return
  }
  await createMute({
    point_id: muteForm.point_id,
    reason: muteForm.reason || null,
    start_at: muteForm.range[0] || null,
    end_at: muteForm.range[1] || null,
  })
  ElMessage.success('屏蔽已创建')
  muteDialog.value = false
  load()
}

async function removeMute(m: PointMute): Promise<void> {
  await ElMessageBox.confirm(`确认解除测点 ${m.point_id} 的屏蔽？`, '提示', { type: 'warning' })
  await disableMute(m.id)
  ElMessage.success('已解除')
  load()
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <el-card shadow="never">
      <template #header>
        <div class="hd">
          <span>维护窗口（静默）</span>
          <el-button v-if="auth.canWrite" type="primary" size="small" @click="openWin">
            新建维护窗口
          </el-button>
        </div>
      </template>
      <el-table :data="windows" size="small" border>
        <el-table-column prop="name" label="名称" />
        <el-table-column label="范围" width="90">
          <template #default="{ row }">{{ SCOPE_LABEL[row.scope_kind] || row.scope_kind }}</template>
        </el-table-column>
        <el-table-column label="对象" min-width="160">
          <template #default="{ row }">{{ row.scope_ids.join(', ') }}</template>
        </el-table-column>
        <el-table-column prop="start_at" label="开始" width="180" />
        <el-table-column prop="end_at" label="结束" width="180" />
        <el-table-column label="记录静默告警" width="120">
          <template #default="{ row }">{{ row.record_silenced ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="auth.canWrite"
              text
              size="small"
              type="danger"
              @click="removeWin(row)"
            >
              删除
            </el-button>
            <span v-else class="ro">只读</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="hd">
          <span>测点屏蔽</span>
          <el-button v-if="auth.canWrite" type="primary" size="small" @click="openMute">
            新建屏蔽
          </el-button>
        </div>
      </template>
      <el-table :data="mutes" size="small" border>
        <el-table-column prop="point_id" label="测点 ID" width="160" />
        <el-table-column prop="reason" label="原因" />
        <el-table-column prop="start_at" label="开始" width="180" />
        <el-table-column label="结束" width="180">
          <template #default="{ row }">{{ row.end_at || '长期' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="auth.canWrite"
              text
              size="small"
              type="danger"
              @click="removeMute(row)"
            >
              解除
            </el-button>
            <span v-else class="ro">只读</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="winDialog" title="新建维护窗口" width="520px">
      <el-form label-width="110px">
        <el-form-item label="名称"><el-input v-model="winForm.name" /></el-form-item>
        <el-form-item label="适用范围">
          <el-select v-model="winForm.scope_kind" style="width: 160px">
            <el-option :value="5" label="空间" />
            <el-option :value="2" label="设备" />
            <el-option :value="3" label="测点" />
          </el-select>
        </el-form-item>
        <el-form-item label="对象 ID">
          <el-input v-model="winForm.scope_ids_text" placeholder="逗号分隔的 resource_id" />
        </el-form-item>
        <el-form-item label="起止时间">
          <el-date-picker
            v-model="winForm.range"
            type="datetimerange"
            value-format="YYYY-MM-DDTHH:mm:ss"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
          />
        </el-form-item>
        <el-form-item label="记录静默告警">
          <el-switch v-model="winForm.record_silenced" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="winDialog = false">取消</el-button>
        <el-button type="primary" @click="saveWin">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="muteDialog" title="新建测点屏蔽" width="480px">
      <el-form label-width="110px">
        <el-form-item label="测点 ID"><el-input v-model="muteForm.point_id" /></el-form-item>
        <el-form-item label="原因"><el-input v-model="muteForm.reason" /></el-form-item>
        <el-form-item label="起止时间">
          <el-date-picker
            v-model="muteForm.range"
            type="datetimerange"
            value-format="YYYY-MM-DDTHH:mm:ss"
            range-separator="至"
            start-placeholder="开始(可空)"
            end-placeholder="结束(空=长期)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="muteDialog = false">取消</el-button>
        <el-button type="primary" @click="saveMute">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ro {
  color: #9ca3af;
}
</style>
