"""Phase 1 Repository 单元测试 — 不依赖真数据库。

目标：验证 ORM 模型可实例化、Repository 方法签名正确、enum 值映射正确。
真数据库集成测试见 Plan 07 全流程冒烟（OFFBOARDING_E2E_BASE_URL）。
"""

from __future__ import annotations

import uuid

from offboarding_flow.state_store.enums import (
    ActionStatus,
    ActionType,
    FlowStatus,
    NodeStatus,
    NotificationChannel,
    NotificationStatus,
    Role,
)
from offboarding_flow.state_store.models import (
    ActionLog,
    Base,
    FlowInstance,
    NodeState,
    Notification,
    NotificationOutbox,
    User,
)
from offboarding_flow.state_store.repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
    UserRepository,
)


def test_metadata_has_6_tables():
    """Base.metadata 必须包含 6 张业务表。"""
    table_names = sorted(Base.metadata.tables.keys())
    expected = sorted(
        [
            "app.flow_instances",
            "app.node_states",
            "app.action_logs",
            "app.users",
            "app.notifications",
            "app.notification_outbox",
        ]
    )
    assert table_names == expected, f"got {table_names}"


def test_flow_instance_can_be_constructed():
    flow = FlowInstance(employee_id="zhang.san", template="standard_offboarding")
    assert flow.employee_id == "zhang.san"
    assert flow.template == "standard_offboarding"


def test_node_state_can_be_constructed():
    flow_id = uuid.uuid4()
    node = NodeState(
        flow_id=flow_id,
        node_name="manager_review",
        node_title="上级审批",
        status=NodeStatus.WAITING_HUMAN.value,
    )
    assert node.node_name == "manager_review"
    assert node.status == "waiting_human"


def test_action_log_can_be_constructed():
    log = ActionLog(
        flow_id=uuid.uuid4(),
        actor="li.si",
        action=ActionType.ADVANCE.value,
        status=ActionStatus.SUCCESS.value,
    )
    assert log.actor == "li.si"
    assert log.action == "advance"


def test_user_can_be_constructed():
    user = User(
        username="zhang.san",
        email="zhang.san@example.com",
        role=Role.APPLICANT.value,
    )
    assert user.username == "zhang.san"
    assert user.role == "applicant"


def test_notification_can_be_constructed():
    n = Notification(
        flow_id=uuid.uuid4(),
        channel=NotificationChannel.EMAIL.value,
        recipient="zhang.san@qq.com",
        status=NotificationStatus.PENDING.value,
    )
    assert n.channel == "email"
    assert n.status == "pending"


def test_notification_outbox_can_be_constructed():
    o = NotificationOutbox(
        flow_id=uuid.uuid4(),
        channel=NotificationChannel.MATTERMOST.value,
        recipient="li.si",
        payload={"subject": "test"},
        status=NotificationStatus.PENDING.value,
    )
    assert o.channel == "mattermost"
    assert o.payload == {"subject": "test"}


def test_flow_status_enum_values():
    assert FlowStatus.IN_PROGRESS.value == "in_progress"
    assert FlowStatus.COMPLETED.value == "completed"
    assert FlowStatus.CANCELLED.value == "cancelled"
    assert FlowStatus.REJECTED.value == "rejected"


def test_node_status_enum_values():
    assert NodeStatus.PENDING.value == "pending"
    assert NodeStatus.WAITING_HUMAN.value == "waiting_human"
    assert NodeStatus.IN_REVIEW.value == "in_review"
    assert NodeStatus.DONE.value == "done"
    assert NodeStatus.REJECTED.value == "rejected"
    assert NodeStatus.RETURNED.value == "returned"


def test_action_type_enum_values():
    assert ActionType.ADVANCE.value == "advance"
    assert ActionType.RETURN.value == "return"
    assert ActionType.REJECT.value == "reject"
    assert ActionType.SYSTEM.value == "system"


def test_role_enum_has_required_roles():
    """8 角色 + admin（PRD §6.2 + SEED-02）。"""
    values = {r.value for r in Role}
    assert {
        "applicant",
        "manager",
        "hr",
        "it_admin",
        "finance",
        "legal",
        "kb_owner",
        "archivist",
        "admin",
    }.issubset(values)


def test_repository_classes_have_expected_methods():
    """Repository 方法签名校验（实际调用留集成测试）。"""
    # FlowRepository
    assert hasattr(FlowRepository, "create")
    assert hasattr(FlowRepository, "get")
    assert hasattr(FlowRepository, "list_all")
    assert hasattr(FlowRepository, "mark_completed")
    # NodeRepository
    assert hasattr(NodeRepository, "upsert")
    assert hasattr(NodeRepository, "get")
    assert hasattr(NodeRepository, "list_by_flow")
    assert hasattr(NodeRepository, "complete")
    # ActionRepository
    assert hasattr(ActionRepository, "create")
    assert hasattr(ActionRepository, "list_by_flow")
    # UserRepository
    assert hasattr(UserRepository, "upsert")
    assert hasattr(UserRepository, "get_by_username")


def test_node_states_has_unique_constraint():
    """node_states 必须有 (flow_id, node_name) 唯一约束（PITFALLS #16 幂等基础）。"""
    table = Base.metadata.tables["app.node_states"]
    unique_constraints = [
        c for c in table.constraints if hasattr(c, "name") and c.name == "uq_node_states_flow_node"
    ]
    assert len(unique_constraints) == 1
    cols = sorted(c.name for c in unique_constraints[0].columns)
    assert cols == ["flow_id", "node_name"]


def test_notification_outbox_has_unique_constraint():
    """notification_outbox 必须有 (flow_id, node_state_id, channel) 唯一约束（Phase 4 幂等基础）。"""
    table = Base.metadata.tables["app.notification_outbox"]
    unique_constraints = [
        c
        for c in table.constraints
        if hasattr(c, "name") and c.name == "uq_outbox_flow_node_channel"
    ]
    assert len(unique_constraints) == 1
    cols = sorted(c.name for c in unique_constraints[0].columns)
    assert cols == ["channel", "flow_id", "node_state_id"]
