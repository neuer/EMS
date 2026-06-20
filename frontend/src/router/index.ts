import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useAuthStore } from '@/store/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
  // NOC 值班大屏：独立全屏路由，不套用主布局
  { path: '/bigscreen', name: 'bigscreen', component: () => import('@/views/BigScreen.vue') },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue') },
      { path: 'topology', name: 'topology', component: () => import('@/views/Topology.vue') },
      { path: 'devices', name: 'devices', component: () => import('@/views/Devices.vue') },
      {
        path: 'points/:id',
        name: 'point-detail',
        component: () => import('@/views/PointDetail.vue'),
      },
      { path: 'trend', name: 'trend', component: () => import('@/views/Trend.vue') },
      { path: 'alarms', name: 'alarms', component: () => import('@/views/Alarms.vue') },
      { path: 'reports', name: 'reports', component: () => import('@/views/Reports.vue') },
      { path: 'metadata', name: 'metadata', component: () => import('@/views/Metadata.vue') },
      // 系统设置：按角色守卫（meta.role 为所需最低角色）
      {
        path: 'settings/ems',
        name: 'settings-ems',
        meta: { role: 'admin' },
        component: () => import('@/views/settings/Ems.vue'),
      },
      {
        path: 'settings/rules',
        name: 'settings-rules',
        meta: { role: 'admin' },
        component: () => import('@/views/settings/Rules.vue'),
      },
      {
        path: 'settings/notify',
        name: 'settings-notify',
        meta: { role: 'admin' },
        component: () => import('@/views/settings/Notify.vue'),
      },
      {
        path: 'settings/suppress',
        name: 'settings-suppress',
        meta: { role: 'operator' },
        component: () => import('@/views/settings/Suppress.vue'),
      },
      {
        path: 'settings/users',
        name: 'settings-users',
        meta: { role: 'admin' },
        component: () => import('@/views/settings/Users.vue'),
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳登录页；并按 meta.role 做角色级访问控制（后端仍强制校验）
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.token) {
    return { name: 'login' }
  }
  if (to.name === 'login' && auth.token) {
    return { name: 'dashboard' }
  }
  const required = to.meta.role as string | undefined
  if (required && !auth.roleSatisfies(required)) {
    // 权限不足：回退到大盘，不进入受限页面
    return { name: 'dashboard' }
  }
  return true
})
