"""access_revoke 节点：权限回收（5 并行节点之一）。"""

from offboarding_flow.flow_engine.nodes._human_node_factory import make_human_node

ACCESS_REVOKE_NODE_NAME = "access_revoke"
ACCESS_REVOKE_NODE_TITLE = "权限回收"
ACCESS_REVOKE_NODE_DESCRIPTION = (
    "请回收离职员工的所有系统权限（邮箱、VPN、GitLab、Confluence 等）并填写清单。"
)

access_revoke_node = make_human_node(
    ACCESS_REVOKE_NODE_NAME,
    ACCESS_REVOKE_NODE_TITLE,
    ACCESS_REVOKE_NODE_DESCRIPTION,
)
