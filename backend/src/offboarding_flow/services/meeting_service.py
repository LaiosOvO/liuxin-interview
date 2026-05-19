"""meeting_service — 会议纪要 → AI 提取 → Outline 文档 → Mattermost 分发。

流程：
1. ingest(raw_text): 调 GLM 提取 JSON 结构（tasks/owners/blockers/decisions）
2. publish_to_outline(): 渲染 markdown + 调 OutlineClient 创建文档
3. distribute_to_mm(): channel post 文档链接 + DM 各 owner 私推任务清单

设计要点：
- LLM 返回**严格 JSON**（由 prompts.EXTRACT_MEETING_PROMPT 约束）
- JSON 解析失败兜底：抓 ``` 围栏 / 容错首尾杂质
- Outline 写入失败不阻断 MM 分发（degraded mode）— 至少消息还能 push
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from offboarding_flow.config import get_settings
from offboarding_flow.llm.prompts import (
    ANALYZE_BLOCKER_PROMPT,
    ANALYZE_DECISION_PROMPT,
    ANALYZE_TASK_PROMPT,
    EXECUTIVE_BRIEF_PROMPT,
    EXTRACT_MEETING_PROMPT,
    PERSONAL_BRIEF_PROMPT,
)
from offboarding_flow.outline.client import OutlineClient, OutlineError
from offboarding_flow.providers import (
    DocInfo,
    DocProvider,
    IMProvider,
    get_doc_provider,
    get_im_provider,
)
from offboarding_flow.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# Outline 默认 collection 名 — 所有会议纪要都进这里
DEFAULT_COLLECTION_NAME = "会议纪要 / Meetings"


@dataclass(frozen=True)
class Task:
    text: str
    owner: str
    due_date: str | None
    priority: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        return cls(
            text=str(d.get("text", "")).strip(),
            owner=str(d.get("owner", "unknown")).strip().lower() or "unknown",
            due_date=d.get("due_date"),
            priority=str(d.get("priority", "medium")).lower(),
        )


@dataclass(frozen=True)
class Blocker:
    description: str
    owner: str | None
    severity: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Blocker":
        owner = d.get("owner")
        return cls(
            description=str(d.get("description", "")).strip(),
            owner=str(owner).strip().lower() if owner else None,
            severity=str(d.get("severity", "medium")).lower(),
        )


@dataclass(frozen=True)
class Decision:
    decision: str
    made_by: str | None
    impact: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Decision":
        made_by = d.get("made_by")
        return cls(
            decision=str(d.get("decision", "")).strip(),
            made_by=str(made_by).strip().lower() if made_by else None,
            impact=str(d.get("impact", "")).strip(),
        )


@dataclass(frozen=True)
class AnalyzedTask:
    task: "Task"
    ai_brief: str  # 单独 LLM 分析的 markdown


@dataclass(frozen=True)
class AnalyzedBlocker:
    blocker: "Blocker"
    ai_brief: str


@dataclass(frozen=True)
class AnalyzedDecision:
    decision: "Decision"
    ai_brief: str


@dataclass(frozen=True)
class AnalyzedMeeting:
    """逐项深度分析后的结果（每条任务/卡点/决策都有 AI brief）。"""

    extract: "MeetingExtract"
    tasks: list[AnalyzedTask]
    blockers: list[AnalyzedBlocker]
    decisions: list[AnalyzedDecision]
    executive_brief: str  # 管理层视角


@dataclass(frozen=True)
class MeetingExtract:
    """LLM 提取结果（不可变 DTO）。"""

    title: str
    summary: str
    tasks: list[Task]
    blockers: list[Blocker]
    decisions: list[Decision]
    raw_text: str

    def owners(self) -> list[str]:
        """所有相关 username（去重，去 unknown / 空 / 无效）。"""
        INVALID = {"unknown", "", "n/a", "未指定", "tbd", "未知"}
        s: set[str] = set()
        for t in self.tasks:
            if t.owner and t.owner.lower() not in INVALID:
                s.add(t.owner)
        for b in self.blockers:
            if b.owner and b.owner.lower() not in INVALID:
                s.add(b.owner)
        for d in self.decisions:
            if d.made_by and d.made_by.lower() not in INVALID:
                s.add(d.made_by)
        return sorted(s)


def _strip_json_fences(text: str) -> str:
    """LLM 可能给 ```json ... ``` 围栏，剥掉。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if m:
        return m.group(1).strip()
    return text


