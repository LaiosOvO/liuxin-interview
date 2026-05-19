"""飞书 (Lark) WebSocket 长连接 bot listener。

设计要点
========

- **WebSocket 长连接模式**：lark-oapi SDK 自带长连接（飞书称 "事件订阅长连接"），
  无需 HTTPS / 公网 IP / 域名 — 飞书强烈推荐演示场景用此模式。
- **SDK 是同步阻塞型**：`lark.ws.Client.start()` 内部跑自己的 asyncio loop。
  我们在独立后台线程里跑，通过 `asyncio.run_coroutine_threadsafe` 把事件
  桥接到 FastAPI 主 loop 处理。
- **演示约定（v1）**：路景智一个飞书账号扮演所有角色。bot 收到的第一条
  @ 消息会自动学习 sender 的 open_id（如果配置没填），后续 bot 主动 @ 时
  消息开头加 `【XX 身份】` 标签 — 见 memory/project_single_user_multi_role.md。

事件处理
========
- `im.message.receive_v1`：@ bot 时触发；handler 提取消息文本 → 调
  `MeetingService.extract` 用 GLM 总结 → 调 `LarkDocsProvider.create_document`
  创建飞书 docx → 反馈文档链接给用户。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from offboarding_flow.config import Settings, get_settings

logger = logging.getLogger(__name__)

# 全局单例 — start 时初始化，stop 时清理
_listener: "LarkListener | None" = None
# 主 FastAPI loop 引用（SDK 线程回调要桥接到这）
_main_loop: asyncio.AbstractEventLoop | None = None


class LarkListener:
    """飞书 WebSocket bot listener — 在后台线程跑 lark.ws.Client。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread: threading.Thread | None = None
        self._cli: Any = None  # lark.ws.Client（lark-oapi 进程内同步对象）
        # 学习到的 demo owner open_id（首次收到消息时回填）
        self._learned_owner_open_id: str = settings.lark_demo_owner_open_id or ""

    # ------------------------------------------------------------------ #
    # 启动 / 停止
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """启动 listener — 同步返回，listener 线程后台跑。"""
        if self._thread and self._thread.is_alive():
            logger.warning("[lark_listener] already running, skip")
            return
        self._thread = threading.Thread(
            target=self._run_forever,
            name="lark-ws-listener",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[lark_listener] 启动（WebSocket 长连接, app_id=%s, demo_mode=%s）",
            self.settings.lark_app_id[:12] + "...",
            self.settings.lark_demo_mode,
        )

    def stop(self) -> None:
        """停止 listener — SDK 没有干净的 stop API，线程是 daemon 会随进程退出。"""
        logger.info("[lark_listener] 停止信号（daemon 线程随进程退出）")

    # ------------------------------------------------------------------ #
    # 内部 — 后台线程跑 SDK
    # ------------------------------------------------------------------ #

    def _run_forever(self) -> None:
        try:
            import lark_oapi as lark
        except ImportError:
            logger.error("[lark_listener] lark-oapi 未安装 — 跑 `pip install lark-oapi`. 跳过启动")
            return

        # 构造事件 dispatcher — 注册 im.message.receive_v1
        event_handler = (
            lark.EventDispatcherHandler.builder(
                self.settings.lark_app_id,  # encrypt_key 长连接模式可空
                self.settings.lark_app_id,  # verification_token 长连接模式可空
            )
            .register_p2_im_message_receive_v1(self._on_message_receive)
            .build()
        )

        self._cli = lark.ws.Client(
            self.settings.lark_app_id,
            self.settings.lark_app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        try:
            logger.info("[lark_listener] 长连接 connecting...")
            self._cli.start()  # 同步阻塞，内部跑 SDK 自己的 loop
        except Exception as exc:
            logger.exception("[lark_listener] client.start fatal: %s", exc)

    # ------------------------------------------------------------------ #
    # 事件 handler — 在 SDK 线程触发，要桥接到主 loop
    # ------------------------------------------------------------------ #

    def _on_message_receive(self, data: Any) -> None:
        """SDK 线程回调入口 — 把事件丢回主 loop 异步处理。"""
        global _main_loop
        if _main_loop is None or not _main_loop.is_running():
            logger.warning("[lark_listener] main loop not ready, drop event")
            return
        try:
            asyncio.run_coroutine_threadsafe(self._handle_message_async(data), _main_loop)
        except Exception as exc:
            logger.exception("[lark_listener] dispatch to main loop failed: %s", exc)

    async def _handle_message_async(self, data: Any) -> None:
        """主 loop 异步处理 — 提取文本 → GLM 总结 → 创建飞书文档 → 回复。"""
        try:
            event = getattr(data, "event", None)
            if event is None:
                return
            message = getattr(event, "message", None)
            sender = getattr(event, "sender", None)
            if message is None:
                return

            # 学习 demo owner open_id（首次收到 @ 消息时回填）
            sender_open_id = ""
            if sender is not None:
                sid = getattr(sender, "sender_id", None)
                if sid is not None:
                    sender_open_id = getattr(sid, "open_id", "") or ""
            if not self._learned_owner_open_id and sender_open_id:
                self._learned_owner_open_id = sender_open_id
                logger.info(
                    "[lark_listener] 学习到 demo owner open_id=%s",
                    sender_open_id,
                )

            # 解析 sender 真实身份（name / email / mobile）— 让 bot 知道是谁说话
            sender_info = await self._resolve_sender(sender_open_id) if sender_open_id else {}
            sender_name = sender_info.get("name", "未知用户")
            sender_email = sender_info.get("email", "")

            # 提取消息文本
            msg_text = self._extract_text(message)
            chat_id = getattr(message, "chat_id", "")
            message_id = getattr(message, "message_id", "")
            chat_type = getattr(message, "chat_type", "")  # p2p / group

            logger.info(
                "[lark_listener] 收到消息 chat_type=%s chat_id=%s len=%d sender_name=%s sender_email=%s open_id=%s...",
                chat_type,
                chat_id,
                len(msg_text),
                sender_name,
                sender_email,
                sender_open_id[:16],
            )

            # ===== 优先：消息里有飞书文档链接 → 直接去拉文档原文 → 总结 =====
            doc_urls = self._extract_feishu_doc_urls(msg_text)
            if doc_urls:
                logger.info("[lark_listener] 识别到飞书文档链接: %s", doc_urls)
                await self._reply_text(
                    chat_id,
                    message_id,
                    f"【bot】{sender_name} 收到 ✅ 我去拉取文档原文（{len(doc_urls)} 篇）→ AI 总结 → 回 @ 您",
                )
                await self._process_meeting_from_doc_urls(
                    doc_urls=doc_urls,
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_email=sender_email,
                    sender_open_id=sender_open_id,
                )
                return

            # ===== 意图路由：先用 LLM intent agent 推理，失败降级到关键词 =====
            try:
                intent = await self._llm_classify_intent(msg_text)
                logger.info("[lark_listener] LLM intent=%s msg_len=%d", intent, len(msg_text))
            except Exception as exc:
                logger.warning("[lark_listener] LLM intent fail (降级关键词): %s", exc)
                intent = self._classify_intent(msg_text)
                logger.info("[lark_listener] fallback intent=%s", intent)

            if intent == "offboarding":
                # 离职流程命令 → 走 dispatch_message
                await self._handle_offboarding_command(
                    msg_text=msg_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_email=sender_email,
                    sender_open_id=sender_open_id,
                    chat_type=chat_type,
                )
                return

            if intent == "summarize":
                await self._handle_summarize_request(
                    request=msg_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_open_id=sender_open_id,
                )
                return

            if intent == "list_docs":
                await self._list_accessible_docs_and_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_open_id=sender_open_id,
                )
                return

            if intent == "meeting":
                # 任何会议相关问题 → RAG
                await self._handle_qa(
                    question=msg_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_open_id=sender_open_id,
                )
                return

            # ===== "帮我总结 XX 会议" → 从 DB 检索 → 渲染总结 → 写"协作文档1" =====
            if (
                any(
                    k in msg_text for k in ("帮我总结", "总结一下", "总结下", "总结下", "summarize")
                )
                and len(msg_text) < 80
            ):
                await self._handle_summarize_request(
                    request=msg_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_open_id=sender_open_id,
                )
                return

            # ===== "回编号选文档" → 从上次列表 cache 拿 doc_id → 拉总结 =====
            chosen = self._parse_doc_choice(msg_text, chat_id)
            if chosen is not None:
                await self._reply_text(
                    chat_id,
                    message_id,
                    f"【bot】{sender_name} 选了 **{chosen['name']}** ✅ 我去拉原文 → 总结 → 回 @ 您",
                )
                await self._process_meeting_from_doc_urls(
                    doc_urls=[chosen["doc_url"]],
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_email=sender_email,
                    sender_open_id=sender_open_id,
                )
                return

            # ===== 显式命令：列文档（"列文档" / "list" / "文档列表"）=====
            if any(k in msg_text for k in ("列文档", "文档列表", "list docs", "查文档")):
                await self._list_accessible_docs_and_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_open_id=sender_open_id,
                )
                return

            # ===== 纯问候 / 帮助 — 不走 RAG =====
            if self._is_greeting_or_help(msg_text):
                identity_line = f"识别到您是 **{sender_name}**" if sender_name != "未知用户" else ""
                await self._reply_text(
                    chat_id,
                    message_id,
                    f"【bot】您好，{identity_line}\n"
                    "我支持以下能力 ✨\n\n"
                    "**1. 任何问题 → 自动 RAG 答**\n"
                    "  • 例如 `项目 X 讨论了什么`, `谁负责设备归还`\n"
                    "  • 我自动匹配相关文档，AI 回答 + @ 您\n\n"
                    "**2. 文档总结**\n"
                    "  • 贴飞书 doc 链接 / 粘纪要文本（>200 字） → AI 提炼新文档\n"
                    "  • `列文档` → 看 bot 可访问的文档列表，回编号选\n\n"
                    "**3. 离职流程**\n"
                    "  • `我要离职` — 起流程",
                )
                return

            # ===== 默认：长文本 → 总结；短文本 → RAG 问答 =====
            # 默认行为：把消息当成"问会议内容"，自动 RAG（用户要求：默认 RAG 不要触发词）
            if len(msg_text) > 500:
                # 长文本（粘贴的会议纪要原文）→ 走 GLM 提炼
                pass  # 跳过 if/elif，落到下面的 should_process 分支
            elif intent != "offboarding":
                # 默认走 RAG（即使没问号，也尝试找文档回答）
                await self._handle_qa(
                    question=msg_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_name=sender_name,
                    sender_open_id=sender_open_id,
                )
                return

            if intent == "help":
                # 不应该走到这（上面已处理），保留兜底
                identity_line = f"识别到您是 **{sender_name}**" if sender_name != "未知用户" else ""
                await self._reply_text(
                    chat_id,
                    message_id,
                    f"【bot】您好，{identity_line}\n"
                    "我支持两种能力 ✨\n\n"
                    "**1. 离职流程**\n"
                    "  • `我要离职` — 起流程\n"
                    "  • `我的流程` — 查看进度\n"
                    "  • `通过 / 退回 / 拒绝 [意见]` — 节点决策\n\n"
                    "**2. 会议纪要总结**\n"
                    "  • 直接把会议纪要文本（>200 字 或 含「纪要/总结/会议」）发我\n"
                    "  • 我会用 AI 提炼**任务/负责人/卡点/决策**并整理成飞书协作文档",
                )
                return

            # 触发关键词（meeting）：含会议关键词或长度 > 200
            should_process = (
                any(k in msg_text for k in ["总结", "纪要", "提炼", "整理", "会议"])
                or len(msg_text) > 200
            )
            if not should_process:
                await self._reply_text(
                    chat_id,
                    message_id,
                    f"【会议纪要 bot】{sender_name} 您好，没识别到会议关键词。\n"
                    "想让我总结请：① 发送较长的纪要文本（>200 字）或 "
                    "② 消息里包含「总结 / 纪要 / 提炼 / 整理 / 会议」任一关键词。",
                )
                return

            # 先回复"处理中"（带身份确认）
            await self._reply_text(
                chat_id,
                message_id,
                f"【会议纪要 bot】收到 **{sender_name}** 的纪要 ✅\n"
                "正在用 AI 提炼并生成飞书协作文档，请稍候 30s~1min ⏳",
            )

            # 调 MeetingService 处理（把 sender 真实身份传进去，写到文档元信息里）
            await self._process_meeting(
                msg_text,
                chat_id,
                message_id,
                sender_name=sender_name,
                sender_email=sender_email,
                sender_open_id=sender_open_id,
            )

        except Exception as exc:
            logger.exception("[lark_listener] handle message failed: %s", exc)

    # ------------------------------------------------------------------ #
    # 意图分类 — 离职 / 会议 / 帮助
    # ------------------------------------------------------------------ #

    # 离职关键词（覆盖发起 + 决策 + 查询 + 推进）
    _OFFBOARDING_KEYWORDS = (
        "我要离职",
        "申请离职",
        "离职申请",
        "提交离职",
        "我的流程",
        "查看流程",
        "流程进度",
        "通过",
        "退回",
        "拒绝",
        "同意",
        "审批",
        "继续",
        "下一步",
        "下一个",
        "推进",
        "next",
        "help",
        "帮助",
        "命令",
    )

    async def _llm_classify_intent(self, msg_text: str) -> str:
        """LLM intent agent — GLM 推理判断用户意图（关键词写死的升级版）。

        返回 'offboarding' / 'meeting' / 'summarize' / 'list_docs' / 'help'。
        失败抛异常，调用方降级到 _classify_intent 关键词版。
        """
        from offboarding_flow.llm.glm_client import build_glm_client

        # 过短消息直接走帮助，省 GLM 调用
        if not msg_text or len(msg_text.strip()) < 2:
            return "help"

        client = build_glm_client()
        settings = self.settings

        system = (
            "你是 IM 机器人的意图路由器。给定用户消息，返回单一意图标签的 JSON："
            '{"intent":"<one of: offboarding/summarize/list_docs/meeting/help>"}\n\n'
            "意图说明：\n"
            "- offboarding：与离职流程相关 — 起流程（我要/我想/想要离职）、推进节点"
            "（通过、退回、拒绝、同意、继续、下一步、推进、审批等）、查询流程进度\n"
            "- summarize：用户让我总结某个会议（『总结 X 会议』『帮我总结纪要』『把 Y 整理成文档』等）\n"
            "- list_docs：用户问『列文档』『有哪些文档』『查文档列表』等\n"
            "- meeting：会议纪要相关的问答（『X 会议讨论了什么』『谁负责设备归还』『卡点有哪些』等任何问题）\n"
            "- help：纯问候（你好、hi）、求助菜单、与上面都不相关的闲聊\n\n"
            "只输出 JSON 不加其他文字。"
        )
        try:
            r = await client.chat.completions.create(
                model=settings.glm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": msg_text[:300]},
                ],
                temperature=0.1,
                timeout=15.0,
            )
            raw = (r.choices[0].message.content or "").strip()
        except Exception as e:
            raise RuntimeError(f"GLM intent call: {e}") from e

        # 解析 JSON
        import json
        import re

        cleaned = re.sub(r"^```(?:json)?\n?|```$", "", raw, flags=re.MULTILINE).strip()
        try:
            data = json.loads(cleaned)
            intent = str(data.get("intent", "")).strip().lower()
        except json.JSONDecodeError:
            # 兜底：raw 里含哪个关键词就选哪个
            for cand in ("offboarding", "summarize", "list_docs", "meeting", "help"):
                if cand in raw.lower():
                    intent = cand
                    break
            else:
                intent = "meeting"  # 兜底

        if intent not in ("offboarding", "summarize", "list_docs", "meeting", "help"):
            intent = "meeting"
        return intent

    def _classify_intent(self, msg_text: str) -> str:
        """简单关键词路由。返回 'offboarding' / 'meeting' / 'help' / 'other'。

        v1 简单决策树（后续可换 LLM intent router）：
        - 含"离职"二字 → offboarding（涵盖 我要/我想/申请/提交 等所有变体）
        - 短消息含决策词（通过/退回/拒绝/继续/同意等）→ offboarding
        - 含 help/帮助/命令 → help
        - 默认 → meeting
        """
        if not msg_text:
            return "help"
        text = msg_text.strip()
        # 含"离职"二字 → 离职流程
        if "离职" in text:
            return "offboarding"
        if any(k in text for k in ("help", "帮助", "命令", "怎么用", "支持哪些")):
            return "help"
        # 短消息且含决策/推进词 → offboarding
        if len(text) < 30 and any(
            k in text for k in ("通过", "退回", "拒绝", "同意", "继续", "下一步", "推进", "审批")
        ):
            return "offboarding"
        return "meeting"

    async def _handle_offboarding_command(
        self,
        *,
        msg_text: str,
        chat_id: str,
        message_id: str,
        sender_name: str,
        sender_email: str,
        sender_open_id: str,
        chat_type: str,
    ) -> None:
        """离职流程命令 → 适配 lark 字段后调 im.dispatcher.dispatch_message。"""
        from offboarding_flow.config import get_settings
        from offboarding_flow.im.context import IMHelpers
        from offboarding_flow.im.dispatcher import dispatch_message
        from offboarding_flow.state_store.session import new_session

        settings = get_settings()

        # 飞书 sender_name 解析成业务 username — demo 模式统一回路景智 / 或用 email 前缀
        sender_username = self._resolve_business_username(
            sender_name=sender_name, sender_email=sender_email
        )

        # 适配 IMHelpers：post_channel / send_dm 都通过 _reply_text 回写
        async def _post_channel(_chan: str, text: str) -> None:
            # 演示约定：bot 回写时加 【身份】 前缀（路景智一人多角色场景）
            prefixed = self._prefix_identity_for_demo(text)
            await self._reply_text(chat_id, message_id, prefixed)

        async def _send_dm(username: str, text: str) -> None:
            # demo 模式 — 所有 DM 都回到当前 chat（路景智一个人）
            prefixed = self._prefix_identity_for_demo(text, target_role=username)
            await self._reply_text(chat_id, message_id, prefixed)

        helpers = IMHelpers(post_channel=_post_channel, send_dm=_send_dm)

        try:
            await dispatch_message(
                sender_username=sender_username,
                user_id=sender_open_id,
                channel_id=chat_id,
                channel_type="D" if chat_type == "p2p" else "O",
                message=msg_text,
                im_helpers=helpers,
                settings=settings,
                session_factory=new_session,
            )
        except Exception as exc:
            logger.exception("[lark_listener] offboarding dispatch failed: %s", exc)
            await self._reply_text(
                chat_id,
                message_id,
                f"【离职流程 bot】❌ 命令处理失败：{type(exc).__name__}: {str(exc)[:200]}",
            )
            return

        # 起流程 / 推进节点后，主动 follow-up：告诉用户当前身份 + 公网 deeplink
        try:
            await self._send_role_and_deeplink_followup(
                sender_username=sender_username,
                chat_id=chat_id,
                message_id=message_id,
                sender_open_id=sender_open_id,
            )
        except Exception as exc:
            logger.warning("[lark_listener] followup deeplink failed (non-fatal): %s", exc)

    async def _send_role_and_deeplink_followup(
        self,
        *,
        sender_username: str,
        chat_id: str,
        message_id: str,
        sender_open_id: str,
    ) -> None:
        """起流程 / 推进节点后，主动告知：『您现在的身份 = X，处理入口 = 公网 deeplink』。

        实现：
        1. 查 DB 最近 in_progress 的 flow（employee_id=sender_username）
        2. 找其中 status='waiting_human' 的节点
        3. 给每个 waiting 节点签 token + 拼 deeplink → 一条消息发给用户
        """
        import time as _time
        from uuid import uuid4 as _uuid4

        from offboarding_flow.auth import deep_link as _deep_link
        from offboarding_flow.auth import jwt_service as _jwt
        from offboarding_flow.auth.schemas import JWTPayload as _JWTPayload
        from offboarding_flow.config import get_settings as _get_settings
        from offboarding_flow.state_store.repositories import (
            FlowRepository,
            NodeRepository,
        )
        from offboarding_flow.state_store.session import new_session

        settings = _get_settings()

        async with new_session() as s:
            flow_repo = FlowRepository(s)
            node_repo = NodeRepository(s)
            flows = await flow_repo.list_all(limit=20)
            # 取该员工最近一条 in_progress
            target = next(
                (
                    f
                    for f in flows
                    if f.employee_id == sender_username and f.status == "in_progress"
                ),
                None,
            )
            if target is None:
                logger.info("[lark_listener] followup: no in_progress flow for %s", sender_username)
                return
            nodes = await node_repo.list_by_flow(target.id)
            waiting = [
                n for n in nodes if n.status == "waiting_human" and n.node_name != "applicant_view"
            ]
            if not waiting:
                await self._reply_text(
                    chat_id,
                    message_id,
                    f"【流程通知】案件 {str(target.id)[:8]} 当前无待处理节点（可能已完成或在自动节点）",
                )
                return

        # 角色 → 中文身份
        role_map = {
            "apply": "申请人",
            "manager_review": "上级（李四）",
            "hr_initial": "HR 初审（Bob）",
            "device_return": "IT 管理员（Charlie，设备归还）",
            "access_revoke": "IT 管理员（Charlie，权限回收）",
            "knowledge_handover": "HR（知识交接）",
            "finance_settle": "财务（David）",
            "legal_sign": "法务（Eve）",
            "hr_final": "HR 终审（Alice）",
            "applicant_final_confirm": "申请人（最终确认）",
        }

        now = int(_time.time())
        lines = [f"【流程已推进 — 案件 {str(target.id)[:8]}】", ""]
        _node_role_map = {
            "apply": "applicant",
            "manager_review": "manager",
            "hr_initial": "hr",
            "device_return": "it_admin",
            "access_revoke": "it_admin",
            "knowledge_handover": "hr",
            "finance_settle": "finance",
            "legal_sign": "legal",
            "hr_final": "hr",
            "applicant_final_confirm": "applicant",
        }
        for n in waiting:
            identity = role_map.get(n.node_name, n.node_name)
            role = _node_role_map.get(n.node_name, "applicant")
            payload = _JWTPayload(
                sub=n.assignee or sender_username,
                email=f"{n.assignee or sender_username}@demo.local",
                role=role,
                flow_id=target.id,
                node_id=n.id,
                node_name=n.node_name,
                allowed_actions=["advance", "return", "reject"],
                iat=now,
                exp=now + settings.token_expiry_hours * 3600,
                jti=_uuid4().hex,
            )
            token = _jwt.encode(payload)
            deeplink = _deep_link.build_deep_link(
                token, payload, base_url=settings.deeplink_base_url
            )
            lines.append(f"👉 **您现在是【{identity}】身份**")
            lines.append(f"   处理节点：{n.node_title}")
            lines.append(f"   公网链接（点开即操作）：{deeplink}")
            lines.append("")
            lines.append("   或直接在飞书回复 bot：`通过 [意见]` / `退回 [意见]` / `拒绝 [意见]`")
            lines.append("")

        await self._reply_text(chat_id, message_id, "\n".join(lines))

    def _resolve_business_username(self, sender_name: str, sender_email: str) -> str:
        """飞书身份 → 业务 username。

        Demo 模式：路景智扮演所有角色 — 默认回 'laios'（作为申请人 / 全角色测试）。
        生产：应该查 user_repo 用 email/name 找对应 username。
        """
        if not self.settings.lark_demo_mode:
            # TODO: 生产模式查 users 表（按 email 匹配）
            return sender_email.split("@")[0] if sender_email else "unknown"
        # demo: 路景智一人多角色
        return "laios"

    def _replace_all_mentions_with_demo_owner(self, md: str) -> str:
        """演示约定：把 markdown 里 `@username` 都替换成 `@路景智 (XX 身份)`。

        防止文档里 @ 真实飞书账号（实际上路景智一人扮演多角色，所有 @ 都应该回指他）。
        """
        import re

        role_map = {
            "li.si": "上级",
            "hr.bob": "HR 初审",
            "hr.alice": "HR 终审",
            "it.charlie": "IT 管理员",
            "fin.david": "财务",
            "legal.eve": "法务",
            "wang.wu": "知识管理",
            "laios": "申请人",
            "zhang.san": "申请人",
        }

        def _sub(m: "re.Match[str]") -> str:
            username = m.group(1).rstrip(".,;:")
            role = role_map.get(username, username)
            return f"@路景智 ({role} 身份)"

        # 匹配 @xxx.yyy 或 @xxx
        return re.sub(r"@([a-zA-Z][a-zA-Z0-9._-]*)", _sub, md)

    def _prefix_identity_for_demo(self, text: str, target_role: str | None = None) -> str:
        """演示约定：bot 回写消息时按目标角色加 【XX 身份】 前缀。

        Demo 模式下 (lark_demo_mode=True) 必加；生产模式直接返回原文本。
        """
        if not self.settings.lark_demo_mode:
            return text
        # 根据 target_role 标签化（target_role 可能是 username 如 li.si / hr.bob）
        role_map = {
            "li.si": "上级（李四）",
            "hr.bob": "HR 初审（Bob）",
            "hr.alice": "HR 终审（Alice）",
            "it.charlie": "IT 管理员（Charlie）",
            "fin.david": "财务（David）",
            "legal.eve": "法务（Eve）",
            "wang.wu": "知识管理（王五）",
            "laios": "申请人 / 路景智",
        }
        if target_role and target_role in role_map:
            return f"【{role_map[target_role]} 身份】\n{text}"
        return f"【bot 通知】\n{text}"

    # ------------------------------------------------------------------ #
    # 飞书文档 — 列表 / 拉原文 / 选择 / RAG 问答
    # ------------------------------------------------------------------ #

    # 链接正则：飞书 docx / wiki / sheets 都有 token
    _DOC_URL_RE = r"https?://[\w.-]*feishu\.cn/(docx|docs|wiki|sheets)/([A-Za-z0-9]+)"

    def _extract_feishu_doc_urls(self, text: str) -> list[dict[str, str]]:
        """从消息文本提取飞书文档链接 → [{"type": "docx", "token": "xxx", "url": "..."}]"""
        import re

        results: list[dict[str, str]] = []
        for m in re.finditer(self._DOC_URL_RE, text):
            results.append({"type": m.group(1), "token": m.group(2), "url": m.group(0)})
        return results

    async def _fetch_doc_raw_content(self, doc_type: str, token: str) -> str:
        """拉飞书文档原文（纯文本）。docx 用 raw_content，wiki 先解析到 obj_token。"""
        import httpx

        from offboarding_flow.providers.lark_provider import _get_tenant_token

        settings = self.settings
        tok = await _get_tenant_token(
            settings.lark_base_url, settings.lark_app_id, settings.lark_app_secret
        )
        headers = {"Authorization": f"Bearer {tok}"}

        async with httpx.AsyncClient(timeout=20.0) as client:
            real_token = token
            # wiki 链接需要先解析到底层 doc obj
            if doc_type == "wiki":
                wiki_url = (
                    f"{settings.lark_base_url}/open-apis/wiki/v2/spaces/get_node?token={token}"
                )
                resp = await client.get(wiki_url, headers=headers)
                data = resp.json()
                if data.get("code") == 0:
                    node = data.get("data", {}).get("node", {})
                    real_token = node.get("obj_token", token)
                    doc_type = node.get("obj_type", "docx")
                else:
                    logger.warning("[lark_listener] wiki resolve fail: %s", data.get("msg"))

            if doc_type in ("docx", "doc"):
                url = (
                    f"{settings.lark_base_url}/open-apis/docx/v1/documents/"
                    f"{real_token}/raw_content"
                )
                resp = await client.get(url, headers=headers)
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("content", "")
                logger.warning(
                    "[lark_listener] docx raw fail code=%s msg=%s",
                    data.get("code"),
                    data.get("msg"),
                )
                return f"[拉取失败 code={data.get('code')} msg={data.get('msg')}]"
            return f"[暂不支持文档类型 {doc_type}]"

    async def _list_user_docs(self, max_count: int = 10) -> list[dict[str, str]]:
        """列出 bot 可访问的最近文档（应用空间根目录）→ [{"name", "token", "type", "url"}]"""
        import httpx

        from offboarding_flow.providers.lark_provider import _get_tenant_token

        settings = self.settings
        tok = await _get_tenant_token(
            settings.lark_base_url, settings.lark_app_id, settings.lark_app_secret
        )
        headers = {"Authorization": f"Bearer {tok}"}

        url = f"{settings.lark_base_url}/open-apis/drive/v1/files?page_size={max_count}&order_by=EditedTime&direction=DESC"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(
                    "[lark_listener] list files fail code=%s msg=%s",
                    data.get("code"),
                    data.get("msg"),
                )
                return []
            files = data.get("data", {}).get("files", []) or []
            out: list[dict[str, str]] = []
            for f in files:
                ftype = f.get("type", "")
                ftoken = f.get("token", "")
                fname = f.get("name", "untitled")
                if ftype in ("docx", "doc", "sheet", "bitable"):
                    out.append(
                        {
                            "name": fname,
                            "token": ftoken,
                            "type": ftype,
                            "url": f.get("url", f"{settings.lark_base_url}/{ftype}/{ftoken}"),
                        }
                    )
            return out

    async def _list_accessible_docs_and_reply(
        self, chat_id: str, message_id: str, sender_name: str, sender_open_id: str
    ) -> None:
        """列文档 + cache + 回复编号列表。"""
        docs = await self._list_user_docs(max_count=10)
        if not docs:
            await self._reply_text(
                chat_id,
                message_id,
                f"【bot】{sender_name} 您好 ✨\n"
                "暂时没有可访问的文档。\n\n"
                "**让我能读到文档的 3 种方式**：\n"
                "1. 直接把飞书文档链接发我（如 https://xxx.feishu.cn/docx/abc）\n"
                "2. 在飞书云空间把文档『分享』给本应用\n"
                "3. 直接粘贴会议纪要文本（>200 字）让我总结",
            )
            return

        # cache 到 _doc_list_cache[chat_id]
        if not hasattr(self, "_doc_list_cache"):
            self._doc_list_cache: dict[str, list[dict[str, str]]] = {}
        self._doc_list_cache[chat_id] = docs

        lines = [f"【bot】{sender_name} 我能访问以下 **{len(docs)} 篇文档**（最近编辑）："]
        for i, d in enumerate(docs, 1):
            lines.append(f"{i}. **{d['name']}** ({d['type']}) — [打开]({d['url']})")
        lines.append("")
        lines.append("**用法**：")
        lines.append("• 回复编号（如 `1`）→ 我去拉它原文 + 总结")
        lines.append("• 贴文档链接 → 直接总结")
        lines.append("• 提问（含问号或「讨论/提到/是什么」）→ 我自动匹配文档回答")
        await self._reply_text(chat_id, message_id, "\n".join(lines))

    def _parse_doc_choice(self, text: str, chat_id: str) -> dict[str, str] | None:
        """如果消息是纯数字（如 "1" "2"），且 cache 有列表，返回对应文档信息。"""
        text = text.strip()
        if not text.isdigit():
            return None
        if not hasattr(self, "_doc_list_cache"):
            return None
        docs = self._doc_list_cache.get(chat_id)
        if not docs:
            return None
        idx = int(text) - 1
        if 0 <= idx < len(docs):
            d = docs[idx]
            return {"name": d["name"], "doc_url": d["url"], "token": d["token"], "type": d["type"]}
        return None

    def _is_qa_query(self, text: str) -> bool:
        """[已废弃] — 现在默认所有消息都走 RAG，保留兼容。"""
        return True

    def _is_greeting_or_help(self, text: str) -> bool:
        """判定是纯问候 / 帮助 → 不走 RAG，回欢迎语。"""
        text = text.strip().lower()
        greetings = (
            "你好",
            "您好",
            "hi",
            "hello",
            "hey",
            "在吗",
            "在么",
            "帮助",
            "help",
            "command",
            "命令",
            "怎么用",
            "支持哪些",
            "能做什么",
        )
        # 短消息 + 命中问候词 → 帮助
        if len(text) < 12 and any(g in text for g in greetings):
            return True
        # 极短（< 4 字符）且无中英文内容 → 也回帮助
        if len(text) < 4:
            return True
        return False

    # 飞书 wiki 文档绑定（路景智已共享给本 bot 应用）
    _MEETING_NOTES_WIKI_TOKEN = "PuwTwHuk9iLSAukdR2Fc2l0JnAd"  # 会议纪要1（读取源）
    _COLLAB_DOC_WIKI_TOKEN = "PHjGwuq7Mi4pRfkLestc8e57nXg"  # 协作文档（写入位置 — AI 总结落到这里）

    async def _handle_summarize_request(
        self,
        *,
        request: str,
        chat_id: str,
        message_id: str,
        sender_name: str,
        sender_open_id: str,
    ) -> None:
        """处理"@bot 帮我总结 XX 会议"：
        1. 从 DB 用关键词匹配 meeting（先 title 粗匹配，再 LLM router 兜底）
        2. 拿 raw_text → GLM 渲染总结 markdown
        3. append 到协作文档1（wiki）；如果 forbidden 则创建新 docx
        4. 回复用户 + @ 路景智
        """
        from offboarding_flow.state_store.meeting_repository import MeetingRepository
        from offboarding_flow.state_store.session import new_session

        await self._reply_text(
            chat_id,
            message_id,
            f"【bot】{sender_name} 我去会议库找匹配的纪要并写到协作文档 ✍️ ...",
        )

        # 1. 先 ILIKE 关键词匹配
        import re

        words = [w for w in re.findall(r"[一-龥A-Za-z0-9]+", request) if len(w) >= 2]
        meeting = None
        async with new_session() as s:
            repo = MeetingRepository(s)
            for w in words:
                if w in ("帮我", "总结", "下", "一下", "会议", "纪要"):
                    continue
                hits = await repo.search_by_title(w, limit=3)
                if hits:
                    meeting = hits[0]
                    break
            # 兜底：取最近一篇
            if meeting is None:
                recent = await repo.list_recent(limit=1)
                meeting = recent[0] if recent else None

        if meeting is None:
            await self._reply_text(
                chat_id,
                message_id,
                "【bot】❌ 会议库还没纪要 — 先发一段会议内容让我入库",
            )
            return

        # 2. 用已有 extract_json 渲染（不重跑 GLM）
        from offboarding_flow.services.meeting_service import MeetingService

        svc = MeetingService()
        try:
            # 若 extract_json 有内容 → 重构 MeetingExtract 用 render_markdown
            ej = meeting.extract_json or {}
            from offboarding_flow.services.meeting_service import (
                Blocker,
                Decision,
                MeetingExtract,
                Task,
            )

            extract = MeetingExtract(
                title=meeting.title,
                summary=meeting.summary or ej.get("summary", ""),
                tasks=[
                    Task(**{k: t.get(k, "") for k in ("text", "owner", "due_date", "priority")})
                    for t in ej.get("tasks", [])
                    if isinstance(t, dict)
                ],
                blockers=[
                    Blocker(description=b.get("description", ""), owner=b.get("owner", ""))
                    for b in ej.get("blockers", [])
                    if isinstance(b, dict)
                ],
                decisions=[
                    Decision(decision=d.get("decision", ""))
                    for d in ej.get("decisions", [])
                    if isinstance(d, dict)
                ],
            )
            md = svc.render_markdown(extract, ingested_by="路景智 (bot 演示)")
            if self.settings.lark_demo_mode:
                md = self._replace_all_mentions_with_demo_owner(md)
        except Exception as exc:
            logger.warning("[lark_listener] render markdown fail: %s — fallback to raw", exc)
            md = f"# {meeting.title}\n\n{meeting.summary or ''}\n\n---\n\n{meeting.raw_text[:3000]}"

        # 3. append 到协作文档1（wiki），失败则创建新 docx
        target_url = None
        target_type = "新建"
        try:
            obj_token = await self._resolve_wiki_to_docx(self._COLLAB_DOC_WIKI_TOKEN)
            await self._append_text_to_docx(obj_token, md)
            target_url = f"https://pg-verse.feishu.cn/wiki/{self._COLLAB_DOC_WIKI_TOKEN}"
            target_type = "协作文档（wiki）"
        except Exception as exc:
            logger.warning("[lark_listener] wiki append fail: %s — fallback to new docx", exc)
            # fallback: 在 bot 自己空间新建 docx
            try:
                from offboarding_flow.providers.lark_provider import LarkDocsProvider

                doc_info = await LarkDocsProvider().create_document(
                    title=f"【AI 总结】{meeting.title}",
                    markdown=md,
                )
                target_url = doc_info.url
                target_type = "新建 docx（协作文档未共享给 bot，自动创建了新文档）"
                # 更新 DB ai_doc_url
                async with new_session() as s:
                    repo = MeetingRepository(s)
                    m = await repo.get(meeting.id)
                    if m:
                        m.ai_doc_url = doc_info.url
                        await s.commit()
            except Exception as exc2:
                await self._reply_text(
                    chat_id,
                    message_id,
                    f"【bot】❌ 写飞书文档失败：{type(exc2).__name__}: {str(exc2)[:200]}",
                )
                return

        # 4. 回复 + @ 路景智
        await self._reply_text_with_at(
            chat_id,
            message_id,
            sender_open_id,
            f"【bot】✅ 已找到《{meeting.title}》并总结到 **{target_type}**\n" f"→ {target_url}",
        )

    async def _resolve_wiki_to_docx(self, wiki_token: str) -> str:
        import httpx

        from offboarding_flow.providers.lark_provider import _get_tenant_token

        settings = self.settings
        tok = await _get_tenant_token(
            settings.lark_base_url, settings.lark_app_id, settings.lark_app_secret
        )
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{settings.lark_base_url}/open-apis/wiki/v2/spaces/get_node?token={wiki_token}",
                headers={"Authorization": f"Bearer {tok}"},
            )
            data = r.json()
            if data.get("code") != 0:
                raise RuntimeError(f"wiki resolve: {data.get('msg')}")
            return data["data"]["node"]["obj_token"]

    async def _append_text_to_docx(self, doc_id: str, markdown: str) -> None:
        """把 markdown 作为 elements 追加到 docx —— **@路景智 转成真 mention_user chip**。

        关键修复：
        1. 先 strip 掉 Mattermost 风格 markdown link 语法（`[**@xxx**](/laios/messages/...)`）
        2. 切块时识别 `@路景智`，拼 mention_user element（蓝色 chip）+ 普通 text_run
        3. 飞书显示就是真 @ mention（蓝色高亮 + 通知到路景智本人）
        """
        import httpx

        from offboarding_flow.providers.lark_provider import _chunk_text, _get_tenant_token

        settings = self.settings
        owner_open_id = settings.lark_demo_owner_open_id or self._learned_owner_open_id or ""

        # 1. strip Mattermost link 语法
        md_clean = self._strip_mattermost_md_links(markdown)

        tok = await _get_tenant_token(
            settings.lark_base_url, settings.lark_app_id, settings.lark_app_secret
        )
        headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        chunks = _chunk_text(md_clean, 3500)
        async with httpx.AsyncClient(timeout=15) as c:
            for chunk in chunks:
                # 2. 拼真 mention_user elements
                elements = self._md_to_lark_elements(chunk, owner_open_id)
                body = {
                    "index": -1,
                    "children": [
                        {
                            "block_type": 2,
                            "text": {"elements": elements, "style": {}},
                        }
                    ],
                }
                r = await c.post(
                    f"{settings.lark_base_url}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    headers=headers,
                    json=body,
                )
                data = r.json()
                if data.get("code") != 0:
                    raise RuntimeError(
                        f"docx append: code={data.get('code')} msg={data.get('msg')}"
                    )

    def _strip_mattermost_md_links(self, md: str) -> str:
        """`[**@路景智 (xxx 身份)**](/laios/messages/...)` → `@路景智 (xxx 身份)` 纯文字。"""
        import re

        return re.sub(
            r"\[\*\*(@路景智[^*\]]*)\*\*\]\(/laios/messages/[^)]*\)",
            r"\1",
            md,
        )

    def _md_to_lark_elements(self, text: str, owner_open_id: str) -> list[dict]:
        """把含 `@路景智` 的纯文本拆成飞书 elements 列表，@路景智 → mention_user chip。

        如果 owner_open_id 空（启动期未配置且未学到），降级用纯 text_run。
        """
        import re

        if not owner_open_id:
            return [{"text_run": {"content": text, "text_element_style": {}}}]

        elements: list[dict] = []
        pattern = re.compile(r"@路景智")
        last = 0
        for m in pattern.finditer(text):
            if m.start() > last:
                elements.append(
                    {"text_run": {"content": text[last : m.start()], "text_element_style": {}}}
                )
            elements.append({"mention_user": {"user_id": owner_open_id, "text_element_style": {}}})
            last = m.end()
        if last < len(text):
            elements.append({"text_run": {"content": text[last:], "text_element_style": {}}})
        return elements

    async def _handle_qa(
        self,
        *,
        question: str,
        chat_id: str,
        message_id: str,
        sender_name: str,
        sender_open_id: str,
    ) -> None:
        """RAG 问答（pageindex 风格 — 从 DB 检索，不依赖飞书 list_files API）。

        2 阶段：
          1. **LLM router**：把所有 meetings (id+title+summary) 当 TOC，让 GLM
             选最多 3 个 meeting_id（带推理）
          2. **LLM answer**：拉这 3 个 meeting 的 raw_text + extract_json 喂 GLM 回答
        """
        from offboarding_flow.state_store.meeting_repository import MeetingRepository
        from offboarding_flow.state_store.session import new_session

        await self._reply_text(
            chat_id,
            message_id,
            f"【bot】{sender_name} 我去会议纪要库找答案 🔍 ...",
        )

        # 1. 列出 DB 里所有 meeting (TOC)
        async with new_session() as s:
            repo = MeetingRepository(s)
            meetings = await repo.list_recent(limit=30)

        if not meetings:
            await self._reply_text(
                chat_id,
                message_id,
                "【bot】❌ 会议库还没纪要 — 请先粘贴一段会议内容或贴飞书 doc 链接让我入库 + 总结",
            )
            return

        # 2. 给 LLM 路由 — 选最相关的 meeting_id
        toc_lines = []
        for m in meetings:
            summary = (m.summary or "")[:120].replace("\n", " ")
            toc_lines.append(f"- id={m.id}  标题=《{m.title}》  摘要：{summary}")

        from offboarding_flow.llm.glm_client import build_glm_client

        client = build_glm_client()
        settings = get_settings()

        router_prompt = (
            f"用户问：{question}\n\n"
            f"以下是当前会议纪要库的目录（{len(meetings)} 篇）：\n\n"
            + "\n".join(toc_lines)
            + "\n\n请选出最相关的 1-3 篇（按相关度降序），仅输出 JSON，格式："
            + '{"selected_ids":["uuid1","uuid2"], "reason":"为什么选这些"}'
            + "\n如果用户问题与所有纪要都无关，selected_ids 返回空数组 []。"
        )
        try:
            r1 = await client.chat.completions.create(
                model=settings.glm_model,
                messages=[
                    {"role": "system", "content": "你是会议纪要路由器，只输出 JSON。"},
                    {"role": "user", "content": router_prompt},
                ],
                temperature=0.1,
                timeout=30.0,
            )
            router_raw = (r1.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.exception("[lark_listener] QA router fail: %s", exc)
            await self._reply_text(
                chat_id,
                message_id,
                f"【bot】❌ 路由失败：{type(exc).__name__}: {str(exc)[:200]}",
            )
            return

        # 解析路由结果
        import json
        import re
        import uuid as _uuid

        # 去掉 ``` fence
        router_clean = re.sub(r"^```(?:json)?\n?|```$", "", router_raw, flags=re.MULTILINE).strip()
        try:
            router_data = json.loads(router_clean)
            selected_ids_raw = router_data.get("selected_ids", [])
            reason = router_data.get("reason", "")
        except json.JSONDecodeError:
            logger.warning("[lark_listener] router JSON 解析失败 raw=%r", router_raw[:200])
            selected_ids_raw = []
            reason = ""

        selected_ids: list[_uuid.UUID] = []
        for sid in selected_ids_raw[:3]:
            try:
                selected_ids.append(_uuid.UUID(str(sid)))
            except (ValueError, TypeError):
                continue

        if not selected_ids:
            await self._reply_text_with_at(
                chat_id,
                message_id,
                sender_open_id,
                f"【bot】未在会议库找到与『{question}』相关的纪要。\n"
                f"_(路由器理由：{reason or '无相关条目'})_",
            )
            return

        # 3. 拉这几篇的全文 → 喂 GLM 回答
        async with new_session() as s:
            repo = MeetingRepository(s)
            chosen = await repo.get_many(selected_ids)

        contents = [f"## 文档：{m.title}\n\n{(m.raw_text or '')[:6000]}" for m in chosen]
        answer_prompt = (
            f"用户问题：{question}\n\n"
            f"以下是相关的会议纪要原文（共 {len(contents)} 篇），请基于这些内容回答用户问题。"
            f"如果文档里没有明确答案，请直接说『未在文档中找到』，不要编造。"
            f"回答尽量简洁、要点列出、引用文档标题。\n\n" + "\n\n---\n\n".join(contents)
        )
        try:
            r2 = await client.chat.completions.create(
                model=settings.glm_model,
                messages=[
                    {"role": "system", "content": "你是会议纪要问答助手。"},
                    {"role": "user", "content": answer_prompt},
                ],
                temperature=0.2,
                timeout=60.0,
            )
            answer = (r2.choices[0].message.content or "（无回答）").strip()
        except Exception as exc:
            logger.exception("[lark_listener] QA answer fail: %s", exc)
            await self._reply_text(
                chat_id,
                message_id,
                f"【bot】❌ AI 回答失败：{type(exc).__name__}: {str(exc)[:200]}",
            )
            return

        ref_lines = "\n".join(
            f"- 《{m.title}》" + (f" → [文档]({m.ai_doc_url})" if m.ai_doc_url else "")
            for m in chosen
        )
        await self._reply_text_with_at(
            chat_id,
            message_id,
            sender_open_id,
            f"【bot 回答】\n\n{answer}\n\n**参考会议纪要**：\n{ref_lines}\n\n_AI 生成 · 请人工复核_",
        )

    async def _process_meeting_from_doc_urls(
        self,
        *,
        doc_urls: list[dict[str, str]],
        chat_id: str,
        message_id: str,
        sender_name: str,
        sender_email: str,
        sender_open_id: str,
    ) -> None:
        """从飞书文档 URL 列表拉原文 → 合并 → MeetingService 总结 → 创建汇总文档 → @ sender。"""
        raw_chunks: list[str] = []
        for d in doc_urls:
            text = await self._fetch_doc_raw_content(d["type"], d["token"])
            if text and not text.startswith("["):
                raw_chunks.append(f"=== {d.get('url', d['token'])} ===\n\n{text}")

        if not raw_chunks:
            await self._reply_text(
                chat_id,
                message_id,
                "【bot】❌ 文档原文为空 / 拉取失败。请确认 bot 有此文档权限（在飞书把文档『分享』给应用）",
            )
            return

        combined = "\n\n---\n\n".join(raw_chunks)
        await self._process_meeting(
            combined,
            chat_id,
            message_id,
            sender_name=sender_name,
            sender_email=sender_email,
            sender_open_id=sender_open_id,
        )

    async def _reply_text_with_at(
        self, chat_id: str, message_id: str, target_open_id: str, text: str
    ) -> None:
        """回复 + @ 指定 user（飞书 text 消息用 <at user_id="open_id">@xx</at> 语法）。"""
        if target_open_id:
            at_tag = f'<at user_id="{target_open_id}"></at> '
            text = at_tag + text
        await self._reply_text(chat_id, message_id, text)

    # ------------------------------------------------------------------ #
    # 业务 — 调 MeetingService + LarkDocsProvider
    # ------------------------------------------------------------------ #

    async def _process_meeting(
        self,
        raw_text: str,
        chat_id: str,
        message_id: str,
        *,
        sender_name: str,
        sender_email: str,
        sender_open_id: str,
    ) -> None:
        """会议纪要 → GLM 提取 → 创建飞书文档 → 回复链接。"""
        from offboarding_flow.providers.lark_provider import LarkDocsProvider
        from offboarding_flow.services.meeting_service import MeetingService

        # 1. GLM 提取
        try:
            meeting_svc = MeetingService(
                doc_provider=None,
                im_provider=None,
                outline_client=None,
            )
            extract = await meeting_svc.extract(raw_text)
            logger.info(
                "[lark_listener] GLM extract OK title=%s tasks=%d blockers=%d decisions=%d",
                extract.title,
                len(extract.tasks),
                len(extract.blockers),
                len(extract.decisions),
            )
        except Exception as exc:
            logger.exception("[lark_listener] GLM extract failed: %s", exc)
            await self._reply_text(
                chat_id,
                message_id,
                f"【会议纪要 bot】❌ AI 提炼失败：{type(exc).__name__}: {str(exc)[:200]}",
            )
            return

        # 2. 渲染 Markdown — ingested_by 用真实身份名，让文档可追溯
        ingested_by = (
            sender_name
            if sender_name and sender_name != "未知用户"
            else (sender_email or (sender_open_id[:12] if sender_open_id else "unknown"))
        )
        md = meeting_svc.render_markdown(extract, ingested_by=ingested_by)

        # demo 模式 — 把所有 @owner 替换成 @路景智 (XX 身份)
        # 避免文档里 @ 真实飞书账号，演示场景一人多角色
        if self.settings.lark_demo_mode:
            md = self._replace_all_mentions_with_demo_owner(md)

        # 3. 创建飞书 docx
        try:
            docs_provider = LarkDocsProvider()
            doc_info = await docs_provider.create_document(
                title=extract.title or "会议纪要总结",
                markdown=md,
            )
            logger.info(
                "[lark_listener] 飞书文档创建 OK doc_id=%s url=%s",
                doc_info.id,
                doc_info.url,
            )
        except Exception as exc:
            logger.exception("[lark_listener] create_document failed: %s", exc)
            await self._reply_text(
                chat_id,
                message_id,
                f"【会议纪要 bot】⚠️ AI 提炼成功，但飞书文档创建失败：{exc}\n"
                f"以下是 Markdown 总结：\n\n{md[:1500]}",
            )
            return

        # 3.5 入库 — 用 MeetingRepository 持久化（pageindex RAG 数据源）
        try:
            from offboarding_flow.state_store.meeting_repository import MeetingRepository
            from offboarding_flow.state_store.session import new_session

            extract_json = {
                "title": extract.title,
                "summary": extract.summary,
                "tasks": [
                    {
                        "text": t.text,
                        "owner": t.owner,
                        "due_date": t.due_date,
                        "priority": t.priority,
                    }
                    for t in extract.tasks
                ],
                "blockers": [
                    {"description": b.description, "owner": b.owner} for b in extract.blockers
                ],
                "decisions": [{"decision": d.decision} for d in extract.decisions],
            }
            async with new_session() as s:
                repo = MeetingRepository(s)
                await repo.save(
                    title=extract.title or "未命名会议",
                    raw_text=raw_text,
                    summary=extract.summary,
                    extract_json=extract_json,
                    ai_doc_url=doc_info.url,
                    ingested_by=ingested_by,
                    chat_id=chat_id,
                )
                await s.commit()
            logger.info("[lark_listener] meeting saved to DB title=%s", extract.title)
        except Exception as e:
            logger.warning("[lark_listener] meeting DB save failed (non-fatal): %s", e)

        # 4. 回复用户 — 文档链接 + 任务概览
        owner_lines: list[str] = []
        if extract.tasks:
            owner_lines.append(f"\n**📌 任务（{len(extract.tasks)}）**")
            for t in extract.tasks[:5]:
                due = f" · 截止 {t.due_date}" if t.due_date else ""
                owner_lines.append(f"- @{t.owner} — {t.text}{due}")
            if len(extract.tasks) > 5:
                owner_lines.append(f"… 另有 {len(extract.tasks) - 5} 项见文档")
        if extract.blockers:
            owner_lines.append(f"\n**⚠️ 卡点（{len(extract.blockers)}）**")
            for b in extract.blockers[:3]:
                owner_lines.append(f"- {b.description}")

        reply_lines = [
            f"【会议纪要 bot】✅ 总结完成 — [{extract.title}]({doc_info.url})",
            "",
            f"> {extract.summary}" if extract.summary else "",
            *owner_lines,
            "",
            "_本总结由 AI 生成，关键决策请人工复核_",
        ]
        # @ 路景智 / sender 提醒
        await self._reply_text_with_at(chat_id, message_id, sender_open_id, "\n".join(reply_lines))

    # ------------------------------------------------------------------ #
    # 工具 — 解析 sender / 抽取文本 / 回复消息
    # ------------------------------------------------------------------ #

    async def _resolve_sender(self, open_id: str) -> dict[str, str]:
        """通过 contact API 拿 sender 真实身份（name / email / mobile）。

        缓存 1 小时（簡單 in-memory dict）避免每条消息都打接口。
        失败返回 {}。
        """
        if not hasattr(self, "_sender_cache"):
            self._sender_cache: dict[str, tuple[float, dict[str, str]]] = {}
        import time as _time

        cached = self._sender_cache.get(open_id)
        if cached and _time.time() - cached[0] < 3600:
            return cached[1]

        import httpx

        from offboarding_flow.providers.lark_provider import _get_tenant_token

        settings = self.settings
        try:
            token = await _get_tenant_token(
                settings.lark_base_url, settings.lark_app_id, settings.lark_app_secret
            )
        except Exception as exc:
            logger.warning("[lark_listener] get token for resolve_sender: %s", exc)
            return {}

        url = (
            f"{settings.lark_base_url}/open-apis/contact/v3/users/{open_id}" "?user_id_type=open_id"
        )
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=headers)
                data = resp.json()
                if data.get("code") == 0:
                    user = data.get("data", {}).get("user", {})
                    info = {
                        "name": user.get("name", "") or user.get("nickname", ""),
                        "email": user.get("enterprise_email", "") or user.get("email", ""),
                        "mobile": user.get("mobile", ""),
                        "open_id": user.get("open_id", open_id),
                        "user_id": user.get("user_id", ""),
                        "department_ids": ",".join(user.get("department_ids", []) or []),
                    }
                    self._sender_cache[open_id] = (_time.time(), info)
                    return info
                logger.warning(
                    "[lark_listener] resolve_sender code=%s msg=%s — 可能权限不够，"
                    "检查应用是否申请了 contact:user.id:readonly + contact:user.base:readonly",
                    data.get("code"),
                    data.get("msg"),
                )
        except Exception as exc:
            logger.warning("[lark_listener] resolve_sender HTTP fail: %s", exc)
        return {}

    def _extract_text(self, message: Any) -> str:
        """从 lark message 对象抽出纯文本。"""
        msg_type = getattr(message, "message_type", "")
        content_str = getattr(message, "content", "")
        if not content_str:
            return ""

        import json as _json

        try:
            content = _json.loads(content_str) if isinstance(content_str, str) else content_str
        except Exception:
            return str(content_str)

        if msg_type == "text":
            text = content.get("text", "") if isinstance(content, dict) else ""
            # 飞书 @ 消息文本里会有 @_user_1 等占位，去掉
            import re

            return re.sub(r"@_user_\d+\s*", "", text).strip()
        if msg_type == "post":
            # rich text post — flatten title + content array
            parts: list[str] = []
            if isinstance(content, dict):
                title = content.get("title")
                if title:
                    parts.append(title)
                for paragraph in content.get("content", []) or []:
                    for el in paragraph or []:
                        if isinstance(el, dict) and "text" in el:
                            parts.append(el["text"])
            return "\n".join(parts).strip()
        # file / image / audio — v1 不处理
        return ""

    async def _reply_text(self, chat_id: str, message_id: str, text: str) -> None:
        """通过 Lark OpenAPI 回复一条文本消息。

        用 reply API（关联到原消息）；失败 fallback 到 send（直接发到 chat）。

        演示约定（lark_demo_mode=True）：每条回复**默认 @ 学到的 demo owner（路景智）**
        — 不需要 caller 显式调 _reply_text_with_at。让一人多角色场景每条消息都明确推送。
        """
        if not chat_id and not message_id:
            return
        # demo 模式 — 自动 @ 路景智 + 加 bot 身份标签
        if self.settings.lark_demo_mode:
            if self._learned_owner_open_id and not text.startswith("<at "):
                text = f'<at user_id="{self._learned_owner_open_id}"></at> {text}'
        # 复用 LarkIMProvider 的 token 缓存 + httpx client
        import json as _json

        import httpx

        from offboarding_flow.providers.lark_provider import _get_tenant_token

        settings = self.settings
        try:
            token = await _get_tenant_token(
                settings.lark_base_url, settings.lark_app_id, settings.lark_app_secret
            )
        except Exception as exc:
            logger.warning("[lark_listener] get token failed for reply: %s", exc)
            return

        # 飞书 text 消息 content 格式：{"text": "..."}
        body = {
            "msg_type": "text",
            "content": _json.dumps({"text": text}, ensure_ascii=False),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 优先 reply（关联原消息）
            if message_id:
                url = f"{settings.lark_base_url}/open-apis/im/v1/messages/{message_id}/reply"
                try:
                    resp = await client.post(url, headers=headers, json=body)
                    data = resp.json()
                    if data.get("code") == 0:
                        return
                    logger.warning(
                        "[lark_listener] reply failed code=%s msg=%s",
                        data.get("code"),
                        data.get("msg"),
                    )
                except Exception as exc:
                    logger.warning("[lark_listener] reply HTTP fail: %s", exc)

            # fallback：直接发到 chat
            if chat_id:
                url = f"{settings.lark_base_url}/open-apis/im/v1/messages?receive_id_type=chat_id"
                body_send = {**body, "receive_id": chat_id}
                try:
                    resp = await client.post(url, headers=headers, json=body_send)
                    data = resp.json()
                    if data.get("code") != 0:
                        logger.warning(
                            "[lark_listener] send to chat failed code=%s msg=%s",
                            data.get("code"),
                            data.get("msg"),
                        )
                except Exception as exc:
                    logger.warning("[lark_listener] send HTTP fail: %s", exc)


# -------------------------------------------------------------------- #
# main.py lifespan 用的启动 / 停止入口
# -------------------------------------------------------------------- #


def start_lark_listener(settings: Settings | None = None) -> LarkListener:
    """启动单例 — 在 FastAPI lifespan 里调。"""
    global _listener, _main_loop
    if settings is None:
        settings = get_settings()
    _main_loop = asyncio.get_running_loop()
    if _listener is None:
        _listener = LarkListener(settings)
    _listener.start()
    return _listener


def stop_lark_listener() -> None:
    """停止 — 在 FastAPI shutdown 里调。"""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
