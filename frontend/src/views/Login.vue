<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { postJson } from '@/api/http'
import { useAuthStore } from '@/store/auth'

interface TokenResp {
  access_token: string
  token_type: string
  role: string
  username: string
}

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ username: 'admin', password: 'admin123' })

async function onSubmit(): Promise<void> {
  loading.value = true
  try {
    const data = await postJson<TokenResp>('/auth/login', {
      username: form.username,
      password: form.password,
    })
    auth.setAuth({ token: data.access_token, username: data.username, role: data.role })
    ElMessage.success('登录成功')
    await router.push('/dashboard')
  } catch {
    ElMessage.error('登录失败：用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2>动环监控预警平台</h2>
      <el-form label-width="64px" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-button type="primary" :loading="loading" @click="onSubmit">登录</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
}
.login-card {
  width: 360px;
}
</style>
