"""knowledge_handover 节点：知识 / 文档交接（5 并行节点之一）。"""

from offboarding_flow.flow_engine.nodes._human_node_factory import make_human_node

KNOWLEDGE_HANDOVER_NODE_NAME = "knowledge_handover"
KNOWLEDGE_HANDOVER_NODE_TITLE = "知识 / 文档交接"
KNOWLEDGE_HANDOVER_NODE_DESCRIPTION = (
    "请确认知识 / 文档已交接给后续接手人并填写交接路径（如 Confluence URL）。"
)

knowledge_handover_node = make_human_node(
    KNOWLEDGE_HANDOVER_NODE_NAME,
    KNOWLEDGE_HANDOVER_NODE_TITLE,
    KNOWLEDGE_HANDOVER_NODE_DESCRIPTION,
)
