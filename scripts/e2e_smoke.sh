#!/usr/bin/env bash
# 动环监控预警平台 — 端到端联调冒烟脚本（对 ems_mock）
#
# 作用：一键起栈 → 等后端就绪 → 登录 → 触发同步 → 校验连接状态/资产树/实时值/告警统计。
# 全程只读对接 EMS（经 ems_mock）；用于 Sprint 验收与回归。
#
# 用法：
#   scripts/e2e_smoke.sh            # 起栈并联调
#   NO_UP=1 scripts/e2e_smoke.sh    # 跳过起栈，仅对已运行的栈做冒烟
set -uo pipefail

cd "$(dirname "$0")/.."
if [[ -f .env ]]; then set -a; source .env; set +a; fi

BASE="http://localhost:${BACKEND_PORT:-8000}"
API="${BASE}/api/v1"
ADMIN_U="${DEFAULT_ADMIN_USERNAME:-admin}"
ADMIN_P="${DEFAULT_ADMIN_PASSWORD:-admin123}"

PASS=0
FAIL=0
ok()  { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

# 从 JSON 安全取字段（python3，避免依赖 jq；不使用 eval）。
# 用法：echo "$json" | jget data access_token   # 取 d["data"]["access_token"]
#       echo "$json" | jget data __len__          # 取 len(d["data"])（列表/字典长度）
PYJGET='import sys, json
d = json.load(sys.stdin)
args = sys.argv[1:]
take_len = args and args[-1] == "__len__"
if take_len:
    args = args[:-1]
cur = d
try:
    for a in args:
        cur = cur[int(a)] if isinstance(cur, list) else cur[a]
    print(len(cur) if take_len else cur)
except Exception:
    print("")
'
jget() { python3 -c "$PYJGET" "$@" 2>/dev/null; }

if [[ "${NO_UP:-0}" != "1" ]]; then
  echo "[e2e] 启动 db/redis/backend/ems_mock…"
  docker compose up -d db redis backend ems_mock
fi

echo "[e2e] 等待后端就绪（/health）…"
for _ in $(seq 1 60); do
  if curl -fsS "${BASE}/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "${BASE}/health" >/dev/null 2>&1 && ok "后端健康检查通过" || { bad "后端未就绪"; echo "SUMMARY pass=$PASS fail=$FAIL"; exit 1; }

echo "[e2e] 登录获取 token…"
TOKEN="$(curl -fsS -X POST "${API}/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${ADMIN_U}\",\"password\":\"${ADMIN_P}\"}" | jget data access_token)"
if [[ -n "${TOKEN}" && "${TOKEN}" != "None" ]]; then ok "管理员登录成功"; else bad "登录失败"; fi
AUTH=(-H "Authorization: Bearer ${TOKEN}")

echo "[e2e] 触发配置同步…"
SYNC="$(curl -fsS -X POST "${API}/sync/config" "${AUTH[@]}")"
SPACES="$(echo "${SYNC}" | jget data spaces)"
[[ -n "${SPACES}" && "${SPACES}" != "None" && "${SPACES}" != "0" ]] && ok "同步完成，空间数=${SPACES}" || bad "同步未返回资产（spaces=${SPACES}）"

echo "[e2e] 校验资产树…"
TREE="$(curl -fsS "${API}/tree/spaces" "${AUTH[@]}" | jget data __len__)"
[[ -n "${TREE}" && "${TREE}" != "0" && "${TREE}" != "None" ]] && ok "资产树根节点数=${TREE}" || bad "资产树为空"

echo "[e2e] 校验 EMS 连接状态…"
STATE="$(curl -fsS "${API}/settings/ems/status" "${AUTH[@]}" | jget data state)"
[[ "${STATE}" == "online" ]] && ok "EMS 连接在线" || bad "EMS 状态=${STATE}（期望 online，确认 ems_mock 已启动）"

echo "[e2e] 等待实时推送(约 12s)…"
sleep 12
LAST_PUSH="$(curl -fsS "${API}/settings/ems/status" "${AUTH[@]}" | jget data last_push)"
[[ -n "${LAST_PUSH}" && "${LAST_PUSH}" != "None" && "${LAST_PUSH}" != "" ]] \
  && ok "已收到实时推送（last_push=${LAST_PUSH}）" || bad "未收到实时推送（last_push 为空）"

# 用同步得到的某个测点 id 校验最新值缓存（取 /points 列表第一个）
FIRST_PT="$(curl -fsS "${API}/points" "${AUTH[@]}" | jget data 0 resource_id)"
if [[ -n "${FIRST_PT}" && "${FIRST_PT}" != "None" ]]; then
  PTS="$(curl -fsS "${API}/realtime/points?ids=${FIRST_PT}" "${AUTH[@]}" | jget data __len__)"
  [[ -n "${PTS}" && "${PTS}" != "0" && "${PTS}" != "None" ]] \
    && ok "实时最新值接口可用（样本测点 ${FIRST_PT}）" || bad "实时最新值接口异常"
fi

echo "[e2e] 校验告警统计接口…"
AT="$(curl -fsS "${API}/alarms/stats" "${AUTH[@]}" | jget data active_total)"
[[ -n "${AT}" && "${AT}" != "None" ]] && ok "告警统计可用，活动告警=${AT}" || bad "告警统计接口异常"

echo ""
echo "==================== 冒烟结果 ===================="
echo "通过=${PASS}  失败=${FAIL}"
[[ "${FAIL}" -eq 0 ]] && { echo "E2E SMOKE: PASS"; exit 0; } || { echo "E2E SMOKE: FAIL"; exit 1; }
