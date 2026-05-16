"""handover_service — 离职流程节点交接文档生成。

设计：
- 节点 advance 成功后 fire-and-forget 触发（不阻塞 API 响应）
- 走 DocProvider 抽象（Outline / Lark / WeCom / DingTalk 切换）
- 失败仅 log，不影响主流程
- 生成的 doc_url 写回 node_states.handover_doc_url 字段

节点交接 vs 流程总报告：
- generate_node_handover() — 每节点一份（小报告）
- generate_final_summary() — 整流程一份（汇总各节点 + 总览，archive 节点触发）
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from offboarding_flow.flow_engine.provider_mapping import resolve_doc_provider
from offboarding_flow.llm.prompts import (
    HANDOVER_FINAL_SUMMARY_PROMPT,
    HANDOVER_NODE_PROMPT,
)
from offboarding_flow.providers import DocInfo
from offboarding_flow.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# 按员工分独立 collection（用户要求："一个员工就新建的文件夹分类"）。
# 各员工的所有节点交接 + 总报告都进 "离职 · {employee_id}" 文件夹，
# 而不是过去全部堆在一个全局 collection 里。
HANDOVER_COLLECTION_PREFIX = "离职 · "
# 旧的全局兜底名（仅用于 employee_id 缺失等异常情形）。
HANDOVER_FALLBACK_COLLECTION = "离职交接 / 未归档"


def _employee_collection_name(employee_id: str | None) -> str:
    """返回员工独立 collection 名（每员工一文件夹）。"""
    eid = (employee_id or "").strip()
    if not eid:
        return HANDOVER_FALLBACK_COLLECTION
    return f"{HANDOVER_COLLECTION_PREFIX}{eid}"


def _render_rule_based_final_summary(
    *,
    employee_id: str,
    flow_id: Any,
    status: str,
    started_at: str,
    completed_at: str | None,
    node_results: list[dict],
    handover_links: list[dict[str, str]],
) -> str:
    """LLM 不可用时的规则版总报告 — 至少保证文档能生成。"""
    lines: list[str] = []
    lines.append(f"# 离职交接总报告 — {employee_id}")
    lines.append("")
    lines.append("## 👤 员工基本信息")
    lines.append(f"- 员工 ID：`{employee_id}`")
    lines.append(f"- 流程 ID：`{flow_id}`")
    lines.append(f"- 流程状态：**{status}**")
    lines.append(f"- 启动时间：{started_at}")
    lines.append(f"- 完成时间：{completed_at or '（未完成）'}")
    lines.append("")
    lines.append("## ⏱️ 流程时间线")
    if node_results:
        for i, n in enumerate(node_results, 1):
            ts = n.get("completed_at", "")[:16].replace("T", " ")
            lines.append(
                f"{i}. **{n.get('node_title', n.get('node_name', '?'))}**"
                f" — @{n.get('actor', '?')} _{ts}_ → `{n.get('action', '?')}`"
            )
    else:
        lines.append("_无节点记录_")
    lines.append("")
    lines.append("## 📊 各节点摘要")
    if node_results:
        for n in node_results:
            txt = n.get("result_text", "")[:80]
            lines.append(f"- **{n.get('node_title', '?')}**: {txt}")
    lines.append("")
    lines.append("## 📎 涉及的协作文档")
    if handover_links:
        for link in handover_links:
            lines.append(
                f"- [{link.get('title', link.get('node_title', '?'))}]({link.get('url', '')})"
            )
    else:
        lines.append("_无_")
    lines.append("")
    lines.append("## ✅ 合规检查清单")
    done_nodes = {n.get("node_name") for n in node_results if n.get("action") == "advance"}
    checks = [
        ("device_return", "设备归还"),
        ("access_revoke", "权限回收"),
        ("knowledge_handover", "知识交接"),
        ("finance_settle", "财务结算"),
        ("legal_sign", "法务签字"),
    ]
    for key, label in checks:
        mark = "✅" if key in done_nodes else "⬜"
        lines.append(f"- {mark} {label}")
    lines.append("")
    lines.append("## 📞 后续联系人")
    lines.append("- HR 总监：@hr.alice")
    lines.append("- 直属上级：@li.si")
    lines.append("")
    lines.append("---")
    lines.append("> *规则版总报告（LLM 不可用时降级），由离职流程系统自动生成*")
    return "\n".join(lines)


# 下游节点提示（hard-code 简化版；后续可从 DAG 自动推导）
_NEXT_NODES_HINT: dict[str, str] = {
    "manager_review": "HR 初审（hr.bob）会接力评估",
    "hr_initial": "并行 5 节点启动：设备归还 / 权限回收 / 知识交接 / 财务结算 / 法务签字",
    "device_return": "IT 同事会汇总到 HR 终审",
    "access_revoke": "IT 同事会汇总到 HR 终审",
    "knowledge_handover": "知识库管理员归档后 HR 终审",
    "finance_settle": "财务结清后 HR 终审",
    "legal_sign": "法务确认后 HR 终审",
    "hr_final": "申请人会收到最终确认邮件",
    "applicant_final_confirm": "系统自动归档到知识库",
    "archive": "（流程结束）",
}


class HandoverService:
    """节点交接文档服务。"""

    def __init__(self, llm: LLMService | None = None) -> None:
        self.llm = llm or LLMService()

    async def generate_node_handover(
        self,
        *,
        flow_id: uuid.UUID,
        node_id: uuid.UUID,
        employee_id: str,
        node_name: str,
        node_title: str,
        result_text: str,
        actor: str,
        action: str,
    ) -> DocInfo | None:
        """对单个 advanced 节点生成交接文档。失败返回 None。"""
        try:
            ctx = {
                "employee_id": employee_id,
                "node_name": node_name,
                "node_title": node_title,
                "actor": actor,
                "action": action,
                "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "result_text": result_text or "（无具体说明）",
                "next_nodes_brief": _NEXT_NODES_HINT.get(node_name, "见 DAG"),
            }
            markdown = await self.llm.complete(
                HANDOVER_NODE_PROMPT,
                ctx,
                with_disclaimer=True,
                with_header=True,
                timeout=25.0,
            )
            if not markdown:
                logger.warning("[handover] LLM 降级，跳过节点 %s 文档生成", node_name)
                return None

            # 节点 handover 文档放独立 collection
            from offboarding_flow.providers.outline_provider import (
                OutlineProvider,
            )

            doc_provider = resolve_doc_provider(node_name=node_name)
            title = f"[离职交接] {employee_id} · {node_title}"
            # 每员工独立 collection（用户要求按员工分文件夹）
            collection = _employee_collection_name(employee_id)
            if isinstance(doc_provider, OutlineProvider):
                doc_info = await doc_provider.create_document(
                    title=title,
                    markdown=markdown,
                    owner_usernames=[actor, employee_id],
                    collection_name=collection,
                )
            else:
                doc_info = await doc_provider.create_document(
                    title=title,
                    markdown=markdown,
                    owner_usernames=[actor, employee_id],
                )
            logger.info(
                "[handover] node %s doc created url=%s",
                node_name,
                doc_info.url,
            )
            return doc_info
        except Exception as e:
            logger.warning(
                "[handover] generate_node_handover failed flow=%s node=%s: %s",
                flow_id,
                node_name,
                e,
            )
            return None

    async def generate_final_summary(
        self,
        *,
        flow_id: uuid.UUID,
        employee_id: str,
        status: str,
        started_at: str,
        completed_at: str | None,
        node_results: list[dict],
        handover_links: list[dict[str, str]],  # [{node, title, url}]
    ) -> DocInfo | None:
        """流程结束时（archive）生成总交接报告，汇总各节点 + 文档链接。"""
        try:
            links_text = (
                "\n".join(f"- [{link['title']}]({link['url']})" for link in handover_links)
                or "（无）"
            )
            ctx = {
                "employee_id": employee_id,
                "flow_id": str(flow_id),
                "status": status,
                "started_at": started_at,
                "completed_at": completed_at or "（未完成）",
                "node_results_json": json.dumps(node_results, ensure_ascii=False, indent=2),
                "handover_links": links_text,
            }
            markdown = await self.llm.complete(
                HANDOVER_FINAL_SUMMARY_PROMPT,
                ctx,
                with_disclaimer=True,
                with_header=True,
                timeout=60.0,  # 总报告 context 大，给宽松超时
            )
            if not markdown:
                logger.warning("[handover] final summary LLM 降级 — 走规则版 flow=%s", flow_id)
                # 规则版兜底：直接列出 timeline + handover docs（不调 LLM）
                markdown = _render_rule_based_final_summary(
                    employee_id=employee_id,
                    flow_id=flow_id,
                    status=status,
                    started_at=started_at,
                    completed_at=completed_at,
                    node_results=node_results,
                    handover_links=handover_links,
                )

            from offboarding_flow.providers.outline_provider import (
                OutlineProvider,
            )

            # 总报告无特定 node — 走全局默认 provider，但归到员工独立 collection
            doc_provider = resolve_doc_provider()
            title = f"[离职档案] {employee_id} · 完整交接报告"
            collection = _employee_collection_name(employee_id)
            if isinstance(doc_provider, OutlineProvider):
                doc_info = await doc_provider.create_document(
                    title=title,
                    markdown=markdown,
                    owner_usernames=[employee_id],
                    collection_name=collection,
                )
            else:
                doc_info = await doc_provider.create_document(
                    title=title,
                    markdown=markdown,
                    owner_usernames=[employee_id],
                )
            logger.info("[handover] final summary doc created url=%s", doc_info.url)
            return doc_info
        except Exception as e:
            logger.warning(
                "[handover] generate_final_summary failed flow=%s: %s",
                flow_id,
                e,
            )
            return None
