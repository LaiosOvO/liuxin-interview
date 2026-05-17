#!/usr/bin/env bash
# =============================================================================
# pull_huly_images.sh — Huly 镜像一键拉取（Phase 8 / HULY-01）
# -----------------------------------------------------------------------------
# 用途：
#   在 192.168.2.44（或任何 Docker 宿主机）一次性拉齐 Huly 完整 stack 需要的
#   全部镜像（11 个 hardcoreeng 业务服务 + 4 个基础设施 = 15 个）。
#
# 使用方法：
#   # 默认拉 v0.7.423（与 .env.example 同步）
#   ./scripts/pull_huly_images.sh
#
#   # 覆盖版本号
#   HULY_VERSION=v0.7.500 ./scripts/pull_huly_images.sh
#
#   # 仅打印将要执行的命令（不真拉）
#   ./scripts/pull_huly_images.sh --dry-run
#
# 资源消耗预估：
#   - 总下载量：~7-9 GB（按版本浮动）
#   - 拉取耗时：内网镜像缓存 ≈ 3-5 min；公网首次 ≈ 15-25 min
#   - 运行时 RAM：完整 stack ~4-6 GB（CockroachDB 1G + ES 1.5G + 各业务服务 200-500M）
#
# 设计要点：
#   - set -euo pipefail 严格模式，任何一步失败即退出
#   - 单镜像失败时指数退避重试 3 次（10s / 30s / 60s）
#   - 进度输出格式 [N/TOTAL] image:tag
#   - 末尾打印成功 / 失败统计 + docker images 验证清单
#
# 镜像清单同步源：deploy/huly/HULY_IMAGES.md（人工同步）
# 上游参考：https://github.com/hcengineering/huly-selfhost
# =============================================================================

set -euo pipefail

HULY_VERSION="${HULY_VERSION:-v0.7.423}"
DRY_RUN=false

# 解析参数
for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN=true
            ;;
        --help)
            echo "用法: $0 [--dry-run]"
            echo "  --dry-run  仅打印将拉取的镜像，不真执行 docker pull"
            echo "  环境变量 HULY_VERSION 控制 hardcoreeng 镜像版本号，默认 v0.7.423"
            exit 0
            ;;
        *)
            echo "未知参数: $arg（用 --help 查看用法）" >&2
            exit 1
            ;;
    esac
done

# 颜色输出（终端支持时）
if [ -t 1 ]; then
    C_INFO='\033[1;34m'
    C_OK='\033[1;32m'
    C_ERR='\033[1;31m'
    C_WARN='\033[1;33m'
    C_END='\033[0m'
else
    C_INFO='' C_OK='' C_ERR='' C_WARN='' C_END=''
fi

# 镜像清单（业务 11 个 + 基础设施 4 个 = 15 个）
#
# 业务（hardcoreeng/* 同版本）：
#   account / front / transactor / collaborator / workspace / stats / rekoni-service /
#   fulltext / hulykvs / love / print
#
# 基础设施（无 hardcoreeng 前缀）：
#   cockroach / redpanda / elasticsearch / minio
#
# 注意：项目已有独立 offboarding-redis（端口 6380），Huly stack 默认不再起新 redis；
#       若 Plan 04 需 hulypulse 才追加 redis:7-alpine。
HARDCOREENG_IMAGES=(
    "hardcoreeng/account:${HULY_VERSION}"
    "hardcoreeng/front:${HULY_VERSION}"
    "hardcoreeng/transactor:${HULY_VERSION}"
    "hardcoreeng/collaborator:${HULY_VERSION}"
    "hardcoreeng/workspace:${HULY_VERSION}"
    "hardcoreeng/stats:${HULY_VERSION}"
    "hardcoreeng/rekoni-service:${HULY_VERSION}"
    "hardcoreeng/fulltext:${HULY_VERSION}"
    "hardcoreeng/hulykvs:${HULY_VERSION}"
    "hardcoreeng/love:${HULY_VERSION}"
    "hardcoreeng/print:${HULY_VERSION}"
)

INFRA_IMAGES=(
    "cockroachdb/cockroach:latest-v24.2"
    "docker.redpanda.com/redpandadata/redpanda:v24.3.6"
    "elasticsearch:7.14.2"
    "minio/minio:latest"
)

ALL_IMAGES=("${HARDCOREENG_IMAGES[@]}" "${INFRA_IMAGES[@]}")
TOTAL=${#ALL_IMAGES[@]}

# 单镜像拉取（含重试）
pull_with_retry() {
    local image="$1"
    local idx="$2"
    local attempt=1
    local max_attempts=3
    local delays=(10 30 60)

    while [ $attempt -le $max_attempts ]; do
        echo -e "${C_INFO}[${idx}/${TOTAL}] pulling ${image}${C_END} (attempt ${attempt}/${max_attempts})"

        if $DRY_RUN; then
            echo "  [dry-run] docker pull ${image}"
            return 0
        fi

        if docker pull "$image"; then
            echo -e "${C_OK}  ✓ ${image}${C_END}"
            return 0
        fi

        local delay=${delays[$((attempt - 1))]}
        if [ $attempt -lt $max_attempts ]; then
            echo -e "${C_WARN}  ! 拉取失败，${delay}s 后重试${C_END}"
            sleep "$delay"
        fi
        attempt=$((attempt + 1))
    done

    echo -e "${C_ERR}  ✗ ${image} 拉取失败（已重试 ${max_attempts} 次）${C_END}"
    return 1
}

# 主流程
main() {
    echo "============================================================"
    echo "  Huly 镜像拉取脚本 — Phase 8 / HULY-01"
    echo "  HULY_VERSION = ${HULY_VERSION}"
    echo "  总数 = ${TOTAL}（业务 ${#HARDCOREENG_IMAGES[@]} + 基础设施 ${#INFRA_IMAGES[@]}）"
    echo "  dry-run = ${DRY_RUN}"
    echo "============================================================"

    if ! command -v docker >/dev/null 2>&1; then
        echo -e "${C_ERR}错误：未找到 docker 命令${C_END}" >&2
        exit 2
    fi

    local start_ts
    start_ts=$(date +%s)
    local success=0
    local failed=()

    for i in "${!ALL_IMAGES[@]}"; do
        local idx=$((i + 1))
        local image="${ALL_IMAGES[$i]}"
        if pull_with_retry "$image" "$idx"; then
            success=$((success + 1))
        else
            failed+=("$image")
        fi
    done

    local elapsed=$(( $(date +%s) - start_ts ))

    echo "============================================================"
    echo -e "${C_OK}成功 ${success} / ${TOTAL}${C_END}"
    if [ ${#failed[@]} -gt 0 ]; then
        echo -e "${C_ERR}失败 ${#failed[@]} 个：${C_END}"
        for img in "${failed[@]}"; do
            echo "  - $img"
        done
    fi
    echo "总耗时：${elapsed}s"
    echo "============================================================"

    if ! $DRY_RUN; then
        echo "本地镜像验证："
        docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}' \
            | grep -E "hardcoreeng|cockroachdb|redpandadata|elasticsearch|minio" \
            || echo "（未找到镜像，可能未真拉）"
    fi

    [ ${#failed[@]} -eq 0 ] || exit 1
}

main "$@"