class MeetingService:
    """会议纪要服务 — 提取 + 分发。"""

    def __init__(
        self,
        llm: LLMService | None = None,
        doc_provider: DocProvider | None = None,
        im_provider: IMProvider | None = None,
        outline: OutlineClient | None = None,  # 兼容旧调用
    ) -> None:
        self.llm = llm or LLMService()
        self._doc_provider = doc_provider
        self._im_provider = im_provider
        self._outline = outline  # legacy

    def _get_doc(self) -> DocProvider:
        if self._doc_provider is None:
            self._doc_provider = get_doc_provider()
        return self._doc_provider

    def _get_im(self) -> IMProvider:
        if self._im_provider is None:
            self._im_provider = get_im_provider()
        return self._im_provider

    def _get_outline(self) -> OutlineClient:
        """legacy — Outline 直接调用（部分老代码还在用）。"""
        if self._outline is None:
            from offboarding_flow.outline.client import get_outline_client

            self._outline = get_outline_client()
        return self._outline

    # ------------------------------------------------------------------ #
    # 1. 用 LLM 提取
    # ------------------------------------------------------------------ #

    async def extract(self, raw_text: str) -> MeetingExtract:
        """调 GLM 提取结构化字段。"""
        if not raw_text or not raw_text.strip():
            raise ValueError("会议纪要原文不能为空")

        # 关掉 disclaimer/header — 我们要的是纯 JSON
        result = await self.llm.complete(
            EXTRACT_MEETING_PROMPT,
            {"raw_text": raw_text.strip()},
            with_disclaimer=False,
            with_header=False,
            timeout=90.0,  # 提取任务给久一点（GLM-4-flash 2000字 prompt 实测 45s）
        )
        if not result:
            raise RuntimeError("LLM 提取失败（超时 / 空返回）")

        cleaned = _strip_json_fences(result)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning("[meeting] JSON 解析失败 raw=%r", cleaned[:200])
            raise RuntimeError(f"LLM 返回不是合法 JSON: {e}") from e

        extract = MeetingExtract(
            title=str(data.get("title", "未命名会议")).strip()[:50],
            summary=str(data.get("summary", "")).strip(),
            tasks=[Task.from_dict(t) for t in data.get("tasks", []) if isinstance(t, dict)],
            blockers=[
                Blocker.from_dict(b) for b in data.get("blockers", []) if isinstance(b, dict)
            ],
            decisions=[
                Decision.from_dict(d) for d in data.get("decisions", []) if isinstance(d, dict)
            ],
            raw_text=raw_text.strip(),
        )
        # 后处理：把 unknown/无效 owner 兜底到原文里第一个 mention 的 valid username
        return await self._normalize_owners(extract)

    async def _normalize_owners(self, extract: MeetingExtract) -> MeetingExtract:
        """LLM extract owner 偏差兜底：
        - 收集原文里出现的所有 `xxx.yyy` 格式 username
        - 若 owner 是 unknown/空/无效，回退到第一个 mention 的 username
        - 若全部 mention 都找不到，保持 unknown（不强行编）
        """
        INVALID = {"unknown", "", "n/a", "未指定", "tbd", "未知", "none", "null"}
        # 1. 从原文里抓 valid usernames（pattern: lowercase.dotted）
        mentions = re.findall(
            r"\b([a-z][a-z0-9]{1,15}\.[a-z][a-z0-9]{1,15})\b", extract.raw_text.lower()
        )
        # 去重保序
        seen: set[str] = set()
        ordered_mentions: list[str] = []
        for m in mentions:
            if m not in seen:
                seen.add(m)
                ordered_mentions.append(m)
        if not ordered_mentions:
            return extract  # 原文没 username，没法 fallback
        # 2. 优先按 fallback_pool 第一个；按出现顺序选
        fallback = ordered_mentions[0]

        def _fix(owner: str | None) -> str | None:
            if not owner or owner.strip().lower() in INVALID:
                return fallback
            cleaned = owner.strip().lower()
            # 已经是 valid username 格式 → 保留
            if re.match(r"^[a-z][a-z0-9]{1,15}\.[a-z][a-z0-9]{1,15}$", cleaned):
                return cleaned
            # 中文名 / 其他乱码 → fallback
            return fallback

        from dataclasses import replace as _replace

        fixed_tasks = [_replace(t, owner=_fix(t.owner) or "unknown") for t in extract.tasks]
        fixed_blockers = [_replace(b, owner=_fix(b.owner)) for b in extract.blockers]
        fixed_decisions = [_replace(d, made_by=_fix(d.made_by)) for d in extract.decisions]
        return _replace(
            extract, tasks=fixed_tasks, blockers=fixed_blockers, decisions=fixed_decisions
        )

    # ------------------------------------------------------------------ #
    # 2. 渲染 markdown
    # ------------------------------------------------------------------ #

    @staticmethod
    def _mm_user_link(username: str) -> str:
        """把 @username 渲染成可点击的 markdown link，跳到 Mattermost DM。

        Outline doc 不像 Mattermost channel 那样自动识别裸 @username。
        把 @ 写成 markdown link，用户点击直接跳到 MM DM 页（@通知由 MM 端的 DM/channel 真发）。
        """
        try:
            settings = get_settings()
            mm_url = (settings.mattermost_url or "").rstrip("/")
            team = settings.mattermost_team or "laios"
        except Exception:
            mm_url, team = "http://192.168.2.44:8065", "laios"
        if not username:
            return ""
        return f"[**@{username}**]({mm_url}/{team}/messages/@{username})"

    def render_markdown(self, extract: MeetingExtract, ingested_by: str) -> str:
        """把 MeetingExtract 渲染成 Outline 文档内容（markdown）。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines: list[str] = []
        lines.append(
            f"> 🤖 由 AI 从会议纪要自动提取 · 录入人 {self._mm_user_link(ingested_by)} · {now}"
        )
        lines.append("")
        if extract.summary:
            lines.append(f"**摘要**：{extract.summary}")
            lines.append("")

        # 任务
        lines.append("## 📋 任务清单")
        if extract.tasks:
            for t in extract.tasks:
                due = f" · 截止 {t.due_date}" if t.due_date else ""
                prio = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}.get(
                    t.priority, t.priority
                )
                lines.append(f"- [ ] {self._mm_user_link(t.owner)} — {t.text} _{prio}{due}_")
        else:
            lines.append("_无明确任务_")
        lines.append("")

        # 卡点
        lines.append("## ⚠️ 卡点")
        if extract.blockers:
            for b in extract.blockers:
                owner = f" {self._mm_user_link(b.owner)}" if b.owner else ""
                lines.append(f"- {b.description}{owner} _(严重度: {b.severity})_")
        else:
            lines.append("_暂无_")
        lines.append("")

        # 决策
        lines.append("## ✅ 决策")
        if extract.decisions:
            for d in extract.decisions:
                by = f" — _by {self._mm_user_link(d.made_by)}_" if d.made_by else ""
                lines.append(f"- **{d.decision}**{by}")
                if d.impact:
                    lines.append(f"  - 影响：{d.impact}")
        else:
            lines.append("_暂无_")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## 📝 原始纪要")
        lines.append("")
        lines.append(extract.raw_text)
        lines.append("")
        lines.append("---")
        lines.append("> *由 AI 生成 — 所有建议必须经人工确认后执行；AI 不会自动操作任何节点*")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # 3. 推到 Outline
    # ------------------------------------------------------------------ #

    async def publish_to_outline(
        self, extract: MeetingExtract, ingested_by: str
    ) -> dict[str, str] | None:
        """在 Outline 创建文档；失败返回 None（不抛，让分发继续）。"""
        try:
            outline = self._get_outline()
            collection = await outline.ensure_collection(DEFAULT_COLLECTION_NAME)
            md = self.render_markdown(extract, ingested_by)
            doc = await outline.create_document(
                title=extract.title,
                text=md,
                collection_id=collection["id"],
                publish=True,
            )
            settings = get_settings()
            # Outline 返回的 url 是相对路径（如 /doc/xxx-abc）；拼完整 URL
            full_url = settings.outline_url.rstrip("/") + str(doc.get("url", ""))
            return {"id": doc["id"], "url": full_url, "title": extract.title}
        except (OutlineError, Exception) as e:
            logger.warning("[meeting] Outline 写入失败（降级，仅推 MM）: %s", e)
            return None

    # ------------------------------------------------------------------ #
    # 4. 渲染 channel / DM 文案
    # ------------------------------------------------------------------ #

    def render_channel_summary(
        self, extract: MeetingExtract, doc_info: dict[str, str] | None
    ) -> str:
        lines: list[str] = []
        lines.append(f"## 📋 {extract.title}")
        if extract.summary:
            lines.append(f"> {extract.summary}")
        lines.append("")
        if doc_info:
            lines.append(f"**协作文档**: [{doc_info['title']}]({doc_info['url']})")
            lines.append("")
        # 任务概览（同时 @ 各 owner 让 MM 自动通知）
        if extract.tasks:
            lines.append(f"**📌 任务分配（{len(extract.tasks)}）**:")
            for t in extract.tasks:
                due = f" · _截止 {t.due_date}_" if t.due_date else ""
                lines.append(f"- @{t.owner} — {t.text}{due}")
        if extract.blockers:
            lines.append("")
            lines.append(f"**⚠️ 卡点（{len(extract.blockers)}）**:")
            for b in extract.blockers:
                owner = f" @{b.owner}" if b.owner else ""
                lines.append(f"- {b.description}{owner}")
        if extract.decisions:
            lines.append("")
            lines.append(f"**✅ 决策（{len(extract.decisions)}）**:")
            for d in extract.decisions:
                lines.append(f"- {d.decision}")
        lines.append("")
        lines.append("_已私 DM 提醒各负责人 · 由 AI 生成需人工确认_")
        return "\n".join(lines)

    def render_owner_dm(self, owner: str, extract: MeetingExtract) -> str:
        """[fallback] LLM 不可用时的规则版 DM（被 generate_personal_brief 取代）。"""
        my_tasks = [t for t in extract.tasks if t.owner == owner]
        my_blockers = [b for b in extract.blockers if b.owner == owner]
        my_decisions = [d for d in extract.decisions if d.made_by == owner]

        lines: list[str] = [f"📋 **会议「{extract.title}」中你的任务**", ""]
        if my_tasks:
            for t in my_tasks:
                due = f" · _截止 {t.due_date}_" if t.due_date else ""
                prio = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t.priority, "")
                lines.append(f"- {prio} {t.text}{due}")
        else:
            lines.append("_无任务_")
        if my_blockers:
            lines.append("")
            lines.append("**⚠️ 相关卡点**:")
            for b in my_blockers:
                lines.append(f"- {b.description}")
        if my_decisions:
            lines.append("")
            lines.append("**✅ 你的决策**:")
            for d in my_decisions:
                lines.append(f"- {d.decision}")
        lines.append("")
        lines.append("_AI 提取规则版，未走个性化分析_")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # 5. 第二层分析：个人 brief（每个 owner 单独 AI 调用）
    # ------------------------------------------------------------------ #

    async def generate_personal_brief(self, extract: MeetingExtract, owner: str) -> str:
        """给单个 owner 调 LLM 生成个性化分析（"你的关键 3 件事 / 你面临的卡点 / 建议"）。

        LLM 失败时降级到 render_owner_dm 规则版。
        """
        my_tasks = [t for t in extract.tasks if t.owner == owner]
        my_blockers = [b for b in extract.blockers if b.owner == owner]
        my_decisions = [d for d in extract.decisions if d.made_by == owner]

        # 组上下文（不传完整 raw_text，给 LLM 已结构化的字段）
        ctx = {
            "meeting_title": extract.title,
            "meeting_summary": extract.summary or "（无摘要）",
            "owner": owner,
            "my_tasks_json": json.dumps([_task_to_dict(t) for t in my_tasks], ensure_ascii=False),
            "my_blockers_json": json.dumps(
                [_blocker_to_dict(b) for b in my_blockers], ensure_ascii=False
            ),
            "my_decisions_json": json.dumps(
                [_decision_to_dict(d) for d in my_decisions], ensure_ascii=False
            ),
            "all_tasks_brief": ", ".join(f"{t.owner}: {t.text[:30]}" for t in extract.tasks[:10])
            or "（无）",
            "all_decisions_brief": ", ".join(d.decision[:40] for d in extract.decisions[:5])
            or "（无）",
        }
        brief = await self.llm.complete(
            PERSONAL_BRIEF_PROMPT,
            ctx,
            with_disclaimer=True,
            with_header=True,
            timeout=20.0,
        )
        if brief:
            return brief
        # 降级
        logger.warning("[meeting] personal brief LLM 失败，降级规则版 owner=%s", owner)
        return self.render_owner_dm(owner, extract)

    # ------------------------------------------------------------------ #
    # 6. 第二层分析：管理层执行摘要（给 channel 公共文档）
    # ------------------------------------------------------------------ #

    async def generate_executive_brief(self, extract: MeetingExtract) -> str:
        """给 channel 公共文档头部一段管理层视角执行摘要。LLM 失败返回空字符串。"""
        ctx = {
            "meeting_title": extract.title,
            "meeting_summary": extract.summary or "（无）",
            "n_tasks": len(extract.tasks),
            "n_blockers": len(extract.blockers),
            "n_decisions": len(extract.decisions),
            "all_tasks_brief": "; ".join(f"@{t.owner} {t.text[:40]}" for t in extract.tasks[:8])
            or "（无）",
            "all_blockers_brief": "; ".join(b.description[:40] for b in extract.blockers[:5])
            or "（无）",
            "all_decisions_brief": "; ".join(d.decision[:40] for d in extract.decisions[:5])
            or "（无）",
        }
        brief = await self.llm.complete(
            EXECUTIVE_BRIEF_PROMPT,
            ctx,
            with_disclaimer=False,
            with_header=False,
            timeout=20.0,
        )
        return brief or ""

    # ------------------------------------------------------------------ #
    # 7. 逐项深度分析（每条 task/blocker/decision 单独 LLM；asyncio.gather 并发）
    # ------------------------------------------------------------------ #

    async def analyze(self, extract: MeetingExtract) -> AnalyzedMeeting:
        """对每条任务 / 卡点 / 决策都单独调 LLM，asyncio.gather 并发。"""
        # 组共享上下文
        all_tasks_brief = (
            "; ".join(f"@{t.owner} {t.text[:30]}" for t in extract.tasks[:10]) or "（无）"
        )
        all_blockers_brief = "; ".join(b.description[:30] for b in extract.blockers[:5]) or "（无）"

        async def _analyze_one_task(t: Task) -> AnalyzedTask:
            # 同 owner 的卡点 / 决策当上下文
            related_blockers = (
                "; ".join(b.description[:30] for b in extract.blockers if b.owner == t.owner)
                or "（无）"
            )
            related_decisions = (
                "; ".join(d.decision[:30] for d in extract.decisions if d.made_by == t.owner)
                or "（无）"
            )
            brief = await self.llm.complete(
                ANALYZE_TASK_PROMPT,
                {
                    "meeting_title": extract.title,
                    "owner": t.owner,
                    "task_text": t.text,
                    "priority": t.priority,
                    "due_date": t.due_date or "未定",
                    "all_tasks_brief": all_tasks_brief,
                    "related_decisions": related_decisions,
                    "related_blockers": related_blockers,
                },
                with_disclaimer=False,
                with_header=False,
                timeout=20.0,
            )
            return AnalyzedTask(task=t, ai_brief=brief or "_(AI 分析降级)_")

        async def _analyze_one_blocker(b: Blocker) -> AnalyzedBlocker:
            related_tasks = (
                "; ".join(f"@{t.owner} {t.text[:30]}" for t in extract.tasks if t.owner == b.owner)
                or "（无）"
            )
            related_decisions = (
                "; ".join(d.decision[:30] for d in extract.decisions if d.made_by == b.owner)
                or "（无）"
            )
            brief = await self.llm.complete(
                ANALYZE_BLOCKER_PROMPT,
                {
                    "meeting_title": extract.title,
                    "blocker_text": b.description,
                    "owner": b.owner or "未指定",
                    "severity": b.severity,
                    "related_tasks": related_tasks,
                    "related_decisions": related_decisions,
                },
                with_disclaimer=False,
                with_header=False,
                timeout=20.0,
            )
            return AnalyzedBlocker(blocker=b, ai_brief=brief or "_(AI 分析降级)_")

        async def _analyze_one_decision(d: Decision) -> AnalyzedDecision:
            brief = await self.llm.complete(
                ANALYZE_DECISION_PROMPT,
                {
                    "meeting_title": extract.title,
                    "decision_text": d.decision,
                    "made_by": d.made_by or "未指定",
                    "impact": d.impact or "未说明",
                    "all_tasks_brief": all_tasks_brief,
                    "all_blockers_brief": all_blockers_brief,
                },
                with_disclaimer=False,
                with_header=False,
                timeout=20.0,
            )
            return AnalyzedDecision(decision=d, ai_brief=brief or "_(AI 分析降级)_")

        # 并发 gather 所有分析（含 executive brief）
        task_coros = [_analyze_one_task(t) for t in extract.tasks]
        blocker_coros = [_analyze_one_blocker(b) for b in extract.blockers]
        decision_coros = [_analyze_one_decision(d) for d in extract.decisions]
        exec_coro = self.generate_executive_brief(extract)

        results = await asyncio.gather(
            *task_coros,
            *blocker_coros,
            *decision_coros,
            exec_coro,
            return_exceptions=True,
        )

        n_tasks = len(task_coros)
        n_blockers = len(blocker_coros)
        n_decisions = len(decision_coros)

        analyzed_tasks: list[AnalyzedTask] = []
        analyzed_blockers: list[AnalyzedBlocker] = []
        analyzed_decisions: list[AnalyzedDecision] = []
        for i in range(n_tasks):
            r = results[i]
            if isinstance(r, AnalyzedTask):
                analyzed_tasks.append(r)
            else:
                logger.warning("[meeting] task analyze failed: %s", r)
                analyzed_tasks.append(
                    AnalyzedTask(task=extract.tasks[i], ai_brief="_(AI 分析降级)_")
                )
        for i in range(n_blockers):
            r = results[n_tasks + i]
            if isinstance(r, AnalyzedBlocker):
                analyzed_blockers.append(r)
            else:
                logger.warning("[meeting] blocker analyze failed: %s", r)
                analyzed_blockers.append(
                    AnalyzedBlocker(blocker=extract.blockers[i], ai_brief="_(AI 分析降级)_")
                )
        for i in range(n_decisions):
            r = results[n_tasks + n_blockers + i]
            if isinstance(r, AnalyzedDecision):
                analyzed_decisions.append(r)
            else:
                logger.warning("[meeting] decision analyze failed: %s", r)
                analyzed_decisions.append(
                    AnalyzedDecision(decision=extract.decisions[i], ai_brief="_(AI 分析降级)_")
                )

        exec_brief_result = results[-1]
        exec_brief = exec_brief_result if isinstance(exec_brief_result, str) else ""

        return AnalyzedMeeting(
            extract=extract,
            tasks=analyzed_tasks,
            blockers=analyzed_blockers,
            decisions=analyzed_decisions,
            executive_brief=exec_brief,
        )

    # ------------------------------------------------------------------ #
    # 8. 渲染 Analyzed 版 markdown（公共文档 + DM 文案都用这个）
    # ------------------------------------------------------------------ #

    def render_analyzed_markdown(self, analyzed: AnalyzedMeeting, ingested_by: str) -> str:
        """完整版 — 公共文档用（包含每项的 AI 深度分析）。"""
        extract = analyzed.extract
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines: list[str] = []
        lines.append(
            f"> 🤖 由 AI 从会议纪要自动提取并深度分析 · 录入人 {self._mm_user_link(ingested_by)} · {now}"
        )
        lines.append("")
        if extract.summary:
            lines.append(f"**摘要**：{extract.summary}")
            lines.append("")
        if analyzed.executive_brief:
            lines.append("## 📊 管理层执行摘要")
            lines.append(analyzed.executive_brief)
            lines.append("")

        # 任务
        lines.append(f"## 📋 任务清单（{len(analyzed.tasks)}）")
        if analyzed.tasks:
            for at in analyzed.tasks:
                t = at.task
                due = f" · 截止 {t.due_date}" if t.due_date else ""
                prio = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}.get(
                    t.priority, t.priority
                )
                lines.append(f"### {self._mm_user_link(t.owner)} — {t.text}")
                lines.append(f"_{prio}{due}_")
                lines.append("")
                lines.append(at.ai_brief)
                lines.append("")
        else:
            lines.append("_无任务_")
            lines.append("")

        # 卡点
        lines.append(f"## ⚠️ 卡点（{len(analyzed.blockers)}）")
        if analyzed.blockers:
            for ab in analyzed.blockers:
                b = ab.blocker
                owner = f" {self._mm_user_link(b.owner)}" if b.owner else ""
                lines.append(f"### {b.description}{owner}")
                lines.append(f"_严重度：{b.severity}_")
                lines.append("")
                lines.append(ab.ai_brief)
                lines.append("")
        else:
            lines.append("_暂无_")
            lines.append("")

        # 决策
        lines.append(f"## ✅ 决策（{len(analyzed.decisions)}）")
        if analyzed.decisions:
            for ad in analyzed.decisions:
                d = ad.decision
                by = f" — _by {self._mm_user_link(d.made_by)}_" if d.made_by else ""
                lines.append(f"### {d.decision}{by}")
                if d.impact:
                    lines.append(f"_影响：{d.impact}_")
                lines.append("")
                lines.append(ad.ai_brief)
                lines.append("")
        else:
            lines.append("_暂无_")
            lines.append("")

        lines.append("---")
        lines.append("## 📝 原始纪要")
        lines.append("")
        lines.append(extract.raw_text)
        lines.append("")
        lines.append("---")
        lines.append("> *由 AI 生成 — 所有建议必须经人工确认后执行；AI 不会自动操作任何节点*")
        return "\n".join(lines)

    def render_owner_personal_dm(self, analyzed: AnalyzedMeeting, owner: str) -> str:
        """按 owner 聚合 ta 相关的所有 AI 深度分析（任务 + 卡点 + 决策）成一条 DM。"""
        extract = analyzed.extract
        my_tasks = [at for at in analyzed.tasks if at.task.owner == owner]
        my_blockers = [ab for ab in analyzed.blockers if ab.blocker.owner == owner]
        my_decisions = [ad for ad in analyzed.decisions if ad.decision.made_by == owner]

        lines: list[str] = []
        lines.append(f"📋 **会议「{extract.title}」相关你的事项 AI 深度分析**")
        lines.append("")

        if my_tasks:
            lines.append(f"### 🎯 你的任务（{len(my_tasks)}）")
            lines.append("")
            for at in my_tasks:
                t = at.task
                due = f" · _截止 {t.due_date}_" if t.due_date else ""
                lines.append(f"**▸ {t.text}**{due}")
                lines.append("")
                lines.append(at.ai_brief)
                lines.append("")

        if my_blockers:
            lines.append(f"### ⚠️ 涉及你的卡点（{len(my_blockers)}）")
            lines.append("")
            for ab in my_blockers:
                lines.append(f"**▸ {ab.blocker.description}**")
                lines.append("")
                lines.append(ab.ai_brief)
                lines.append("")

        if my_decisions:
            lines.append(f"### ✅ 你的决策（{len(my_decisions)}）")
            lines.append("")
            for ad in my_decisions:
                lines.append(f"**▸ {ad.decision.decision}**")
                lines.append("")
                lines.append(ad.ai_brief)
                lines.append("")

        lines.append("---")
        lines.append("_AI 自动生成；执行前请核对_")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # 9. 端到端 distribute：Outline + channel + 各 owner DM
    # ------------------------------------------------------------------ #

    async def distribute(
        self,
        analyzed: AnalyzedMeeting,
        *,
        ingested_by: str,
        channel_id: str,
        # legacy 兼容参数 — 内部会优先用 Provider 抽象
        mm_post_channel: Callable[[str, str], Awaitable[Any]] | None = None,
        mm_send_dm: Callable[[str, str], Awaitable[Any]] | None = None,
        mm_ensure_in_channel: Callable[[str, str], Awaitable[Any]] | None = None,
    ) -> dict[str, Any]:
        """统一分发 — 走 DocProvider + IMProvider 抽象（可切 Outline/Lark/WeCom/钉钉）。

        0) 同步 user 到目标 doc platform
        1) 创建协作文档
        2) channel 公示
        3) 各 owner 单独 DM
        """
        errors: list[str] = []
        owners = analyzed.extract.owners()

        doc_provider = self._get_doc()
        im_provider = self._get_im()

        # 0a. 同步 owner 到 doc platform（让文档 mention 真链接）
        try:
            sync = await self._ensure_users_synced(owners)
            if sync.get("created"):
                logger.info(
                    "[meeting] %s 同步 created=%s",
                    doc_provider.name,
                    sync["created"],
                )
        except Exception as e:
            logger.warning("[meeting] users sync 失败: %s", e)
            errors.append(f"users_sync: {e}")

        # 0b. ensure owner 在 IM channel 里
        for o in owners:
            try:
                await im_provider.ensure_user_in_channel(channel_id, o)
            except Exception as e:
                logger.debug("[meeting] add %s to channel: %s", o, e)

        # 1. 创建协作文档
        md = self.render_analyzed_markdown(analyzed, ingested_by)
        doc_url: str | None = None
        try:
            doc_info: DocInfo = await doc_provider.create_document(
                title=analyzed.extract.title,
                markdown=md,
                owner_usernames=owners,
            )
            doc_url = doc_info.url
        except Exception as e:
            logger.warning(
                "[meeting] %s create_document 失败（继续 IM 分发）: %s",
                doc_provider.name,
                e,
            )
            errors.append(f"{doc_provider.name}_doc: {e}")

        # 2. channel 公示
        channel_msg = self._render_channel_announce(analyzed, doc_url)
        try:
            await im_provider.post_to_channel(channel_id, channel_msg)
        except Exception as e:
            logger.warning("[meeting] channel post 失败: %s", e)
            errors.append(f"channel: {e}")

        # 3. 各 owner DM（并发，每人独立分析）
        async def _dm(owner: str) -> tuple[str, str | None]:
            try:
                msg = self.render_owner_personal_dm(analyzed, owner)
                await im_provider.send_dm(owner, msg)
                return owner, None
            except Exception as e:
                logger.warning("[meeting] DM %s 失败: %s", owner, e)
                return owner, str(e)

        results = await asyncio.gather(*[_dm(o) for o in owners], return_exceptions=False)
        notified = [o for o, err in results if err is None]
        for o, err in results:
            if err:
                errors.append(f"dm {o}: {err}")

        return {
            "doc_url": doc_url,
            "doc_provider": doc_provider.name,
            "im_provider": im_provider.name,
            "owners_notified": notified,
            "errors": errors,
        }

    def _render_channel_announce(self, analyzed: AnalyzedMeeting, doc_url: str | None) -> str:
        """channel 公示文案（短版 — 完整在 Outline 文档）。"""
        extract = analyzed.extract
        lines: list[str] = []
        lines.append(f"## 📋 {extract.title}")
        if extract.summary:
            lines.append(f"> {extract.summary}")
        if analyzed.executive_brief:
            lines.append("")
            lines.append(analyzed.executive_brief)
        lines.append("")
        if doc_url:
            lines.append(f"📄 **协作文档**（含逐项 AI 深度分析）：{doc_url}")
            lines.append("")
        if extract.tasks:
            lines.append(f"**📌 任务分配（{len(extract.tasks)}）**：")
            for t in extract.tasks:
                due = f" · _截止 {t.due_date}_" if t.due_date else ""
                lines.append(f"- @{t.owner} — {t.text}{due}")
        if extract.blockers:
            lines.append("")
            lines.append(f"**⚠️ 卡点（{len(extract.blockers)}）**：")
            for b in extract.blockers:
                owner = f" @{b.owner}" if b.owner else ""
                lines.append(f"- {b.description}{owner}")
        if extract.decisions:
            lines.append("")
            lines.append(f"**✅ 决策（{len(extract.decisions)}）**：")
            for d in extract.decisions:
                by = f" — @{d.made_by}" if d.made_by else ""
                lines.append(f"- {d.decision}{by}")
        lines.append("")
        lines.append("_✉️ 已私 DM 提醒各负责人个性化 AI 分析_")
        lines.append("_AI 生成 · 请人工核对后执行_")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # 10. 同步 system users → Outline（按 username 查 system，invite Outline）
    # ------------------------------------------------------------------ #

    async def _ensure_users_synced(self, usernames: list[str]) -> dict[str, list[str]]:
        """同步 system users 表 → 当前 DocProvider。已存在 skip。"""
        if not usernames:
            return {"created": [], "skipped": []}
        from offboarding_flow.state_store.repositories import UserRepository
        from offboarding_flow.state_store.session import new_session

        invite_payloads: list[dict[str, str]] = []
        async with new_session() as session:
            repo = UserRepository(session)
            for username in usernames:
                user = await repo.get_by_username(username)
                if user is None:
                    invite_payloads.append(
                        {
                            "username": username,
                            "email": f"{username}@demo.local",
                            "name": username,
                            "role": "member",
                        }
                    )
                else:
                    invite_payloads.append(
                        {
                            "username": user.username,
                            "email": user.email,
                            "name": user.display_name or user.username,
                            "role": "admin" if user.role in ("hr_admin", "admin") else "member",
                        }
                    )
        return await self._get_doc().ensure_users(invite_payloads)


def _task_to_dict(t: Task) -> dict[str, Any]:
    return {"text": t.text, "due_date": t.due_date, "priority": t.priority}


def _blocker_to_dict(b: Blocker) -> dict[str, Any]:
    return {"description": b.description, "severity": b.severity}


def _decision_to_dict(d: Decision) -> dict[str, Any]:
    return {"decision": d.decision, "impact": d.impact}
