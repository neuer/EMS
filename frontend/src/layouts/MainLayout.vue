<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const activeMenu = computed(() => route.path)

// 响应式：窄屏（手机/平板竖屏）折叠为抽屉菜单
const isMobile = ref(false)
const drawer = ref(false)
function onResize(): void {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) drawer.value = false
}
onMounted(() => {
  onResize()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => window.removeEventListener('resize', onResize))

const menus = [
  { path: '/dashboard', title: '监控大盘' },
  { path: '/topology', title: '空间拓扑' },
  { path: '/devices', title: '设备/测点' },
  { path: '/trend', title: '历史趋势' },
  { path: '/alarms', title: '告警中心' },
  { path: '/reports', title: '报表中心' },
  { path: '/metadata', title: '元数据管理' },
]

// 系统设置子菜单：按角色过滤（readonly 不可见任何设置项；operator 仅抑制；admin 全部）
const settingsMenus = computed(() =>
  [
    { path: '/settings/ems', title: 'EMS 连接', role: 'admin' },
    { path: '/settings/rules', title: '规则管理', role: 'admin' },
    { path: '/settings/notify', title: '通知配置', role: 'admin' },
    { path: '/settings/suppress', title: '维护/屏蔽', role: 'operator' },
    { path: '/settings/users', title: '用户管理', role: 'admin' },
  ].filter((m) => auth.roleSatisfies(m.role)),
)

const roleLabel = computed(
  () => ({ admin: '管理员', operator: '操作员', readonly: '只读' })[auth.role] || auth.role,
)

function go(path: string): void {
  router.push(path)
  drawer.value = false
}

function logout(): void {
  auth.clear()
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <!-- 桌面端固定侧栏 -->
    <el-aside v-if="!isMobile" width="200px" class="aside">
      <div class="logo">动环监控预警</div>
      <el-menu :default-active="activeMenu" router class="menu">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <span>{{ m.title }}</span>
        </el-menu-item>
        <el-sub-menu v-if="settingsMenus.length" index="settings" class="sub">
          <template #title>系统设置</template>
          <el-menu-item v-for="s in settingsMenus" :key="s.path" :index="s.path">
            <span>{{ s.title }}</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="left">
          <el-button
            v-if="isMobile"
            class="hamburger"
            text
            size="large"
            @click="drawer = true"
          >
            ☰
          </el-button>
          <div class="title">{{ isMobile ? '动环监控' : '数据中心动环监控预警平台' }}</div>
        </div>
        <div class="user">
          <el-button size="small" text @click="router.push('/bigscreen')">大屏</el-button>
          <el-tag size="small" type="info">{{ roleLabel }}</el-tag>
          <span v-if="!isMobile" class="uname">{{ auth.username }}</span>
          <el-button size="small" text @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 移动端抽屉菜单 -->
    <el-drawer v-model="drawer" direction="ltr" size="220px" :with-header="false">
      <div class="logo dark">动环监控预警</div>
      <el-menu :default-active="activeMenu" class="menu drawer-menu">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path" @click="go(m.path)">
          <span>{{ m.title }}</span>
        </el-menu-item>
        <el-sub-menu v-if="settingsMenus.length" index="settings">
          <template #title>系统设置</template>
          <el-menu-item
            v-for="s in settingsMenus"
            :key="s.path"
            :index="s.path"
            @click="go(s.path)"
          >
            <span>{{ s.title }}</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
      <div class="drawer-foot">
        <span>{{ auth.username }}（{{ roleLabel }}）</span>
        <el-button size="small" text @click="logout">退出</el-button>
      </div>
    </el-drawer>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #1f2937;
}
.logo {
  color: #fff;
  font-weight: 600;
  text-align: center;
  padding: 18px 0;
  font-size: 16px;
  border-bottom: 1px solid #374151;
}
.logo.dark {
  background: #1f2937;
}
.menu {
  background: #1f2937;
  border-right: none;
}
.menu :deep(.el-menu-item),
.menu :deep(.el-sub-menu__title) {
  color: #cbd5e1;
}
.menu :deep(.el-sub-menu .el-menu) {
  background: #1a2433;
}
.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: #2563eb;
}
.drawer-menu {
  min-height: calc(100% - 120px);
}
.drawer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  color: #cbd5e1;
  background: #1f2937;
  font-size: 13px;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
}
.left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hamburger {
  font-size: 22px;
  padding: 0 6px;
}
.title {
  font-weight: 600;
  color: #111827;
}
.user {
  display: flex;
  align-items: center;
  gap: 10px;
}
.uname {
  color: #374151;
  font-size: 14px;
}
.main {
  background: #f3f4f6;
}
</style>
