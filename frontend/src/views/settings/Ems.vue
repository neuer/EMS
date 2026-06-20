<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { fetchEmsConfig, fetchEmsStatus, updateEmsConfig } from '@/api/settings'
import type { EmsStatus } from '@/api/types'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const saving = ref(false)
const status = ref<EmsStatus | null>(null)

// 密码：占位符表示「不修改」，仅在用户输入新值时才提交
const form = reactive({
  base_url: '',
  username: '',
  password: '',
  recv_ip: '',
  recv_port: '',
  version_str: '',
  sync_interval_s: 21600,
  subscribe_data: true,
  subscribe_alarm: true,
  deadband_enabled: false,
})

async function loadConfig(): Promise<void> {
  const cfg = await fetchEmsConfig()
  form.base_url = cfg.base_url
  form.username = cfg.username
  form.password = '' // 不回显明文/掩码，留空即不修改
  form.recv_ip = cfg.recv_ip
  form.recv_port = cfg.recv_port
  form.version_str = cfg.version_str
  form.sync_interval_s = cfg.sync_interval_s
  form.subscribe_data = cfg.subscribe_data
  form.subscribe_alarm = cfg.subscribe_alarm
  form.deadband_enabled = cfg.deadband_enabled
}

async function loadStatus(): Promise<void> {
  status.value = await fetchEmsStatus()
}

function fmt(ts: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleString() : '—'
}

async function save(): Promise<void> {
  saving.value = true
  try {
    await updateEmsConfig({
      base_url: form.base_url,
      username: form.username,
      password: form.password || undefined, // 留空不修改
      recv_ip: form.recv_ip,
      recv_port: form.recv_port,
      version_str: form.version_str,
      sync_interval_s: form.sync_interval_s,
      subscribe_data: form.subscribe_data,
      subscribe_alarm: form.subscribe_alarm,
      deadband_enabled: form.deadband_enabled,
    })
    ElMessage.success('配置已保存，连接管理已按新配置重启')
    form.password = ''
    await loadStatus()
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
  loadStatus()
})
</script>

<template>
  <div class="grid">
    <el-card shadow="never">
      <template #header>EMS 连接配置</template>
      <el-form label-width="130px" :disabled="!auth.isAdmin">
        <el-form-item label="EMS 地址">
          <el-input v-model="form.base_url" placeholder="http://ems-host:port" />
        </el-form-item>
        <el-form-item label="账号"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="留空则不修改；填写则加密更新"
          />
        </el-form-item>
        <el-form-item label="平台接收 IP">
          <el-input v-model="form.recv_ip" placeholder="EMS 推送目标 IP" />
        </el-form-item>
        <el-form-item label="平台接收端口">
          <el-input v-model="form.recv_port" />
        </el-form-item>
        <el-form-item label="协议版本号"><el-input v-model="form.version_str" /></el-form-item>
        <el-form-item label="同步周期(秒)">
          <el-input-number v-model="form.sync_interval_s" :min="60" :step="60" />
        </el-form-item>
        <el-form-item label="订阅实时数据">
          <el-switch v-model="form.subscribe_data" />
        </el-form-item>
        <el-form-item label="订阅告警">
          <el-switch v-model="form.subscribe_alarm" />
        </el-form-item>
        <el-form-item label="死区存储">
          <el-switch v-model="form.deadband_enabled" />
          <span class="hint">开启后模拟量仅在超死区阈值时落原始层</span>
        </el-form-item>
        <el-form-item v-if="auth.isAdmin">
          <el-button type="primary" :loading="saving" @click="save">保存并生效</el-button>
        </el-form-item>
        <el-alert
          v-else
          type="info"
          :closable="false"
          title="当前角色为只读/操作员，仅管理员可修改 EMS 连接配置"
        />
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="hd">
          <span>连接状态</span>
          <el-button size="small" text @click="loadStatus">刷新</el-button>
        </div>
      </template>
      <el-descriptions v-if="status" :column="1" border size="small">
        <el-descriptions-item label="连接状态">
          <el-tag :type="status.state === 'online' ? 'success' : 'danger'">
            {{ status.state }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="Token 有效">
          <el-tag :type="status.token_ok ? 'success' : 'info'">
            {{ status.token_ok ? '有效' : '无效' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="最近心跳">{{ fmt(status.last_heart) }}</el-descriptions-item>
        <el-descriptions-item label="最近推送">{{ fmt(status.last_push) }}</el-descriptions-item>
        <el-descriptions-item label="累计重连次数">{{ status.reconnects }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
}
@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
.hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hint {
  margin-left: 10px;
  color: #9ca3af;
  font-size: 12px;
}
</style>
