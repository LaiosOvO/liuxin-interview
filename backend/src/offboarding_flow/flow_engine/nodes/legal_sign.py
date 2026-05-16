"""legal_sign 节点：法务签字（5 并行节点之一）。"""

from offboarding_flow.flow_engine.nodes._human_node_factory import make_human_node

LEGAL_SIGN_NODE_NAME = "legal_sign"
LEGAL_SIGN_NODE_TITLE = "法务签字"
LEGAL_SIGN_NODE_DESCRIPTION = "请确认保密协议 / 竞业限制 / 离职证明等法务文件签署完成。"

legal_sign_node = make_human_node(
    LEGAL_SIGN_NODE_NAME,
    LEGAL_SIGN_NODE_TITLE,
    LEGAL_SIGN_NODE_DESCRIPTION,
)
