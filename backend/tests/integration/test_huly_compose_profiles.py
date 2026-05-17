"""Phase 8 / HULY-01 + HULY-02 — docker-compose.yml huly-stack/huly profile 静态校验。

不真启动容器；仅校验 YAML / profile / 环境变量 / 依赖关系等静态契约。

覆盖：
1. docker-compose.yml YAML 语法合法
2. services 段含 11 huly-* 业务 + 4 基础设施 + 1 huly-bridge + 现有 5 个原有 service
3. 所有 huly 基础设施 + 业务 service 标 profiles=["huly-stack"]；huly-bridge 标 profiles=["huly"]
4. .env.example 中 docker-compose 引用的 ${HULY_*} 变量全部声明
5. 关键 service 有 healthcheck（huly-cockroach / huly-front / huly-elastic / huly-minio）
6. volumes 段含 4 个 huly-* 卷（cockroach / redpanda / elastic / minio）
7. 所有 huly-* service 都在 networks=[offboarding-net]
8. 默认 profile 启动时（即不带 profile）不包含任何 huly-* service
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

# 期望的 huly-stack profile 业务 service（11 个 hardcoreeng/*）
EXPECTED_HULY_BUSINESS_SERVICES = {
    "huly-account",
    "huly-front",
    "huly-transactor",
    "huly-collaborator",
    "huly-workspace",
    "huly-stats",
    "huly-rekoni",
    "huly-fulltext",
    "huly-kvs",
    "huly-love",
    "huly-print",
}

# 期望的 huly-stack profile 基础设施 service（4 个）
EXPECTED_HULY_INFRA_SERVICES = {
    "huly-cockroach",
    "huly-redpanda",
    "huly-elastic",
    "huly-minio",
}

EXPECTED_HULY_STACK_SERVICES = EXPECTED_HULY_BUSINESS_SERVICES | EXPECTED_HULY_INFRA_SERVICES

# 期望的 huly profile service（仅 huly-bridge sidecar）
EXPECTED_HULY_SIDECAR_SERVICES = {"huly-bridge"}

# 现有 offboarding service（必须不被本 plan 修改）
EXPECTED_EXISTING_SERVICES = {
    "offboarding-postgres",
    "offboarding-redis",
    "flow-api",
    "mock-archive-service",
    "outline",
    "nginx",
    "frontend-build",
}

# 期望 healthcheck 的关键 service
EXPECTED_HEALTHCHECK_SERVICES = {
    "huly-cockroach",
    "huly-redpanda",
    "huly-elastic",
    "huly-minio",
    "huly-front",
    "huly-bridge",
}

# 期望的 huly 持久化卷
EXPECTED_HULY_VOLUMES = {
    "huly-cockroach-data",
    "huly-redpanda-data",
    "huly-elastic-data",
    "huly-minio-data",
}


@pytest.fixture(scope="module")
def compose() -> dict:
    """加载 docker-compose.yml 为 dict。"""
    assert COMPOSE_PATH.exists(), f"docker-compose.yml 不存在: {COMPOSE_PATH}"
    with COMPOSE_PATH.open("r", encoding="utf-8") as fp:
        # safe_load 失败会直接抛 yaml.YAMLError → 测试 fail
        data = yaml.safe_load(fp)
    assert isinstance(data, dict), "docker-compose.yml 顶层应为 mapping"
    return data


@pytest.fixture(scope="module")
def env_example_content() -> str:
    """加载 .env.example 文本。"""
    assert ENV_EXAMPLE_PATH.exists(), f".env.example 不存在: {ENV_EXAMPLE_PATH}"
    return ENV_EXAMPLE_PATH.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# 测试 1：YAML 合法
# -----------------------------------------------------------------------------
def test_compose_yaml_loads_without_error(compose: dict) -> None:
    """docker-compose.yml 必须是合法 YAML（fixture 已加载，到这里即通过）。"""
    assert "services" in compose, "docker-compose.yml 必须有 services 段"
    assert isinstance(compose["services"], dict)


# -----------------------------------------------------------------------------
# 测试 2：services 完整性
# -----------------------------------------------------------------------------
def test_compose_contains_all_expected_services(compose: dict) -> None:
    """services 段必须含 15 huly-stack + 1 huly sidecar + 7 现有 service。"""
    services = set(compose["services"].keys())

    missing_huly_stack = EXPECTED_HULY_STACK_SERVICES - services
    assert not missing_huly_stack, f"缺失 huly-stack service: {missing_huly_stack}"

    missing_sidecar = EXPECTED_HULY_SIDECAR_SERVICES - services
    assert not missing_sidecar, f"缺失 huly sidecar service: {missing_sidecar}"

    missing_existing = EXPECTED_EXISTING_SERVICES - services
    assert (
        not missing_existing
    ), f"缺失现有 offboarding service（不应被本 plan 修改）: {missing_existing}"


# -----------------------------------------------------------------------------
# 测试 3：profile 标签正确
# -----------------------------------------------------------------------------
def test_huly_stack_services_have_correct_profile(compose: dict) -> None:
    """11 业务 + 4 基础设施 = 15 个 service 都必须 profiles=["huly-stack"]。"""
    for name in EXPECTED_HULY_STACK_SERVICES:
        svc = compose["services"][name]
        profiles = svc.get("profiles", [])
        assert "huly-stack" in profiles, f"{name} 缺少 profiles=['huly-stack']，实际: {profiles}"


def test_huly_bridge_has_huly_profile(compose: dict) -> None:
    """huly-bridge 必须 profiles=["huly"]（与 huly-stack 区分）。"""
    bridge = compose["services"]["huly-bridge"]
    profiles = bridge.get("profiles", [])
    assert "huly" in profiles, f"huly-bridge 必须 profiles=['huly']，实际: {profiles}"


def test_existing_services_have_no_huly_profile(compose: dict) -> None:
    """现有 service（postgres/redis/flow-api 等）不应被加 huly profile。"""
    for name in EXPECTED_EXISTING_SERVICES:
        svc = compose["services"][name]
        profiles = svc.get("profiles", [])
        # frontend-build 已用 profiles=["build"]，其他默认无 profile
        forbidden = {"huly-stack", "huly"}
        bad = forbidden & set(profiles)
        assert not bad, f"{name} 不应有 huly profile：{bad}"


# -----------------------------------------------------------------------------
# 测试 4：.env.example 含全部 ${HULY_*} 变量
# -----------------------------------------------------------------------------
def test_env_example_declares_all_huly_vars(compose: dict, env_example_content: str) -> None:
    """compose 中所有 ${HULY_*} 引用必须在 .env.example 有声明。"""
    # 提取 compose.yml 中所有 ${HULY_xxx} 变量名
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\$\{(HULY_[A-Z0-9_]+)", compose_text))
    assert referenced, "compose.yml 应包含 ${HULY_*} 变量引用"

    # .env.example 中所有声明的 var=value
    declared = set(re.findall(r"^(HULY_[A-Z0-9_]+)=", env_example_content, re.MULTILINE))

    missing = referenced - declared
    assert (
        not missing
    ), f".env.example 缺失 compose 引用的变量: {missing}（已声明: {sorted(declared)}）"


def test_env_example_huly_vars_have_safe_placeholders(env_example_content: str) -> None:
    """敏感凭证 HULY_SERVER_SECRET / HULY_BRIDGE_TOKEN 不能硬编码真实值。"""
    for line in env_example_content.splitlines():
        if line.startswith("HULY_SERVER_SECRET="):
            value = line.split("=", 1)[1].strip()
            assert (
                "changeme" in value.lower()
            ), f"HULY_SERVER_SECRET 必须用 changeme_* 占位，不能硬编码真密钥: {value}"
        if line.startswith("HULY_BRIDGE_TOKEN="):
            value = line.split("=", 1)[1].strip()
            assert "changeme" in value.lower(), f"HULY_BRIDGE_TOKEN 必须用 changeme_* 占位: {value}"


# -----------------------------------------------------------------------------
# 测试 5：关键 service 有 healthcheck
# -----------------------------------------------------------------------------
def test_critical_services_have_healthcheck(compose: dict) -> None:
    """huly-cockroach / huly-front / huly-elastic 等关键 service 必须有 healthcheck。"""
    for name in EXPECTED_HEALTHCHECK_SERVICES:
        svc = compose["services"][name]
        hc = svc.get("healthcheck")
        assert hc is not None, f"{name} 缺失 healthcheck"
        assert "test" in hc, f"{name} healthcheck 缺 test 字段"


# -----------------------------------------------------------------------------
# 测试 6：volumes 段含 4 个 huly-* 卷
# -----------------------------------------------------------------------------
def test_compose_declares_all_huly_volumes(compose: dict) -> None:
    """volumes 段必须含 huly-cockroach-data / huly-redpanda-data / huly-elastic-data / huly-minio-data。"""
    declared_volumes = set((compose.get("volumes") or {}).keys())
    missing = EXPECTED_HULY_VOLUMES - declared_volumes
    assert not missing, f"volumes 段缺失 huly 卷: {missing}"


# -----------------------------------------------------------------------------
# 测试 7：所有 huly-* service 都在 offboarding-net
# -----------------------------------------------------------------------------
def test_all_huly_services_join_offboarding_net(compose: dict) -> None:
    """huly-stack + huly-bridge 全部 service 必须 networks: [offboarding-net]。"""
    all_huly_services = EXPECTED_HULY_STACK_SERVICES | EXPECTED_HULY_SIDECAR_SERVICES
    for name in all_huly_services:
        svc = compose["services"][name]
        networks = svc.get("networks", [])
        assert (
            "offboarding-net" in networks
        ), f"{name} 未加入 offboarding-net，实际 networks={networks}"


# -----------------------------------------------------------------------------
# 测试 8：默认 profile 行为不变（无 huly-* service 出现）
# -----------------------------------------------------------------------------
def test_default_profile_excludes_huly_services(compose: dict) -> None:
    """不带 --profile 启动时，huly-* 全 15 个 service 应被 docker compose 排除。

    Compose 规则：标了 profiles=["xxx"] 的 service 仅当 --profile xxx 时才启动。
    """
    huly_services = EXPECTED_HULY_STACK_SERVICES | EXPECTED_HULY_SIDECAR_SERVICES
    for name in huly_services:
        svc = compose["services"][name]
        profiles = svc.get("profiles") or []
        assert profiles, f"{name} 必须显式声明 profiles（避免默认启动），实际: {profiles}"
        # 必须含 huly-stack 或 huly 中至少一个
        assert {"huly-stack", "huly"} & set(
            profiles
        ), f"{name} profiles 必须含 huly-stack 或 huly，实际: {profiles}"
