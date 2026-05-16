#!/bin/sh
# Phase 1 手动冒烟脚本 — 跑 health + 起流程 + advance 全链路
# 默认 BASE_URL=http://localhost:8000；部署到 44 时 export BASE_URL=http://192.168.2.44:8000

set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "[smoke] BASE_URL=$BASE_URL"

echo
echo "=== Step 1: GET /api/health ==="
curl -sf "$BASE_URL/api/health" | python3 -m json.tool

echo
echo "=== Step 2: POST /api/flows ==="
RESP=$(curl -sf -X POST "$BASE_URL/api/flows" \
  -H "Content-Type: application/json" \
  -d '{"employee_id":"zhang.san"}')
echo "$RESP" | python3 -m json.tool

FLOW_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['flow_id'])")
NODE_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['current_node']['id'])")

echo
echo "[smoke] flow_id=$FLOW_ID node_id=$NODE_ID"

echo
echo "=== Step 3: GET /api/flows/$FLOW_ID/nodes ==="
curl -sf "$BASE_URL/api/flows/$FLOW_ID/nodes" | python3 -m json.tool

echo
echo "=== Step 4: POST /api/flows/$FLOW_ID/nodes/$NODE_ID/actions advance ==="
curl -sf -X POST "$BASE_URL/api/flows/$FLOW_ID/nodes/$NODE_ID/actions" \
  -H "Content-Type: application/json" \
  -d '{"action":"advance","result_text":"同意离职 — smoke 测试","actor":"li.si"}' \
  | python3 -m json.tool

echo
echo "=== Step 5: GET /api/flows/$FLOW_ID （应 status=completed） ==="
curl -sf "$BASE_URL/api/flows/$FLOW_ID" | python3 -m json.tool

echo
echo "[smoke] ✓ Phase 1 冒烟通过"
