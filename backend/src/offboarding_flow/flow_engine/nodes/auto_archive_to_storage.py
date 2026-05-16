"""auto_archive_to_storage 自动节点（Phase 4.5 加分项 — PRD §18）。

行为：
1. POST 整个流程的 node_results 到外部 mock-archive-service（PRD §18.2）
2. httpx async + tenacity 3 次指数退避重试
3. 成功 → AutoNodeService.execute_auto_action(SUCCESS) 完成双写 → return advance
4. 失败 → AutoNodeService.execute_auto_action(FAILED) → raise（流程卡住等运维介入）

与 archive 节点的差异：
- archive 是 Phase 2 内置的「占位归档」（仅 log + 追加 node_results，无外部 API）
- auto_archive_to_storage 是 Phase 4.5 演示节点（真调外部 HTTP API）
- 拓扑：applicant_final_confirm advance → auto_archive_to_storage → archive → END

PRD §18.3 演示话术：
    「能不能自动做 ≠ 应不应该自动做」— 失败时不自动绕过到 archive，
    而是 mark action_log.failed + 流程卡住等运维介入。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from offboarding_flow.config import get_settings
from offboarding_flow.flow_engine.state import OffboardingState
from offboarding_flow.state_store.enums import ActionStatus

# 注：AutoNodeService 在函数内延迟 import，规避 services/__init__.py → flow_service → nodes 的循环依赖

AUTO_ARCHIVE_TO_STORAGE_NODE_NAME = "auto_archive_to_storage"
AUTO_ARCHIVE_TO_STORAGE_NODE_TITLE = "自动归档（外部存储）"
AUTO_ARCHIVE_TO_STORAGE_NODE_DESCRIPTION = (
    "系统自动调用外部存储服务归档全部节点结果（无需人工操作）— "
    "演示 AutoNode 与 HumanNode 架构对称。"
)

logger = logging.getLogger(__name__)


class ArchiveServiceError(Exception):
    """外部归档服务调用失败（tenacity 重试用完后抛）。"""


async def _post_to_archive_service(
    url: str,
    body: dict,
    timeout: float,
    max_retries: int,
) -> dict:
    """带重试的 httpx POST。

    tenacity 在 httpx.RequestError / 5xx 时重试，4xx 不重试（业务方拒绝时无意义）。
    """
    retry_cond = retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError))
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=0.5, max=2),
        retry=retry_cond,
        reraise=True,
    ):
        with attempt:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=2.0, read=timeout, write=2.0, pool=2.0)
            ) as client:
                response = await client.post(url, json=body)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"archive service 5xx: {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.json()
    # 不应到达 — tenacity reraise=True 时抛
    raise ArchiveServiceError("retry loop exhausted without result")


async def auto_archive_to_storage_node(state: OffboardingState) -> dict:
    """auto_archive_to_storage 节点函数（PRD §18.2）。

    节点函数内：
    1. 取 flow_id / employee_id / node_results
    2. POST 到 ARCHIVE_SERVICE_URL（tenacity 重试）
    3. 成功 → 通过 AutoNodeService 完成双写 → return current_action=advance
    4. 失败 → AutoNodeService 写 action_log.failed + raise ArchiveServiceError
       （让 graph.ainvoke 失败、流程卡在本节点，等运维 recover 介入；
        故意不自动绕过 — PRD §18.3 + §15.3 AI 边界声明）
    """
    flow_id_str = state.get("flow_id", "")
    try:
        flow_id = uuid.UUID(flow_id_str)
    except (ValueError, TypeError) as e:
        logger.exception("[auto_archive] invalid flow_id=%r: %s", flow_id_str, e)
        raise

    settings = get_settings()
    url = settings.archive_service_url
    timeout = settings.archive_service_timeout_seconds
    max_retries = settings.archive_service_max_retries

    body = {
        "flow_id": flow_id_str,
        "employee_id": state.get("employee_id"),
        "node_results": list(state.get("node_results") or []),
        "archived_at": datetime.now(UTC).isoformat(),
    }

    # 延迟 import 规避循环依赖（services/__init__.py → flow_service → nodes）
    from offboarding_flow.services.auto_node_service import AutoNodeService

    svc = AutoNodeService()
    logger.info(
        "[auto_archive] flow=%s POST %s (%d retries)",
        flow_id_str,
        url,
        max_retries,
    )

    try:
        archive_resp = await _post_to_archive_service(
            url=url, body=body, timeout=timeout, max_retries=max_retries
        )
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("[auto_archive] external API failed flow=%s: %s", flow_id, err_msg)
        # 写 action_log.failed（不动 node_states — 留 in_review 让 recover 处理）
        await svc.execute_auto_action(
            flow_id=flow_id,
            node_name=AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
            node_title=AUTO_ARCHIVE_TO_STORAGE_NODE_TITLE,
            actor="system:auto",
            result_text="自动归档调用失败",
            action_status=ActionStatus.FAILED,
            error_message=err_msg,
            payload={"url": url, "request_body_keys": list(body.keys())},
        )
        # raise 让 graph.ainvoke 失败 → 流程卡住等运维介入（不自动绕过）
        raise ArchiveServiceError(f"自动归档失败已记录，等待运维介入：{err_msg}") from exc

    # 成功路径
    result_text = f"已归档到外部存储 path={archive_resp.get('path', 'unknown')}"
    await svc.execute_auto_action(
        flow_id=flow_id,
        node_name=AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
        node_title=AUTO_ARCHIVE_TO_STORAGE_NODE_TITLE,
        actor="system:auto",
        result_text=result_text,
        action_status=ActionStatus.SUCCESS,
        payload={"url": url, "response": archive_resp},
    )

    return {
        "current_action": "advance",
        "node_results": [
            {
                "node_name": AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
                "node_title": AUTO_ARCHIVE_TO_STORAGE_NODE_TITLE,
                "result_text": result_text,
                "actor": "system:auto",
                "completed_at": datetime.now(UTC).isoformat(),
            }
        ],
    }
