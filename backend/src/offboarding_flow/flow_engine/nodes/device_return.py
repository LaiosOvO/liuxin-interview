"""device_return 节点：设备归还（5 并行节点之一）。"""

from offboarding_flow.flow_engine.nodes._human_node_factory import make_human_node

DEVICE_RETURN_NODE_NAME = "device_return"
DEVICE_RETURN_NODE_TITLE = "设备归还"
DEVICE_RETURN_NODE_DESCRIPTION = (
    "请清点离职员工归还的所有设备（笔记本、门禁卡、SIM 卡等）并填写明细。"
)

device_return_node = make_human_node(
    DEVICE_RETURN_NODE_NAME,
    DEVICE_RETURN_NODE_TITLE,
    DEVICE_RETURN_NODE_DESCRIPTION,
)
