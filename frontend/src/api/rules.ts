import { deleteJson, getJson, postJson, putJson } from '@/api/http'
import type { Rule } from '@/api/types'

export function listRules(point_id?: string): Promise<Rule[]> {
  return getJson('/rules', point_id ? { point_id } : undefined)
}

export type RuleInput = Omit<Rule, 'id'>

export function createRule(body: RuleInput): Promise<Rule> {
  return postJson('/rules', body)
}

export function updateRule(id: number, body: Partial<RuleInput>): Promise<Rule> {
  return putJson(`/rules/${id}`, body)
}

export function deleteRule(id: number): Promise<{ deleted: number }> {
  return deleteJson(`/rules/${id}`)
}
