"""3 个 prompt 模板 — Slice 4C 全部 LLM 能力共享（不要每能力一个 class）。

设计取舍（用户 memory feedback `feedback_capability_design`）:
- 用 f-string / format 占位 简洁可读
- 每个模板是 (system, user_template) 的 tuple — 调用方 format(**context) 渲染 user
- 不依赖 jinja2（少一个 dep）

3 个模板对应 PRD §15.1/15.2/4.5.2:
1. SUMMARIZE_FOR_APPLICANT_PROMPT — LLM-02 申请人邮件总结段（≤ 100 字一句话）
2. SUGGEST_NEXT_STEP_PROMPT — LLM-04 AI 推下一步（≤ 200 字四要素）
3. GENERATE_REPORT_PROMPT — LLM-05 AI 后台报告（markdown 结构化）
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# LLM-02: 申请人最终确认邮件摘要段（PRD §4.5.2）
# ─────────────────────────────────────────────────────────────────────────────

SUMMARIZE_FOR_APPLICANT_PROMPT: tuple[str, str] = (
    # system
    """你是 HR 离职流程助手。任务：把以下节点执行记录浓缩为一句给离职员工本人看的中文总结。

要求：
1. 一句话（≤ 100 字），客观陈述
2. 不要使用 emoji
3. 不要重复每个节点细节，只点明关键完成项 + 是否有异常
4. 第三人称视角（如「你的设备已归还」「权限已回收」）""",
    # user
    """以下是流程各节点的执行记录（JSON）：

{node_results_json}

请输出一句话总结。""",
)

# ─────────────────────────────────────────────────────────────────────────────
# LLM-04: AI 推理下一步建议（PRD §15.1）
# ─────────────────────────────────────────────────────────────────────────────

SUGGEST_NEXT_STEP_PROMPT: tuple[str, str] = (
    # system
    """你是 HR 离职流程顾问。基于以下流程状态，输出"建议下一步"。

要求：
1. 用简洁中文（≤ 200 字）
2. 必须包含四要素：当前节点 / 阻塞原因（如有）/ 推荐操作 / 责任人
3. 不要建议执行动作（系统不允许 AI 自动操作），只给建议供人工参考
4. 若流程已结束，直接告诉用户已结束""",
    # user
    """流程信息（JSON）：

{flow_summary_json}

节点列表：
{nodes_text}

最近动作日志：
{actions_text}

请输出建议下一步。""",
)

# ─────────────────────────────────────────────────────────────────────────────
# LLM-05: AI 后台报告生成（PRD §15.2）
# ─────────────────────────────────────────────────────────────────────────────

GENERATE_REPORT_PROMPT: tuple[str, str] = (
    # system
    """你是 HR 离职流程分析师。基于以下流程数据，输出结构化 markdown 报告。

报告必须包含 4 段（一级标题用 ##）：
1. **当前进度** — 已完成 / 当前激活节点 / 预计完成时间
2. **阻塞事项** — 用 ⚠️ 列出超时节点 / 证据缺失节点（如无写"暂无"）
3. **是否需要真人协助** — 明确"是/否" + 简短说明
4. **建议下一步** — 编号列表，仅供参考必须人工确认

格式参考 PRD §15.2 示例。中文输出。""",
    # user
    """流程信息（JSON）：

{flow_summary_json}

节点列表：
{nodes_text}

最近动作日志：
{actions_text}

请输出 markdown 报告。""",
)


def render_prompt(
    template: tuple[str, str],
    **context: object,
) -> tuple[str, str]:
    """渲染 prompt 模板 — 把 user 模板 format 出来。

    Args:
        template: (system, user_template) 二元组
        **context: 填充 user_template 的占位符

    Returns:
        (system, rendered_user) — 直接喂给 openai chat.completions.messages
    """
    system, user_template = template
    return system, user_template.format(**context)
