<!-- 遵循 CLAUDE.md 全局规范 §21。请如实填写，CI 两个必需检查须为绿方可合并。 -->

## Summary / 变更摘要
<!-- 改了什么、为什么。关联 issue：Closes #xxx -->

## Contract / 契约
<!-- 是否改动对外 API / OpenAPI / 前端 client？是→附 OpenAPI Diff 结论摘要；否→写“无契约变更”。 -->
- [ ] 无契约变更
- [ ] 有契约变更（已重新生成 client，附 Diff 结论）

## Tests / 测试
<!-- 新增/修改的用例，覆盖了哪些路径（成功 + 结构化错误）。LLM 相关须有回放测试。 -->

## Migration / 迁移
- [ ] 无 DB 迁移
- [ ] 含 Alembic 迁移（含 downgrade，已说明回滚成本/兼容窗口）

## Checklist / 自测
- [ ] 本地 `make ci` 全绿（后端 ruff/pyright/pytest + 前端 biome/vue-tsc）
- [ ] 未触碰红线（无 `setting`/`set_event_rules`；推送 ack 格式不变；历史接口 ≤100 点/≤1 天/串行）
- [ ] 无明文凭据/敏感信息入库或日志；新增外部 HTTP 配了 connect/read 超时
- [ ] 可观测性满足（request_id 贯穿、关键失败有指标）
- [ ] 未提交 `.env` 或任何真实密钥

## Compliance / 合规检查（§24，按实际改动填写）
```json
{
  "contract_changed": false,
  "openapi_updated": false,
  "client_regenerated": false,
  "zod_extended_via_wrapper": "NA",
  "cross_feature_import_checked": true,
  "tests_added_or_updated": true,
  "llm_replay_test_present": "NA",
  "migration_required": false,
  "rollback_plan_present": "NA",
  "security_sensitive": false,
  "observability_updated": "NA",
  "exceptions": []
}
```

## Exceptions / 例外（§23）
<!-- 若打破规则：给编号 EXC-YYYYMMDD-NNN、位置、理由、到期/移除计划；无则写“无”。 -->
无
