import axios, { type AxiosInstance } from 'axios'

import { useAuthStore } from '@/store/auth'

// 平台 API 统一前缀与响应包络 {code,msg,data}
export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T
}

export const http: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// 401 统一登出并跳登录
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error?.response?.status === 401) {
      const auth = useAuthStore()
      auth.clear()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export async function getJson<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const resp = await http.get<ApiEnvelope<T>>(url, { params })
  return resp.data.data
}

export async function postJson<T>(url: string, body?: unknown): Promise<T> {
  const resp = await http.post<ApiEnvelope<T>>(url, body)
  return resp.data.data
}

export async function putJson<T>(url: string, body?: unknown): Promise<T> {
  const resp = await http.put<ApiEnvelope<T>>(url, body)
  return resp.data.data
}

export async function deleteJson<T>(url: string): Promise<T> {
  const resp = await http.delete<ApiEnvelope<T>>(url)
  return resp.data.data
}
