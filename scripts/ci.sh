#!/usr/bin/env bash
# 本地一键质量门禁（与 .github/workflows/ci.yml 对齐）：lint → 类型检查 → 测试。
# 后端测试离线确定性（fakeredis/aiosqlite/respx），无需起 DB/Redis。
# 前置：后端已 `uv venv && uv pip install -r requirements-dev.txt`；前端已 `bun install`。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 后端 1/3：ruff"
(cd "$ROOT/backend" && uv run ruff check .)
echo "==> 后端 2/3：pyright"
(cd "$ROOT/backend" && uv run pyright)
echo "==> 后端 3/3：pytest（离线确定性）"
(cd "$ROOT/backend" && uv run pytest)

echo "==> 前端 1/2：biome（lint + 格式校验）"
(cd "$ROOT/frontend" && bun run lint)
echo "==> 前端 2/2：vue-tsc（类型检查）"
(cd "$ROOT/frontend" && bun x vue-tsc --noEmit)

echo "==> 全部质量门禁通过 ✅"
