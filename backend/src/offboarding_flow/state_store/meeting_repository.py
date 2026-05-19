"""MeetingRepository — 会议纪要 CRUD（Meeting v1 / pageindex 风格 RAG 数据源）。

设计要点：
- save(): bot 收到纪要 → GLM 提炼后入库（一次写 raw + summary + extract_json）
- list_recent(): 给 RAG 路由用 — 返回 [(id, title, summary, ai_doc_url)] 让 LLM 当 TOC
- get_raw(): 拿 raw_text 喂 GLM 回答
- search_by_title(): 关键词粗匹配（v1 用 ILIKE，v2 可换 PG 全文检索 / pgvector）
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.state_store.models import Meeting


class MeetingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        *,
        title: str,
        raw_text: str,
        summary: str | None = None,
        extract_json: dict | None = None,
        source_url: str | None = None,
        ai_doc_url: str | None = None,
        ingested_by: str | None = None,
        chat_id: str | None = None,
    ) -> Meeting:
        m = Meeting(
            title=title[:255],
            raw_text=raw_text,
            summary=summary,
            extract_json=extract_json or {},
            source_url=source_url,
            ai_doc_url=ai_doc_url,
            ingested_by=ingested_by,
            chat_id=chat_id,
        )
        self.session.add(m)
        await self.session.flush()
        return m

    async def list_recent(self, limit: int = 30) -> list[Meeting]:
        stmt = select(Meeting).order_by(desc(Meeting.ingested_at)).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, meeting_id: uuid.UUID) -> Meeting | None:
        return await self.session.get(Meeting, meeting_id)

    async def get_many(self, ids: list[uuid.UUID]) -> list[Meeting]:
        if not ids:
            return []
        stmt = select(Meeting).where(Meeting.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def search_by_title(self, query: str, limit: int = 10) -> list[Meeting]:
        """关键词在 title / summary 里粗匹配（ILIKE）。"""
        like = f"%{query}%"
        stmt = (
            select(Meeting)
            .where((Meeting.title.ilike(like)) | (Meeting.summary.ilike(like)))
            .order_by(desc(Meeting.ingested_at))
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


__all__ = ["MeetingRepository"]
