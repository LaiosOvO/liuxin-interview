#!/usr/bin/env bash
# Mattermost 测试组织数据 seed（PRD §9.1）
# 通过 mmctl --local（容器内 Unix socket）操作，无需 PAT
# 使用：cat seed-mattermost.sh | ssh GigaByte@192.168.2.44 'wsl -d Ubuntu -e bash -s'
#
# v2 变更：邮箱从 @demo.local 改为 +alias 真邮箱
#   - 邮件实际投递到 1624456575@qq.com / 1691517500@qq.com / jingzhi.lu@wayz.ai
#   - Mattermost 视为不同邮箱（保留唯一性），实际收件箱共享

set -u

DEPLOY_DIR="${DEPLOY_DIR:-$HOME/mattermost-docker}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-laios1855}"
DEMO_PASSWORD="${DEMO_PASSWORD:-laios1855}"

cd "$DEPLOY_DIR"
MM="docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml exec -T mattermost mmctl --local"

ok()   { printf "  ✓ %s\n" "$*"; }
skip() { printf "  · %s（已存在/已配置）\n" "$*"; }

echo "============================================================"
echo "Mattermost 测试组织数据 Seed v2"
echo "邮箱方案：3 个真邮箱 + alias 分发"
echo "============================================================"

echo
echo "[1/5] 确保系统管理员存在并修正邮箱"
out=$($MM user create \
        --email "jingzhi.lu+admin@wayz.ai" \
        --username admin \
        --password "$ADMIN_PASSWORD" \
        --system-admin 2>&1)
if echo "$out" | grep -qi "already\|exists\|taken"; then
  $MM user edit email admin "jingzhi.lu+admin@wayz.ai" >/dev/null 2>&1 && ok "admin 邮箱已更新" || skip "admin 邮箱无需更新"
else
  ok "admin 已创建 (admin@... / $ADMIN_PASSWORD)"
fi

echo
echo "[2/5] 创建团队（6 个：5 部门 + laios 演示团队）"
TEAMS=(
  "laios:Laios 演示团队"
  "engineering:研发部"
  "hr:人力资源部"
  "it:IT 运维部"
  "finance:财务部"
  "legal:法务部"
)
for t in "${TEAMS[@]}"; do
  name="${t%%:*}"; disp="${t#*:}"
  out=$($MM team create --name "$name" --display-name "$disp" 2>&1)
  if echo "$out" | grep -qi "already\|exists\|taken"; then skip "team $name"; else ok "team $name ($disp)"; fi
done

echo
echo "[3/5] 创建 8 个测试账号（邮箱用 +alias 真邮箱）"
# username:email:firstName:lastName:position
USERS=(
  "zhang.san:1624456575+zhang.san@qq.com:张:三:研发工程师 离职员工"
  "li.si:1624456575+li.si@qq.com:李:四:研发组长 直属上级"
  "hr.bob:1624456575+hr.bob@qq.com:Bob::HR 总监"
  "wang.wu:1691517500+wang.wu@qq.com:王:五:研发总监"
  "hr.alice:1691517500+hr.alice@qq.com:Alice::HR 专员"
  "it.charlie:1691517500+it.charlie@qq.com:Charlie::IT 设备管理员"
  "fin.david:jingzhi.lu+fin.david@wayz.ai:David::财务结算专员"
  "legal.eve:jingzhi.lu+legal.eve@wayz.ai:Eve::法务合规"
)
for u in "${USERS[@]}"; do
  IFS=':' read -r username email fn ln pos <<< "$u"
  out=$($MM user create \
          --email "$email" \
          --username "$username" \
          --password "$DEMO_PASSWORD" \
          --firstname "$fn" \
          --lastname "$ln" 2>&1)
  if echo "$out" | grep -qi "already\|exists\|taken"; then
    # 已存在则尝试更新邮箱，确保符合新方案
    $MM user edit email "$username" "$email" >/dev/null 2>&1 && ok "$username 邮箱已更新为 $email" || skip "user $username"
  else
    ok "user $username ($pos) -> $email"
  fi
done

echo
echo "[4/5] 配置部门归属"
MEMBERSHIPS=(
  "zhang.san:engineering"
  "li.si:engineering"
  "wang.wu:engineering"
  "hr.alice:hr"
  "hr.bob:hr"
  "it.charlie:it"
  "fin.david:finance"
  "legal.eve:legal"
  "admin:laios"
)
for m in "${MEMBERSHIPS[@]}"; do
  IFS=':' read -r username team <<< "$m"
  $MM team users add "$team" "$username" >/dev/null 2>&1 && ok "$username → $team" || skip "$username → $team"
  if [ "$team" != "laios" ]; then
    $MM team users add laios "$username" >/dev/null 2>&1 && ok "$username → laios" || skip "$username → laios"
  fi
done

echo
echo "[5/5] 设置 position（职位） — 用 mmctl user edit"
# username:position
POSITIONS=(
  "zhang.san:研发工程师"
  "li.si:研发组长"
  "wang.wu:研发总监"
  "hr.alice:HR 专员"
  "hr.bob:HR 总监"
  "it.charlie:IT 设备管理员"
  "fin.david:财务结算专员"
  "legal.eve:法务合规"
)
# mmctl 没有直接 set position 命令，跳过；后续 seed_demo_data.py 用 REST API 写 custom_attributes
for p in "${POSITIONS[@]}"; do
  IFS=':' read -r u pos <<< "$p"
  echo "  · $u position 暂留空（待 seed_demo_data.py 用 REST 写）"
done

echo
echo "============================================================"
echo "完成。验证："
echo "============================================================"
echo "--- users ---"
$MM user list --all 2>&1
echo
echo "--- teams ---"
$MM team list 2>&1

echo
echo "============================================================"
echo "登录信息（演示用，请勿用于生产）"
echo "============================================================"
echo "URL:           http://192.168.2.44:8065"
echo "系统管理员:    admin / $ADMIN_PASSWORD  (邮箱: jingzhi.lu+admin@wayz.ai)"
echo "测试账号密码:  $DEMO_PASSWORD"
echo "演示主团队:    laios"
echo
echo "邮箱分配："
echo "  → 1624456575@qq.com  : zhang.san, li.si, hr.bob"
echo "  → 1691517500@qq.com  : wang.wu, hr.alice, it.charlie"
echo "  → jingzhi.lu@wayz.ai : fin.david, legal.eve, admin"
echo "============================================================"
