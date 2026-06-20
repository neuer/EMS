#!/usr/bin/env bash
# 动环监控预警平台 — 数据库备份脚本（PostgreSQL + TimescaleDB）
#
# 用法：
#   scripts/backup.sh                 # 备份到 ./backups/，自定义格式(-Fc)，保留 14 天
#   BACKUP_DIR=/data/bk RETENTION_DAYS=30 scripts/backup.sh
#
# 说明：
# - 使用 docker compose exec 在 db 容器内执行 pg_dump，无需在宿主机安装 pg 客户端。
# - 默认 custom 格式（-Fc），便于 pg_restore 选择性恢复；同时生成校验文件。
# - 仅只读导出，不改动数据库；可安全在生产低峰期定时执行（见 README/恢复文档）。
set -euo pipefail

cd "$(dirname "$0")/.."

# 读取 .env（若存在）以获取数据库账号
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PGUSER="${POSTGRES_USER:-dcim}"
PGDB="${POSTGRES_DB:-dcim}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/dcim_${TS}.dump"

mkdir -p "${BACKUP_DIR}"

echo "[backup] 开始备份 数据库=${PGDB} 用户=${PGUSER} -> ${OUT}"
# -Fc 自定义格式；输出到宿主机文件
docker compose exec -T db pg_dump -U "${PGUSER}" -d "${PGDB}" -Fc > "${OUT}"

# 体积与校验（在备份目录内以 basename 生成，便于 restore 用 -c 校验）
SIZE="$(du -h "${OUT}" | cut -f1)"
BASE="$(basename "${OUT}")"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "${BACKUP_DIR}" && sha256sum "${BASE}" > "${BASE}.sha256")
elif command -v shasum >/dev/null 2>&1; then
  (cd "${BACKUP_DIR}" && shasum -a 256 "${BASE}" > "${BASE}.sha256")
fi
echo "[backup] 完成：${OUT}（${SIZE}）"

# 清理过期备份
echo "[backup] 清理超过 ${RETENTION_DAYS} 天的旧备份"
find "${BACKUP_DIR}" -name 'dcim_*.dump' -type f -mtime "+${RETENTION_DAYS}" -print -delete || true
find "${BACKUP_DIR}" -name 'dcim_*.dump.sha256' -type f -mtime "+${RETENTION_DAYS}" -delete || true

echo "[backup] OK"
