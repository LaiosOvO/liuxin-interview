"""finance_settle 节点：财务结算（5 并行节点之一）。"""

from offboarding_flow.flow_engine.nodes._human_node_factory import make_human_node

FINANCE_SETTLE_NODE_NAME = "finance_settle"
FINANCE_SETTLE_NODE_TITLE = "财务结算"
FINANCE_SETTLE_NODE_DESCRIPTION = "请完成离职员工的薪资 / 福利 / 公积金 / 年假折现结算并填写明细。"

finance_settle_node = make_human_node(
    FINANCE_SETTLE_NODE_NAME,
    FINANCE_SETTLE_NODE_TITLE,
    FINANCE_SETTLE_NODE_DESCRIPTION,
)
