#!/usr/bin/env bash
# 动环监控预警平台 — 数据库恢复脚本（TimescaleDB 专用流程，与 backup.sh 配套）
#
# 用法：
#   scripts/restore.sh ./backups/dcim_20260620_010000.dump
#
# TimescaleDB 逻辑恢复必须遵循官方流程，否则 hypertable / 连续聚合会损坏：
#   1) 重建空库 → 2) CREATE EXTENSION timescaledb → 3) timescaledb_pre_restore()
#   → 4) pg_restore → 5) timescaledb_post_restore()
#
# 风险提示（务必先阅读 docs/运维-备份与恢复.md）：
# - 恢复会「删除并重建」目标库，属高风险操作。
# - 默认需要交互确认；设置 FORCE=1 可跳过确认（仅限自动化演练环境）。
set -euo pipefail

cd "$(dirname "$0")/.."

DUMP="${1:-}"
if [[ -z "${DUMP}" || ! -f "${DUMP}" ]]; then
  echo "用法: scripts/restore.sh <备份文件.dump>" >&2
  exit 2
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
PGUSER="${POSTGRES_USER:-dcim}"
PGDB="${POSTGRES_DB:-dcim}"

# 校验完整性（若有 sha256 旁文件）
if [[ -f "${DUMP}.sha256" ]]; then
  echo "[restore] 校验文件完整性…"
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "${DUMP}")" && sha256sum -c "$(basename "${DUMP}").sha256")
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$(dirname "${DUMP}")" && shasum -a 256 -c "$(basename "${DUMP}").sha256")
  fi
fi

echo "[restore] 目标库=${PGDB} 用户=${PGUSER} 来源=${DUMP}"
if [[ "${FORCE:-0}" != "1" ]]; then
  read -r -p "此操作将删除并重建目标库，确认恢复？(yes/N) " ans
  [[ "${ans}" == "yes" ]] || { echo "已取消"; exit 1; }
fi

echo "[restore] 停止 backend 以释放连接…"
docker compose stop backend || true

dexec() { docker compose exec -T db "$@"; }

echo "[restore] 终止残留连接并重建空库…"
dexec psql -U "${PGUSER}" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = '${PGDB}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${PGDB};
CREATE DATABASE ${PGDB} OWNER ${PGUSER};
SQL

echo "[restore] 创建扩展并进入 pre_restore 模式…"
dexec psql -U "${PGUSER}" -d "${PGDB}" -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS timescaledb;" \
  -c "SELECT timescaledb_pre_restore();"

echo "[restore] 执行 pg_restore…（dump 中的 CREATE EXTENSION 重复声明会被忽略）"
# pre_restore 期间不使用 ON_ERROR_STOP：扩展已存在等无害提示不应中断恢复
dexec pg_restore -U "${PGUSER}" -d "${PGDB}" --no-owner < "${DUMP}" || true

echo "[restore] 退出 post_restore 模式（重建连续聚合/策略状态）…"
dexec psql -U "${PGUSER}" -d "${PGDB}" -v ON_ERROR_STOP=1 \
  -c "SELECT timescaledb_post_restore();"

echo "[restore] 重新启动 backend…"
docker compose start backend

echo "[restore] OK，请登录平台核对数据并检查 EMS 连接状态。"
