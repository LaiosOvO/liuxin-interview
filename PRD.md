# AI 驱动的离职流程执行系统 — PRD

> 版本: v0.4（草案）
> 日期: 2026-05-16
> 作者: liuxin
> 状态: 待评审
>
> **v0.4 变更（面试评分点对齐 + Mattermost @bot 入口 + AI 增强）**：
> - 新增 §15 **AI 能力与边界声明**：AI 推理下一步建议 / AI 生成后台报告 / **明确标出"AI 不能做、必须人工确认"的动作清单**
> - 新增 §16 **Mattermost @bot 入口**：在 Mattermost 频道 `@offboarding-bot start zhang.san` 启动离职流程 + bot 实时输出进度报告
> - 新增 §17 **任务逾期与证据缺失模拟**：明确逾期检测 + AI 报告中的"阻塞事项"识别
> - 新增 §18 **加分项：自动动作节点（API/Webhook 演示）**：v1 演示一个 mock 自动节点证明架构支持人机协同
> - §15.0 评分对照表：面试 9 条评分点全部映射到对应章节
>
> **v0.3 变更**：
> - ✅ Mattermost 实例已部署到 `http://192.168.2.44:8065`（team: `laios`）
> - ✅ MinIO 已部署 `http://192.168.2.44:9001`（console）/ `:9000`（S3 API），预置 3 个 buckets，详见 §10
> - 新增 §6.2 邮件深链 **Token 一键登录**鉴权机制（JWT → session，按 role 渲染视图）
> - 新增 §7.4 **测试 / 演示模式**：统一收件箱 + 角色前缀 + 演示模式开关
> - 新增 §9.1 **测试组织数据 seed 方案**（8 个测试角色，覆盖全流程）
> - 新增 §10.1 **测试环境配置**（含 QQ SMTP / Mattermost / 深链 JWT 完整 env 模板）
> - SMTP 通道确定使用 QQ 邮箱（`smtp.qq.com:465 SSL`），授权码以环境变量注入
> - **范围收敛**：v1 不实现与外部业务系统的真实交互（资产 / AD / 财务全部跳过 Mock 调用），所有节点统一为「**通用节点详情表单（自由文本结果）+ 三态决策**」结构，专注**状态机推进**本身（§4.4）
> - 新增 §4.5 **申请人最终确认节点**：流程末尾自动聚合各节点结果，邮件汇总发送给离职员工本人，由其点击深链确认后才进入归档
>
> **v0.2 变更**：IM 通道从 Mattermost 切换为 **Mattermost**（[github.com/mattermost/mattermost](https://github.com/mattermost/mattermost)）。同时演示阶段使用 Mattermost 承担「轻量 HR 目录」职责（users / teams / custom attributes 模拟员工 / 部门 / 上下级关系），代替真实 HR 系统。详见 §7.2、§9、§14。

---

## 1. 背景与目标

### 1.1 问题陈述

传统离职流程靠 HR 用 Excel / OA 工单串行推动：设备归还、权限回收、知识交接、薪资结算、合同存档等环节散落在不同系统，HR 需要逐一登录、跟催、记录，**信息分散、状态不可见、流转易卡死**。

### 1.2 设计目标

构建一个 **AI 驱动的离职流程执行系统**——区别于 AI 聊天助手，它是一个**有状态、有角色、有交接的流程引擎**。AI 负责：

- **按场景识别流程**：根据离职类型（主动 / 被动 / 协议离职）选择对应的流程模板
- **按步骤推动任务**：状态机推进，节点失败自动重试或回退
- **按角色分发动作**：自动通知设备管理员、IT、财务、法务、直属上级
- **按状态跟踪进度**：每个节点的进入 / 完成 / 卡点都有可观测的状态
- **必要时交给真人**：通过邮件 + Mattermost 推送给具体责任人进行审核 / 确认 / 退回

### 1.3 非目标（YAGNI）

- ❌ 不做通用聊天界面（不是 ChatBot）
- ❌ 不替代具体业务系统（设备库、HR 系统、财务系统都在外部，本系统**只管状态流转**）
- ❌ 不做权限管理系统本身（用现有 SSO / LDAP）
- ❌ 不做工作流可视化编排（v1 流程模板硬编码，agent-builder 是后续阶段）

---

## 2. 核心设计原则

| 原则                  | 说明                                                                                          |
| --------------------- | --------------------------------------------------------------------------------------------- |
| **流程平台 vs 业务平台分离** | 本系统只负责状态机推进、回退、拒绝；具体业务处理（查设备、改权限、算工资）在各自业务系统，通过 API 调用 |
| **状态机驱动**        | 每个离职流程是一个 DAG，节点 = 状态，边 = 转换条件。LangGraph 作为引擎               |
| **双层状态分离**      | **LangGraph 是运行时编排引擎**（管路由、中断、恢复，checkpoint 数据是引擎私有的二进制 pickle）；**业务状态机记录是另一套独立的 DB 表**（`flow_instances` / `node_states` / `action_logs`，给 UI 查询、审计、运营看），两者通过节点函数同步写入 — 见 §5.3 |
| **每个用户视图独立**  | HR 看到的是"我管的所有人"，离职员工看到的是"我的进度"，设备管理员看到的是"待我处理"   |
| **邮件即入口**        | 每次需要人工介入时，邮件中包含状态机当前节点的**深链接**（携带 state_id + node_id + actor），点击直接到对应处理页 |
| **IM 主动推送**       | Mattermost 用作并行通知通道（提升触达率），与邮件互补                                       |
| **三态决策**          | 每个人工节点统一三种动作：**继续 / 退回 / 拒绝**（部分节点有审核子流程）                          |

---

## 3. 用户角色与权限

| 角色            | 主要场景                                                            |
| --------------- | ------------------------------------------------------------------- |
| **离职员工**    | 提交离职申请、查看自己的流程进度、配合设备归还 / 资料交接          |
| **直属上级**    | 审批离职申请、确认工作交接                                         |
| **HR**          | 总览所有离职流程、处理卡点、终审                                   |
| **IT / 设备管理员** | 处理设备归还节点（每台设备：完好 / 损坏赔偿 / 折旧购买 / 缺失）  |
| **财务**        | 处理结算节点（工资、报销、社保）                                   |
| **法务 / 合规**  | 处理保密协议、竞业协议节点                                         |
| **系统管理员**  | 配置流程模板（v1 仅查看，不可编辑）                                |

---

## 4. 核心场景与流程

### 4.1 标准离职流程（DAG 示意）

```
[离职申请]
    ↓
[直属上级审批] —拒绝→ 流程终止
    ↓ 同意
[HR 初审] —退回→ [离职申请]（要求补充材料）
    ↓ 通过
    ├──┬─→ [设备归还]      ──┐
    │  ├─→ [权限回收]      ──┤
    │  ├─→ [知识 / 文档交接] ──┤  并行
    │  └─→ [财务结算]      ──┤
    │                       ↓
    └──→ [法务签字（保密 / 竞业）]
                  ↓
            [HR 终审] —退回→ 任一并行节点
                  ↓ 通过
            [申请人最终确认] —退回→ HR 终审
                  ↓ 确认
            [生成离职证明 + 归档]
                  ↓
              [流程完成]
```

### 4.2 通用节点结构（v1 统一模型）

> **v0.3 范围收敛**：v1 不与任何外部业务系统（资产 / AD / 财务等）做真实交互。所有人工节点统一为**同一种结构** —— 通用节点详情表单。本系统**只负责状态机推进**和**操作内容留痕**，不模拟具体业务字段。

每个人工节点在前端渲染同一套通用表单：

```
┌─────────────────────────────────────────────────────┐
│  节点：设备归还                                       │
│  当前责任人：Charlie（IT 设备管理员）                 │
│  进入时间：2026-05-16 14:30                          │
│  ─────────────────────────────────────────────────  │
│  节点说明（流程模板配置，只读）：                     │
│   请确认离职员工已归还公司分配的所有设备（笔记本、    │
│   门禁卡、SIM 卡等），并填写详细情况。               │
│                                                       │
│  节点详情（文本输入，必填，将作为节点结果存档）：     │
│  ┌─────────────────────────────────────────────┐    │
│  │ 已归还笔记本 MacBook Pro 16'（编号 LP-0420）│    │
│  │ 门禁卡 已注销                                │    │
│  │ SIM 卡 已回收                                │    │
│  │ 显示器外接线缺失，已与员工签字确认           │    │
│  └─────────────────────────────────────────────┘    │
│                                                       │
│  ─────────────────────────────────────────────────  │
│  [✓ 继续]   [↩ 退回]   [✗ 拒绝]                     │
└─────────────────────────────────────────────────────┘
```

**统一字段定义**：

| 字段              | 类型         | 说明                                              |
| ----------------- | ------------ | ------------------------------------------------- |
| `node_name`       | string       | 节点标识（如 `device_return`）                    |
| `node_title`      | string       | 显示标题（如 "设备归还"）                         |
| `node_description`| string       | 节点说明（流程模板配置，提示责任人怎么操作）      |
| `result_text`     | text         | **节点详情**（责任人填写的文本，必填）            |
| `action`          | enum         | `advance` / `return` / `reject`                   |
| `reason`          | text         | 退回 / 拒绝的原因（action 非 advance 时必填）     |
| `actor`           | string       | 操作人 username                                   |
| `completed_at`    | timestamp    | 操作时间                                          |

#### 4.2.1 设备归还的具体表现（示例）

虽然名字叫"设备归还"，但 v1 实现里它和其他节点**完全相同**：
- IT 管理员 Charlie 收到邮件 / Mattermost 通知
- 点击深链 → 自动登录 → 看到上图所示通用表单
- 在「节点详情」里**自由文本**记录归还情况（写啥都行：每台设备一行、自然语言段落、表格 markdown 等）
- 三态决策：
  - **继续** → 文本作为该节点 `result` 存档，流程推进到下一节点
  - **退回** → 流程回到上游节点（默认 HR 初审），responder 必填 reason
  - **拒绝** → 整个流程终止，必填 reason

**v1 不做**：调资产系统 API、区分设备状态枚举、触发财务子流程、写回外部系统。后续 v2 接入真实业务系统时再扩展 `payload.devices: [{...}]` 等结构化字段，通用表单和三态决策结构保持不变。

### 4.3 通用人工节点行为（三态决策）

每个人工节点都暴露统一的三种动作，**所有节点行为完全一致**（包括设备归还、权限回收、知识交接、财务结算、法务签字、上级审批、HR 初审 / 终审、申请人最终确认）：

| 动作      | 状态机行为                                          | 触发                                |
| --------- | --------------------------------------------------- | ----------------------------------- |
| **继续**  | 当前节点 done，`result_text` 写入 payload，推进到下一节点 | 主路径                              |
| **退回**  | 回滚到上游指定节点（流程模板定义），`reason` 必填   | 例如：HR 初审退回到离职申请         |
| **拒绝**  | 整个流程终止（写入终止原因，归档），`reason` 必填   | 仅限上级审批 / HR 终审等关键节点    |

#### 4.3.1 节点结果的累计

每个节点完成后，`result_text` + `actor` + `completed_at` 都写入 `node_states.payload`，并冗余追加到 `flow_instances.context.node_results[]`，形成**有序的执行结果列表**，供 §4.5 申请人最终确认时一次性聚合。

### 4.4 范围之外（v1 显式不做）

| 项 | 原因 |
|---|---|
| 与资产 / AD / 财务系统的真实 API 调用 | v1 不做外部业务交互，专注状态机本身 |
| 每个节点的差异化表单 / 字段 | 通用表单足够，差异化留到 v2 |
| 节点附件上传 | 留接口，v1 不实现 |
| 节点子流程（执行 + 审核两层三态） | 留模板扩展点，v1 流程模板中所有节点均为单层 |

### 4.5 申请人最终确认节点（v0.3 新增）

#### 4.5.1 定位

在「HR 终审 → 归档」之间插入一个新节点 `applicant_final_confirm`，**assignee = 离职员工本人**。这是整个流程对申请人的「**结果回执**」：让申请人看到所有节点都做了什么、谁做的、写了什么备注，确认无误后再归档。

#### 4.5.2 节点逻辑

1. 触发条件：HR 终审 `advance`
2. 节点函数自动从 `flow_instances.context.node_results[]` 聚合本流程所有已完成节点的结果
3. 渲染**汇总邮件**（含一张完整时间线表格）发给离职员工本人，邮件正文示例：

```
张三 你好：

你的离职流程已完成全部审核环节，请最终确认以下执行记录无误。
点击下方按钮查看详情并确认 / 退回。

【执行记录】
────────────────────────────────────────────────────
1. 离职申请           (zhang.san, 2026-05-16 10:00)
   申请原因：个人发展，转岗其他公司
   计划离职日期：2026-05-31

2. 上级审批           (li.si, 2026-05-16 11:20) ✓ 继续
   备注：同意。已沟通交接计划。

3. HR 初审            (hr.alice, 2026-05-16 13:45) ✓ 继续
   备注：材料齐全。

4. 设备归还           (it.charlie, 2026-05-16 14:50) ✓ 继续
   备注：MacBook、门禁卡、SIM 卡已归还。
        显示器外接线缺失（已员工签字确认）。

5. 权限回收           (it.charlie, 2026-05-16 14:55) ✓ 继续
   备注：邮箱、VPN、Gitlab、Confluence 权限均已回收。

6. 知识 / 文档交接    (li.si, 2026-05-16 15:30) ✓ 继续
   备注：核心项目文档已整理到 Confluence /handover/zhangsan/

7. 财务结算           (fin.david, 2026-05-16 16:10) ✓ 继续
   备注：5 月工资已结算，年假折现 ¥3200 已入工资单。

8. 法务签字           (legal.eve, 2026-05-16 16:40) ✓ 继续
   备注：保密协议、竞业限制（无）已签署。

9. HR 终审            (hr.bob, 2026-05-16 17:00) ✓ 继续
   备注：所有环节确认无误。
────────────────────────────────────────────────────

[✓ 我已确认]   [↩ 我有异议（退回 HR 终审）]
```

4. 申请人点击邮件深链 → 一键登录（与其他节点完全一致的 token 机制）
5. 申请人看到的页面在通用节点表单基础上**额外展示**这张时间线表格（页面顶部，可滚动）
6. 申请人决策（无「拒绝」选项，只有 **确认 / 退回**）：
   - **确认** → 写入 `result_text`（如"无异议，已确认"）→ 推进到归档
   - **退回** → 写入 reason → 回退到 HR 终审，由 HR 复核

#### 4.5.3 邮件聚合伪代码

```python
async def applicant_final_confirm_node(state: OffboardingState):
    node_results = state["context"]["node_results"]   # 已按时间排序
    employee = await db.get_employee(state["employee_id"])
    html_body = render_template("final_confirm.html", {
        "employee": employee,
        "node_results": node_results,
        "deep_link": build_deep_link(state["flow_id"], current_node_id, employee.username),
    })
    await send_email(
        to=employee.email,
        subject=f"[申请人确认] 你的离职流程已完成审核，请最终确认",
        html_body=html_body,
    )
    return state   # interrupt_before 挂起，等申请人点击
```

---

## 5. 系统架构

### 5.1 高层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                          前端 (Next.js)                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ 员工视图   │ │ HR 视图    │ │ IT 视图    │ │ 状态机详情页 │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘ │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST / WebSocket
┌──────────────────────────────▼──────────────────────────────────┐
│                       后端 API 层 (FastAPI)                      │
│   - 流程查询  - 节点动作（继续/退回/拒绝）  - 鉴权（JWT）        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                  Agent 编排层 (LangGraph)                        │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  StateGraph: OffboardingFlow                            │    │
│  │  ├─ apply_node       (start)                            │    │
│  │  ├─ manager_review   (human-in-loop)                    │    │
│  │  ├─ hr_initial       (human-in-loop)                    │    │
│  │  ├─ device_return    (human-in-loop, parallel)          │    │
│  │  ├─ access_revoke    (agent, parallel)                  │    │
│  │  ├─ knowledge_handover (human-in-loop, parallel)        │    │
│  │  ├─ finance_settle   (human-in-loop, parallel)          │    │
│  │  ├─ legal_sign       (human-in-loop)                    │    │
│  │  ├─ hr_final         (human-in-loop)                    │    │
│  │  └─ archive          (agent, end)                       │    │
│  └────────────────────────────────────────────────────────┘    │
│  Checkpointer: PostgreSQL (持久化中断/恢复)                     │
└──────────┬──────────────────┬─────────────────┬─────────────────┘
           │                  │                 │
┌──────────▼──────┐  ┌────────▼────────┐ ┌──────▼──────────────┐
│ Notification    │  │ External Sys     │ │ LLM Service          │
│ ├─ SMTP (Email) │  │ ├─ HR 系统       │ │ ├─ GLM / Qwen        │
│ └─ Mattermost  │  │ ├─ 资产系统      │ │ └─ 局域网模型(可选)  │
│    Webhook      │  │ ├─ AD/LDAP       │ │                      │
│                 │  │ └─ 财务系统      │ │                      │
└─────────────────┘  └─────────────────┘ └──────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────┐
│                持久化 (PostgreSQL)                              │
│  - flow_instances  - node_states  - action_logs                 │
│  - notifications   - decisions_snapshot                         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 关键模块

| 模块                  | 职责                                              | 技术选型                 |
| --------------------- | ------------------------------------------------- | ------------------------ |
| **flow-engine**       | LangGraph 状态图、checkpoint、人工中断恢复        | LangGraph + Postgres saver |
| **state-store**       | 状态机的持久化记录（业务可读、审计、UI 查询）     | SQLAlchemy + PostgreSQL  |

### 5.3 LangGraph runtime ≠ 业务状态机记录（关键概念辨析）

本系统有**两份"状态"**，职责完全不同，**任何业务查询都不要直接读 LangGraph 的 checkpoint**：

```
┌─────────────────────────────────────────────┬─────────────────────────────────────────────┐
│  LangGraph Checkpoint（引擎私有）           │  业务状态机记录（DB 表，业务可读）          │
├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
│  表：langgraph_checkpoints                  │  表：flow_instances / node_states /         │
│      (LangGraph PostgresSaver 自管)         │      action_logs / notifications            │
│                                             │                                             │
│  内容：pickle 序列化的 StateGraph 运行时    │  内容：结构化业务字段，纯关系数据           │
│        state (TypedDict / dict)             │        - flow_id / employee_id              │
│        + interrupt 位置 + thread_id         │        - 当前激活节点 / 整体状态             │
│                                             │        - 每个节点的 result_text / actor     │
│  用途：                                     │        - 三态决策的完整审计日志             │
│   ✓ 进程崩溃后从最近节点恢复执行            │  用途：                                     │
│   ✓ 人工中断后 invoke(None) 继续            │   ✓ HR Dashboard 多维度查询和筛选            │
│   ✓ 条件边路由 (route_after_xxx)            │   ✓ 申请人 / 责任人的进度查看               │
│   ✗ **不要**作为 UI 数据源                  │   ✓ 合规审计、操作回溯                       │
│   ✗ **不要**做跨流程聚合查询                │   ✓ 申请人最终确认聚合 node_results         │
│   ✗ schema 不稳定，是引擎实现细节            │   ✓ 数据分析、报表、SLA 计算                 │
└─────────────────────────────────────────────┴─────────────────────────────────────────────┘
```

#### 5.3.1 节点函数的"双写"职责

每个 LangGraph 节点函数都必须：

```python
async def manager_review_node(state: OffboardingState):
    # 1. 节点进入时：在业务表创建/更新 node_states 记录（"我"已激活）
    node_state = await state_store.upsert_node_state(
        flow_id=state["flow_id"],
        node_name="manager_review",
        status="waiting_human",
        assignee=lookup_manager(state["employee_id"]),
        entered_at=now(),
    )
    # 2. 发邮件 / IM 通知
    await notification_dispatcher.dispatch(node_state, channels=["email", "mattermost"])
    # 3. 返回 LangGraph 的 state（这是引擎私有的）
    return state    # interrupt_before 在此挂起
```

人工操作回来时（FastAPI 路由）：

```python
async def submit_action(flow_id, node_id, action, result_text, reason):
    # 1. 写业务表：动作日志 + 节点状态变更
    await state_store.write_action_log(flow_id, node_id, action, result_text, reason)
    await state_store.complete_node_state(node_id, result_text=result_text)
    await state_store.append_node_result(flow_id, {...})   # 累计到 context.node_results
    
    # 2. 同步给 LangGraph：更新引擎 state + 恢复执行
    graph.update_state(
        config={"configurable": {"thread_id": flow_id}},
        values={"current_action": action, "decisions": {node_name: result_text}},
    )
    await graph.ainvoke(None, config={"configurable": {"thread_id": flow_id}})
```

#### 5.3.2 一致性约束

- **业务表是 source of truth**（给人 / 给 UI / 给报表用）
- **LangGraph checkpoint 是引擎的 source of truth**（用于恢复执行）
- 两者通过节点函数 + API 路由保持一致；任何一边失败要回滚另一边（节点函数内用 DB 事务 + try/except，失败时不要 `invoke` LangGraph）
- **崩溃恢复**：若两边不一致，以**业务表为权威**重建 LangGraph state（提供 `scripts/recover_from_db.py` 工具）

#### 5.3.3 为什么不复用 LangGraph 的 state？

| 维度 | 直接读 LangGraph checkpoint | 业务表 |
|---|---|---|
| Schema 稳定性 | 跟 LangGraph 版本绑定 | 我们自己定义，稳定 |
| 查询能力 | 只能按 thread_id 取整段 | 关系型 SQL，可 JOIN 可索引 |
| 跨流程聚合（HR 看全部）| ❌ 困难 | ✅ 天然支持 |
| 字段可演进 | ❌ 序列化格式被锁死 | ✅ 加列即可 |
| 给前端用 | ❌ 暴露引擎细节 | ✅ 业务语义清晰 |
| **flow-templates**    | 离职流程的 DAG 定义（v1 硬编码 Python）           | Python class             |
| **notification**      | 邮件 + Mattermost 推送，含状态深链生成           | aiosmtplib + httpx       |
| **integration**       | 外部业务系统的 API client（HR / 资产 / AD / 财务）| httpx + 适配器模式       |
| **auth**              | JWT + RBAC，按角色返回不同视图                    | FastAPI Depends          |
| **web**               | 多角色 dashboard、状态机可视化                    | Next.js + React Flow     |

---

## 6. 状态机数据模型

> 本节描述的是 **§5.3 提到的"业务状态机记录"**，即 `flow_instances` / `node_states` / `action_logs` / `notifications` 这一组业务表。**不是** LangGraph 的 checkpoint（那个由 `PostgresSaver` 自管，schema 不开放给业务消费）。

### 6.1 核心表

```sql
-- 流程实例：每个离职员工对应一条记录
flow_instances (
  id              UUID PRIMARY KEY,
  employee_id     VARCHAR(64),        -- 离职员工 ID
  flow_template   VARCHAR(64),        -- 流程模板名（standard_offboarding）
  current_nodes   JSONB,              -- 当前激活节点列表（并行场景多个）
  status          ENUM(running, paused, terminated, completed),
  context         JSONB,              -- 流程上下文（员工信息 / 决策快照）
  created_at      TIMESTAMP,
  updated_at      TIMESTAMP
)

-- 节点状态：流程中每个节点的运行快照
node_states (
  id              UUID PRIMARY KEY,
  flow_id         UUID REFERENCES flow_instances(id),
  node_name       VARCHAR(64),        -- e.g. device_return
  node_title      VARCHAR(128),       -- 显示标题（"设备归还"）
  node_description TEXT,              -- 节点说明（流程模板配置）
  status          ENUM(pending, waiting_human, in_review, done, rejected, returned),
  assignee        VARCHAR(64),        -- 当前责任人 username
  result_text     TEXT,               -- 节点详情（责任人填写，advance/return/reject 时必填）
  payload         JSONB,              -- 节点扩展数据（v2 接外部系统时用）
  entered_at      TIMESTAMP,
  completed_at    TIMESTAMP
)

-- 动作日志：每次三态决策（继续 / 退回 / 拒绝）
action_logs (
  id              UUID PRIMARY KEY,
  flow_id         UUID,
  node_state_id   UUID,
  actor           VARCHAR(64),
  action          ENUM(advance, return, reject),
  reason          TEXT,
  payload         JSONB,              -- 决策附带的数据（如设备处理结果）
  created_at      TIMESTAMP
)

-- 通知记录：邮件 / IM 推送审计
notifications (
  id              UUID PRIMARY KEY,
  flow_id         UUID,
  node_state_id   UUID,
  channel         ENUM(email, rocketchat),
  recipient       VARCHAR(128),
  link            TEXT,               -- 深链
  status          ENUM(sent, failed, clicked),
  sent_at         TIMESTAMP
)
```

### 6.2 深链格式与 Token 一键登录

每次需要人工介入时，邮件 / IM 携带的深链格式：

```
http://192.168.2.44:3000/flow/{flow_id}/node/{node_state_id}?token={signed_jwt}
```

#### 6.2.1 Token Payload（JWT，HS256 签名）

```json
{
  "sub": "li.si",                          // 操作人 username（Mattermost username 同步）
  "email": "li.si@demo.local",             // 真实邮箱（演示模式被网关覆写）
  "role": "manager",                       // employee / manager / hr / it / finance / legal
  "flow_id": "8f3a2b1e-...",
  "node_id": "a91c4d7e-...",
  "node_name": "manager_review",
  "allowed_actions": ["advance", "return", "reject"],
  "iat": 1716000000,
  "exp": 1716086400,                       // 默认 24h 过期（TOKEN_EXPIRY_HOURS）
  "jti": "one-shot-uuid"                   // 用于一次性失效
}
```

#### 6.2.2 一键登录流程（点击邮件 / IM 链接的完整链路）

```
[收件人点击邮件按钮]
   ↓  GET http://192.168.2.44:3000/flow/{flow_id}/node/{node_id}?token=xxx
[Next.js 前端]
   ↓  自动提交 POST /api/auth/exchange { token }
[FastAPI 后端]
   ↓  1. 校验 JWT 签名 + exp 未过期
   ↓  2. 校验 jti 未消费（Redis 黑名单 / DB `consumed_tokens` 表）
   ↓  3. 校验 (flow_id, node_id) 仍 waiting_human
   ↓  4. 校验 sub === node_state.assignee
   ↓  5. 写 jti 到已消费表（防转发复用）
   ↓  6. 签发 HttpOnly Cookie（与 flow_id 绑定，TTL 24h）
   ↓  7. 返回 { redirect_to: /flow/.../node/...?logged_in=1, role, name }
[前端]
   ↓  根据 role 拉取 GET /api/flows/{flow_id}/nodes/{node_id}/view
   ↓  渲染角色专属页面（IT 看设备清单；HR 看终审表单；上级看离职信表单）
[用户在页面操作完]
   ↓  POST /api/flows/{flow_id}/nodes/{node_id}/actions
   ↓  body: { action: "advance" | "return" | "reject", reason, payload }
[FastAPI]
   ↓  写 action_logs → graph.update_state(...) → graph.invoke(...)
   ↓  该节点所有未消费 token 一并失效（防止下游 token 失活后被复用）
[LangGraph]
   ↓  恢复执行 → 下一节点函数发送下一批通知
```

#### 6.2.3 安全约束

| 约束 | 实现 |
| ---- | ---- |
| 链接转发被滥用 | `jti` 一次性使用，token 换 session 后立即作废 |
| 跨节点 / 跨角色复用 | token 与 `(flow_id, node_id, sub)` 三元组强绑定 |
| 节点状态变更后失效 | 节点 `done/rejected/returned` 时清掉该 node 所有有效 token |
| Session 越权 | Cookie 与 `flow_id` 绑定；每次 API 调用校验 `role + node.assignee` |
| 密钥泄露 | `JWT_SECRET` 仅存 `.env`，不入库，定期轮换 |

#### 6.2.4 角色视图差异（按 role 渲染）

| Role     | 可见数据                                        | 可执行动作                    |
| -------- | ----------------------------------------------- | ----------------------------- |
| employee | 自己流程进度、各节点状态、被退回时的补充表单    | 提交申请 / 补充材料           |
| manager  | 下属离职申请详情、交接计划                      | advance / reject              |
| hr       | 所有流程总览、当前节点详情、卡点告警            | advance / return / reject     |
| it       | 设备清单（仅自己负责的节点）                    | 逐台打标 → advance / return   |
| finance  | 结算明细（仅自己节点）                          | advance / return              |
| legal    | 保密 / 竞业协议状态                             | advance / return              |

---

## 7. 人工介入与通知设计

### 7.1 双通道通知策略

每次状态机进入 `waiting_human` 节点，系统并行触发：

1. **邮件通知**（主通道，正式存档）
   - 主题：`[离职流程] {员工姓名} - {节点名称} 待您处理`
   - 正文：节点简介 + 操作要点 + **深链按钮**
   - 抄送：HR（保持可见）

2. **Mattermost 推送**（辅助通道，提升触达）
   - 通过 Webhook 发送到责任人私聊 / 部门频道
   - 卡片消息：节点信息 + 链接 + 快捷按钮（继续 / 退回 / 拒绝可在 IM 直接操作，可选 v2）

### 7.2 Mattermost 集成数据契约

Mattermost 在本系统中承担**双重角色**：

1. **IM 通知通道**（主用途）：通过 Bot 推送状态变更卡片消息
2. **轻量 HR 目录**（演示阶段）：Users / Teams / Channels / Custom Attributes 模拟员工、部门、上下级关系，代替真实 HR 系统对接（详见 §9）

需要从 Mattermost 管理员处获取：

| 数据项            | 说明                                                       |
| ----------------- | ---------------------------------------------------------- |
| Server URL        | 内网 Mattermost 服务地址（如 `http://192.168.2.44:8065`）  |
| Bot Account Token | 创建一个 Bot 账号，获取 Personal Access Token              |
| Incoming Webhook  | 用于简单消息推送（每个 channel 一个 URL）                  |
| REST API Token    | 用于读取 users / teams / channels（HR 目录查询）           |
| 用户映射          | 员工邮箱 → Mattermost username（Mattermost 自身已有邮箱字段，可直接查）|

推送消息格式（Mattermost Incoming Webhook JSON，与 Slack 格式兼容）：

```json
{
  "channel": "@user.name",
  "username": "离职流程 Bot",
  "icon_emoji": ":outbox_tray:",
  "text": "您有一个待处理节点",
  "attachments": [{
    "title": "李四 - 设备归还",
    "title_link": "http://192.168.2.44:3000/flow/xxx/node/yyy?token=zzz",
    "text": "请在 24 小时内处理 3 台设备的归还确认",
    "color": "#FFA500",
    "fields": [
      {"title": "员工", "value": "李四（工号 12345）", "short": true},
      {"title": "节点", "value": "设备归还", "short": true}
    ],
    "actions": [
      {"name": "继续", "integration": {"url": "http://192.168.2.44:8000/api/action/advance"}},
      {"name": "退回", "integration": {"url": "http://192.168.2.44:8000/api/action/return"}},
      {"name": "拒绝", "integration": {"url": "http://192.168.2.44:8000/api/action/reject"}}
    ]
  }]
}
```

**关键能力**：Mattermost 的 Interactive Message Buttons（`actions` 字段）支持用户直接在 IM 中点击「继续 / 退回 / 拒绝」，无需跳转邮件深链——这是相比 Rocket.Chat 的体验提升点。

### 7.3 Agent 主动通知触发点

| 触发事件                    | 通知对象              |
| --------------------------- | --------------------- |
| 节点进入 waiting_human      | 节点 assignee         |
| 节点超时未处理（>24h）      | assignee + HR         |
| 节点被退回                  | 上游节点 assignee     |
| 流程被拒绝                  | 员工 + HR + 上级      |
| 流程完成                    | 员工 + HR             |

### 7.4 测试 / 演示模式

为了在面试 / Demo 场景下让一位演示者用**一个邮箱**走完所有角色，引入 **APP_MODE=demo** 开关：

#### 7.4.1 收件箱聚合策略

- `notifications` 表的 `recipient` 字段仍记录**真实 assignee 邮箱**（审计完整）
- **发送网关**在 `APP_MODE=demo` 下把实际投递地址覆写为 `DEMO_INBOX=1624456575@qq.com`
- 邮件**主题**前缀加角色标记，便于在统一收件箱里区分：

```
[设备管理员·it.charlie] 离职流程 — 张三 — 设备归还待处理
[HR·hr.bob]            离职流程 — 张三 — HR 终审待处理
[上级·li.si]            离职流程 — 张三 — 上级审批待处理
```

- 邮件**正文**顶部插入提示横幅：

```
🧪 [演示模式] 此邮件本应发送给 it.charlie@demo.local
当前操作角色：IT 设备管理员
点击下方按钮将以该角色身份自动登录系统。
```

#### 7.4.2 邮件按钮 → 一键登录

邮件正文渲染一个醒目的「**立即处理**」按钮，链接即 §6.2 的深链格式。点击后浏览器自动完成 token → session 交换，免输入账号密码即可看到该角色的处理页面。

#### 7.4.3 SMTP 发件配置（演示用 QQ 邮箱）

```env
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=true                          # QQ 强制 SSL，不是 STARTTLS
SMTP_USER=1624456575@qq.com
SMTP_PASSWORD=${QQ_SMTP_AUTH_CODE}         # QQ 邮箱授权码，从 .env 注入
SMTP_FROM_NAME=离职流程 Bot
```

> ⚠️ QQ 邮箱授权码不是登录密码，是邮箱「设置 → 账户 → POP3/IMAP/SMTP 服务」生成的 16 位码，**仅通过 .env 注入，不入库不入文档**。

#### 7.4.4 切换生产模式

设 `APP_MODE=prod` 后：
- 发件网关恢复使用 `notifications.recipient`（真实邮箱）
- 邮件主题去掉角色前缀
- 邮件正文移除演示模式横幅
- 业务代码 0 修改

---

## 8. LangGraph 关键设计

### 8.1 StateGraph 定义（伪代码）

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

class OffboardingState(TypedDict):
    employee_id: str
    flow_id: str
    decisions: dict           # 各节点决策快照
    notifications_sent: list
    current_action: str       # advance / return / reject

graph = StateGraph(OffboardingState)
graph.add_node("apply", apply_node)
graph.add_node("manager_review", manager_review_node)        # interrupt_before
graph.add_node("hr_initial", hr_initial_node)                # interrupt_before
graph.add_node("device_return", device_return_node)          # interrupt_before
graph.add_node("access_revoke", access_revoke_node)
# ...

graph.add_edge("apply", "manager_review")
graph.add_conditional_edges("manager_review", route_after_manager_review,
                            {"advance": "hr_initial", "reject": END})
graph.add_conditional_edges("hr_initial", route_after_hr_initial,
                            {"advance": "parallel_fanout", "return": "apply"})
# 并行扇出 / 扇入
# ...

app = graph.compile(
    checkpointer=PostgresSaver(...),
    interrupt_before=["manager_review", "hr_initial", "device_return", ...]
)
```

### 8.2 人工中断恢复机制

- 进入人工节点前 `interrupt_before` 暂停，状态写入 Postgres
- 用户点击邮件深链 → API 接收三态决策 → `app.update_state(...)` + `app.invoke(...)` 恢复
- 恢复后图按条件边路由到下一节点

### 8.3 并行节点

设备归还 / 权限回收 / 知识交接 / 财务结算 可并行，用 LangGraph 的 fan-out + fan-in 模式（多边入度节点等待所有上游完成）。

---

## 9. 外部系统集成清单

| 系统              | 调用场景                              | 接口形式               | 必要性 | 演示阶段实现        |
| ----------------- | ------------------------------------- | ---------------------- | ------ | ------------------- |
| **Mattermost**    | IM 推送 + 轻量 HR 目录（员工/部门/上下级）+ SSO | Webhook + REST API     | P0     | ✅ 已部署 `http://192.168.2.44:8065`（team: `laios`）|
| **资产管理系统**  | 查询员工名下设备、回写归还状态        | REST API               | P0     | Mock Server         |
| **AD / LDAP**     | 触发权限回收                          | LDAP / SCIM            | P1     | Mock Server         |
| **财务系统**      | 触发结算流程、查询薪资状态            | REST API               | P1     | Mock Server         |
| **SMTP 服务**     | 邮件通知（含深链）                    | SMTP                   | P0     | ✅ QQ 邮箱 `smtp.qq.com:465`（演示模式统一收件箱） |

**演示阶段的"HR 系统"实现**：使用 Mattermost 的内置数据模型代替真实 HR 系统：

| HR 概念       | Mattermost 实体                                     |
| ------------- | -------------------------------------------------- |
| 员工          | User（含 email、first_name、last_name、position）  |
| 部门          | Team                                                |
| 上下级关系    | User Custom Attributes（`manager_email`）           |
| 工号          | User Custom Attributes（`employee_id`）             |
| 入离职状态    | User active/inactive                                |
| 设备清单      | 暂存于本系统数据库（v1）或 Custom Attributes（v2）  |

**集成策略**：所有外部系统调用走 `integration/` 目录的适配器，**Mock 优先**——v1 阶段先用 Mock Server 跑通整个流程，再逐个对接真实系统。

### 9.1 测试组织数据 Seed

演示阶段需要一份**覆盖全流程所有角色**的组织数据。落地为一个 `scripts/seed_demo_data.py` 脚本，幂等执行，使用 Mattermost REST API + 本系统 DB 双写。

#### 9.1.1 部门（Mattermost Team）

| Team name      | display_name | 用途                       |
| -------------- | ------------ | -------------------------- |
| `engineering`  | 研发部       | 离职员工 + 上级 + 总监     |
| `hr`           | 人力资源部   | HR 专员 + HR 总监          |
| `it`           | IT 运维部    | 设备管理员                 |
| `finance`      | 财务部       | 结算专员                   |
| `legal`        | 法务部       | 合规专员                   |

> 已有 `laios` team 用作演示主团队，业务 team 在其下创建。

#### 9.1.2 测试账号（8 个，覆盖完整 DAG）

> v0.3 调整：邮箱从 `@demo.local` 改为**真邮箱 + alias** 形式，分发到 3 个真实收件箱。已 seed 到实例：`http://192.168.2.44:8065`。

| Username      | 姓名    | 角色          | 团队        | Mattermost Email                | 真实收件箱            | manager_email                   | employee_id |
| ------------- | ------- | ------------- | ----------- | ------------------------------- | --------------------- | ------------------------------- | ----------- |
| `zhang.san`   | 张三    | 离职员工      | engineering | `1624456575+zhang.san@qq.com`   | 1624456575@qq.com     | `1624456575+li.si@qq.com`       | EMP001      |
| `li.si`       | 李四    | 直属上级      | engineering | `1624456575+li.si@qq.com`       | 1624456575@qq.com     | `1691517500+wang.wu@qq.com`     | EMP002      |
| `wang.wu`     | 王五    | 部门总监      | engineering | `1691517500+wang.wu@qq.com`     | 1691517500@qq.com     | —                               | EMP003      |
| `hr.alice`    | Alice   | HR 专员       | hr          | `1691517500+hr.alice@qq.com`    | 1691517500@qq.com     | `1624456575+hr.bob@qq.com`      | EMP004      |
| `hr.bob`      | Bob     | HR 总监       | hr          | `1624456575+hr.bob@qq.com`      | 1624456575@qq.com     | —                               | EMP005      |
| `it.charlie`  | Charlie | IT 设备管理员 | it          | `1691517500+it.charlie@qq.com`  | 1691517500@qq.com     | —                               | EMP006      |
| `fin.david`   | David   | 财务结算专员  | finance     | `jingzhi.lu+fin.david@wayz.ai`  | jingzhi.lu@wayz.ai    | —                               | EMP007      |
| `legal.eve`   | Eve     | 法务合规      | legal       | `jingzhi.lu+legal.eve@wayz.ai`  | jingzhi.lu@wayz.ai    | —                               | EMP008      |

> 系统管理员 `admin` 邮箱：`jingzhi.lu+admin@wayz.ai`。所有账号统一密码：`laios1855`。

#### 9.1.3 邮箱字段策略（关键决策 — v0.3 修订）

Mattermost 强制邮箱唯一。演示需要邮件能真正投递到演示者掌控的收件箱：

| 方案 | 做法 | 优劣 |
| --- | --- | --- |
| ~~A. fake @demo.local~~ | ~~每个 user 用 `${username}@demo.local`，发件网关覆写到 DEMO_INBOX~~ | v0.2 设计，演示者实际收不到真实邮件；已弃用 |
| **B. 真邮箱 + alias**（v0.3 采用）| Mattermost email 用 `${realbox}+${username}@${domain}` | Mattermost 视为不同邮箱满足唯一性；QQ / 企业邮箱的 `+alias` 默认投递到原邮箱；演示者真能收到邮件 |

**采用方案 B**，3 个真邮箱分发：

- `1624456575@qq.com`：zhang.san（离职员工）、li.si（上级）、hr.bob（HR 终审）— **主流程链路**
- `1691517500@qq.com`：wang.wu（总监）、hr.alice（HR 专员）、it.charlie（IT）— **部门管理者**
- `jingzhi.lu@wayz.ai`：fin.david（财务）、legal.eve（法务）、admin（系统管理员）— **后置 + 系统**

实现细节：
- `manager_email` 字段（Custom Attribute）同样用 +alias 形式，确保链路可追踪
- 实际发件全部走 `APP_MODE=demo` 网关覆写到 `DEMO_INBOX`

#### 9.1.4 Mattermost Custom Attributes

每个 user 写入以下自定义字段（管理员后台启用 Custom Profile Attributes）：

| 字段             | 类型   | 示例                    |
| ---------------- | ------ | ----------------------- |
| `employee_id`    | text   | `EMP001`                |
| `department`     | text   | `engineering`           |
| `role`           | select | `employee` / `manager` / `hr` / `it` / `finance` / `legal` |
| `manager_email`  | text   | `li.si@demo.local`      |

#### 9.1.5 Seed 脚本工作流

```
scripts/seed_demo_data.py
  1. 校验 Mattermost 可达 + Bot Token 有效
  2. 创建 5 个 team（幂等，已存在则跳过）
  3. 创建 8 个 user，写入 custom attributes
  4. 把每个 user 加入对应 team
  5. 创建本系统 DB 的 users 表镜像记录
  6. (可选) 调用 POST /api/flows 用 zhang.san 起一个 standard_offboarding 流程
  7. 输出演示者操作清单：
     - 收件箱 1624456575@qq.com 应收到第 1 封邮件（标题 [上级·li.si] ...）
     - 点击「立即处理」按钮 → 自动以 li.si 身份登录
     - 选「继续」→ 触发 hr.bob 的第 2 封邮件
     - ……直到流程完成
```

---

## 10. 部署环境

- **目标环境**：局域网服务器 `192.168.2.44`（GigaByte laios），仅内网访问
- **部署方式**：Docker Compose（多服务统一编排）
  - `flow-api`（FastAPI + LangGraph，单容器或拆 worker 见下）
  - `flow-worker`（LangGraph 异步任务 / 定时扫单，**v1 与 flow-api 合并**也可）
  - `postgres`（业务表 + LangGraph checkpoint 同库不同 schema）
  - `redis`（jti 黑名单 + 任务队列）
  - `web-static`（**前端 = `next build` 产物的静态文件**，通过 nginx 直接 serve，不跑 Node 运行时）
  - `nginx`（反向代理 + 静态资源服务，监听 `192.168.2.44:80`）
- **已就绪基础设施（独立 compose 栈，跨项目复用）**：
  - **Mattermost** `http://192.168.2.44:8065`（IM 通道 + 演示阶段 HR 目录，部署于 `deploy/mattermost/`）
  - **MinIO** S3 兼容对象存储 — API `http://192.168.2.44:9000` + Console `http://192.168.2.44:9001`（部署于 `deploy/minio/`）
    - 预置 3 个 buckets：`offboarding-attachments`（节点附件）、`offboarding-exports`（离职证明 PDF / 归档包）、`offboarding-screenshots`（演示截图，public download）
    - 凭证：root `admin / laios1855`（v1 演示用；生产建议建 Service Account 限定到 `offboarding-*` bucket）
- **LLM 接入**：优先调用现有 GLM API（外网），如内网隔离则切局域网部署 Qwen / GLM-9B
- **日志 / 监控**：本地 Loki + Grafana（轻量，不依赖云服务）

#### 10.0.1 前端构建与部署策略

- **前端构建模式**：Next.js 15 使用 `output: 'export'`（静态导出），输出 `out/` 目录纯静态资源
  - 优点：无需 Node 运行时容器，nginx 直接 serve，部署简单 / 资源占用低
  - 取舍：放弃 RSC 服务端渲染、API routes 等需运行时的能力（不影响本项目，所有动态数据通过浏览器调 FastAPI 拿）
  - 动态路由（如 `/flow/[flow_id]/node/[node_id]`）走客户端渲染：构建期生成壳页面 + `useParams()` + `fetch()` 拉数据
- **构建产物挂载**：
  - 开发期：`pnpm dev` 起 Next 开发服务器
  - 生产期：CI / 本地执行 `pnpm build` → 产出 `frontend/out/` → Docker build 时 `COPY out/ /usr/share/nginx/html`，或挂 volume

#### 10.0.2 Nginx 路由策略

```nginx
# nginx.conf 关键路由
server {
    listen 80;
    server_name 192.168.2.44;

    # 1. API 反代到 FastAPI
    location /api/ {
        proxy_pass http://flow-api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 90s;
    }

    # 2. WebSocket (实时流状态推送，可选)
    location /ws/ {
        proxy_pass http://flow-api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 3. 静态前端（Next.js export 产物）
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri.html $uri/index.html /index.html;
        # /index.html 兜底：客户端路由（/flow/xxx/node/yyy）由前端 router 处理
    }

    # 4. Mattermost 不通过 nginx 代理（同机 8065 端口直接对外）
    # 用户访问 http://192.168.2.44:80     → 本系统前端
    # 用户访问 http://192.168.2.44:8065   → Mattermost
}
```

### 10.1 测试环境配置（`.env`）

```env
# === 模式开关 ===
APP_MODE=demo                              # demo / prod
DEMO_INBOX=1624456575@qq.com

# === Mattermost ===
MATTERMOST_URL=http://192.168.2.44:8065
MATTERMOST_TEAM=laios
MATTERMOST_BOT_USERNAME=offboarding-bot
MATTERMOST_BOT_TOKEN=${MM_BOT_TOKEN}       # Personal Access Token，从环境注入
MATTERMOST_INCOMING_WEBHOOK=${MM_WEBHOOK}  # 备用简单推送通道

# === SMTP（QQ 邮箱，演示统一收件箱） ===
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=true
SMTP_USER=1624456575@qq.com
SMTP_PASSWORD=${QQ_SMTP_AUTH_CODE}         # 16 位授权码，不入库
SMTP_FROM_NAME=离职流程 Bot

# === 深链与鉴权 ===
DEEPLINK_BASE_URL=http://192.168.2.44:3000
JWT_SECRET=${JWT_SECRET_32B}               # 32 字节随机串
TOKEN_EXPIRY_HOURS=24

# === 数据库 ===
POSTGRES_DSN=postgresql+asyncpg://flow:flow@postgres:5432/flow_db
REDIS_URL=redis://redis:6379/0             # 用于 jti 黑名单 + 任务队列

# === 对象存储（MinIO，节点附件 / 离职证明 PDF / 截图） ===
MINIO_ENDPOINT=http://192.168.2.44:9000
MINIO_ACCESS_KEY=admin                     # v1 用 root；生产建议建 Service Account
MINIO_SECRET_KEY=${MINIO_SECRET}
MINIO_BUCKET_ATTACHMENTS=offboarding-attachments
MINIO_BUCKET_EXPORTS=offboarding-exports
MINIO_BUCKET_SCREENSHOTS=offboarding-screenshots
MINIO_USE_SSL=false

# === LLM（可选） ===
LLM_PROVIDER=glm
GLM_API_KEY=${GLM_API_KEY}
```

**安全约束**：
- `.env` 必须加入 `.gitignore`
- 提交 `.env.example` 仅含字段名 + 占位符
- `${QQ_SMTP_AUTH_CODE}` / `${MM_BOT_TOKEN}` / `${JWT_SECRET}` 通过 OS 环境变量或 Docker secrets 注入
- CI / 部署脚本不打印 env 内容

### 10.2 启动顺序（Docker Compose）

```
1. postgres + redis        （基础设施）
2. flow-api (FastAPI)      （等待 DB 就绪 → 运行 alembic 迁移 → 启动 uvicorn）
3. nginx                   （反向代理 + 静态前端，依赖 flow-api 健康检查通过）
```

**前端构建**（在 build 阶段或部署前完成，不需要运行容器）：
```bash
cd frontend && pnpm install && pnpm build
# 产出 frontend/out/*  →  打包进 nginx 镜像 / 挂载 volume
```

**首次启动后执行**：
```bash
docker compose exec flow-api python scripts/seed_demo_data.py
```

**部署到 192.168.2.44**：
```bash
# 一键启动（已构建前端 + 镜像）
docker compose -f docker-compose.yml --env-file .env up -d

# 验证
curl http://192.168.2.44/api/health          # 应返回 200
curl -I http://192.168.2.44/                 # 应返回 200，Content-Type: text/html
```

---

## 11. 非功能性需求

| 维度       | 要求                                                                 |
| ---------- | -------------------------------------------------------------------- |
| 性能       | 单流程实例端到端 < 7 天，节点状态查询 < 200ms                       |
| 可靠性     | LangGraph checkpoint 持久化，进程崩溃可从最近节点恢复               |
| 可观测性   | 每次三态决策有审计日志，状态机变迁有完整时序记录                    |
| 安全       | 深链 token 一次性 / 有过期；SSO 强制；外部系统调用走密钥管理        |
| 可扩展性   | 流程模板可扩展（v1 硬编码，v2 接入 agent-builder 后可视化编排）     |
| 内网约束   | 全部组件可在 `192.168.2.44` 单机离线运行（外网仅 LLM API 调用可选）|

---

## 12. 开源参考与调研对象

> 这些项目将在 Design Doc 阶段对比，PRD 阶段先列待调研清单

| 项目                          | 调研角度                                          |
| ----------------------------- | ------------------------------------------------- |
| **LangGraph**                 | 状态图、checkpoint、interrupt 机制               |
| **Temporal / Cadence**        | 工作流引擎对比（vs LangGraph 的取舍）            |
| **Camunda 8 / Zeebe**         | BPMN 工作流参考（人工任务、状态机标准）          |
| **n8n / Activepieces**        | 可视化流程编排（agent-builder 阶段参考）          |
| **Dify / LangFlow / Flowise** | 低代码 Agent 平台参考                             |
| **CrewAI / AutoGen**          | 多 Agent 协作模式参考                             |
| **React Flow**                | 前端状态机可视化（必选）                          |

---

## 13. 里程碑（粗）

| 阶段       | 内容                                                        | 输出物                            |
| ---------- | ----------------------------------------------------------- | --------------------------------- |
| M0 PRD     | 本文档评审通过                                              | PRD.md                            |
| M1 设计    | 详细架构、状态机图、API 契约、开源对比                      | docs/architecture.md, design.md   |
| M2 核心后端 | LangGraph 流程 + 三态决策 API + Mock 外部系统               | flow-engine 跑通端到端            |
| M3 通知    | 邮件（QQ SMTP）+ Mattermost 集成、深链 token 一键登录、seed 测试组织数据 | 通知通道闭环 + 演示模式可端到端跑通 |
| M4 前端    | 多角色 dashboard + 状态机可视化                             | web 可演示                        |
| M5 集成    | 对接真实外部系统（先 HR 和资产）                            | 真实链路 demo                     |
| M6 演示    | 离职流程端到端演示视频 / 截图、面试讲稿                     | 演示材料                          |

---

## 14. 待确认问题

1. ✅ 演示阶段全程 Mock 外部业务系统（资产 / AD / 财务），HR 目录用 Mattermost 替代；真实集成留到 M5
2. ❓ LLM 在本系统中**具体在哪些节点起作用**？目前看 LangGraph 主要是状态机，AI 介入点可能是：
   - 离职申请的语义抽取（员工填写的离职原因 → 结构化字段）
   - 知识交接节点的文档智能整理
   - 卡点诊断（流程超时时，AI 分析原因并给 HR 建议）
3. ✅ Mattermost 已部署到 `http://192.168.2.44:8065`（team `laios`，v0.3 确认）
4. ❓ 演示阶段 SSO 是否直接用 Mattermost OAuth2？
   - **v0.3 暂行方案**：邮件深链 Token 一键登录（§6.2），免 SSO 即可演示完整闭环
   - SSO 留作 M5 阶段补充
5. ❓ 是否需要支持**流程模板自定义**（v1 不做，确认下）？
6. ✅ 用 Mattermost 当 "HR 目录" + 邮件统一收件箱（`1624456575@qq.com`）是面试演示的合理精简方案
7. ❓ Token 失效策略最终采用「一次性 + 24h 兜底」还是「仅 24h 过期可复用」？
   - **v0.3 暂定**：一次性消费（`jti` 黑名单），换 session 后失效；session 24h 过期
   - 优点：链接转发被复用风险最低
   - 缺点：用户中途关闭浏览器需要点二次邮件（可通过 `POST /api/notifications/{id}/resend` 重发）

---

## 15. AI 能力与边界声明（v0.4 新增）

### 15.0 面试评分点对照表

| # | 评分点 | 在 PRD 中的位置 | 状态 |
|---|--------|----------------|------|
| 1 | 创建"离职案件"数据记录 | §6.1 `flow_instances` 表 + §4.1 DAG 起点 `apply` 节点 | ✅ 已设计 |
| 2 | 至少 3 个角色（员工 / HR / 运维）| §3 + §9.1 — 实际 8 个角色（员工 / 上级 / 总监 / HR 专员 / HR 总监 / IT / 财务 / 法务）超出要求 | ✅ 已设计 |
| 3 | 至少 5 个任务步骤 | §4.1 — 实际 10 节点（apply / manager_review / hr_initial / 5 并行 / hr_final / applicant_final_confirm / archive）超出要求 | ✅ 已设计 |
| 4 | 每个任务设置状态 | §6.1 `node_states.status` enum (`pending / waiting_human / done / rejected / returned`) | ✅ 已设计 |
| 5 | **模拟 AI 输出下一步** | **§15.1** AI 推理下一步建议 | ✅ v0.4 新增 |
| 6 | 模拟任务逾期或证据缺失 | **§17** 逾期与证据缺失模拟 | ✅ v0.4 新增（部分原 NOTI-05 已有逾期扫描） |
| 7 | 输出后台报告（进度 / 阻塞 / 需真人 / 建议下一步） | **§15.2** AI 后台报告 + **§16.3** Mattermost @bot 报告输出 | ✅ v0.4 新增 |
| 8 | 标出 AI 不能做、必须真人确认的动作 | **§15.3** AI 边界声明清单 | ✅ v0.4 新增 |
| 9 | （加分项）API/Webhook/RPA 自动动作 | **§18** 自动动作节点演示 | ✅ v0.4 新增（加分） |
| + | （简化版核心）Mattermost @bot 启动 | **§16** Mattermost Bot 入口 | ✅ v0.4 新增 |

### 15.1 AI 推理下一步建议（LLM-04）

**触发场景**：
- HR 在 Dashboard 选某个流程实例，点击 "AI 建议下一步" 按钮
- Mattermost @bot 中 `@offboarding-bot suggest <flow_id>` 命令

**输入**：
- 流程 ID → 后端读 `flow_instances` + `node_states` 全部记录 + `context.node_results[]`

**Prompt（system + user）**：
```
[system]
你是 HR 离职流程顾问。基于以下流程状态，输出"建议下一步"。
要求：
1. 用简洁中文（≤ 200 字）
2. 必须包含：当前节点 / 阻塞原因（如有）/ 推荐操作 / 责任人
3. 不要建议执行动作（系统不允许 AI 自动操作），只给建议供人工参考
4. 若流程已结束，直接告诉用户已结束

[user]
{flow_summary_json}
```

**输出**：
- 文本（直接展示给 HR / 在 Mattermost 频道回复）
- 标签 `<ai-suggestion>` 包裹以便前端识别 AI 来源

**降级策略**：LLM 失败 → 显示规则模板回退 ("当前节点是 X，责任人 Y，已等待 Z 小时，建议邮件催促或重新分配")

### 15.2 AI 后台报告（LLM-05）

**触发场景**：
- HR 在 Dashboard 点击"生成报告"
- Mattermost @bot 中 `@offboarding-bot report <flow_id>` 命令
- 定时任务每天 9am 自动生成所有 active 流程的报告，邮件发给 HR 主管

**输入**：
- 同 §15.1，加上时间窗口（默认全程）

**输出格式**（结构化 markdown，前端 / Mattermost 渲染）：

```markdown
# 流程报告：张三 离职流程
> 生成时间：2026-05-17 09:00 | 流程 ID: 8f3a2b1e

## 1. 当前进度
- 已完成节点：4/10（apply / manager_review / hr_initial / device_return）
- 当前激活：access_revoke / knowledge_handover / finance_settle / legal_sign（4 个并行）
- 预计完成时间：2026-05-20（基于历史平均节点耗时）

## 2. 阻塞事项
- ⚠️ `knowledge_handover` 节点已等待 36 小时（超过 24h SLA）
  - 责任人：li.si（直属上级）
  - 上次提醒：2026-05-16 14:00
- ⚠️ `legal_sign` 节点 result_text 为空（已提交但内容缺失，疑似证据缺失）

## 3. 是否需要真人协助
- **是** — 需要 HR 介入：
  - 联系 li.si 推进知识交接（或考虑重新分配给同事）
  - 与 legal.eve 核实法务签字内容缺失原因

## 4. 建议下一步（仅供参考，需人工确认）
1. 重发知识交接节点提醒邮件给 li.si + cc HR
2. 联系 legal.eve 补全签字结果文本
3. 若 24h 内无响应，考虑流程退回到 hr_initial

---
*由 AI 生成 — 所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点*
```

**降级策略**：LLM 失败 → 用规则模板回退（按当前节点状态机械列出阻塞项，无智能建议段）

### 15.3 AI 能力边界声明（必须显式告知用户）

为了让用户清楚 AI 的角色，**所有 AI 输出场景必须显式声明边界**：

#### AI 可做（系统允许）

| 能力 | 实现 |
|------|------|
| 总结节点结果（生成申请人确认邮件摘要段）| LLM-02 |
| 推理建议下一步（输出给 HR 参考）| LLM-04 / §15.1 |
| 生成后台报告（进度 / 阻塞分析 / 建议）| LLM-05 / §15.2 |
| 自然语言查询流程状态（Mattermost @bot）| §16.2 |
| 异常检测（标记疑似证据缺失）| §17.2 |

#### **AI 绝对不能做（必须人工确认）**

| 动作 | 为什么 AI 不能做 |
|------|-----------------|
| 三态决策（继续 / 退回 / 拒绝）| 责任落到具体人头上，涉及法律 / 财务边界 |
| 修改流程模板 / 添加节点 | 流程结构决策需要管理层签字 |
| 删除流程实例或节点记录 | 审计完整性必须保护 |
| 直接调用外部业务系统 API（实际归还设备 / 关闭权限 / 转账）| 业务操作有不可逆后果 |
| 改写历史 `action_logs` 或 `result_text` | 审计链不可变更 |
| 替申请人确认最终结果 | 申请人确认是流程合规的法律要求 |
| 发送非系统模板邮件 | 邮件代表公司发声，必须人工 review |

#### UI / Bot 输出规范

- 所有 AI 生成的内容必须带 `🤖 AI 生成` 角标
- 报告 / 建议末尾固定 disclaimer："*由 AI 生成 — 所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点*"
- Mattermost @bot 回复时显式标 `[AI 助手]`

---

## 16. Mattermost @bot 入口（v0.4 新增）

### 16.1 定位

**Mattermost @bot 是面试 demo 的核心入口之一**（与前端 + 邮件并列），让演示者可以在 IM 里完成「启动流程 / 查进度 / 生成报告」全部操作，不必切换到浏览器。

### 16.2 支持的命令

通过 Mattermost `@offboarding-bot` 提及（mention）或 Outgoing Webhook 触发：

| 命令 | 功能 | 示例 |
|------|------|------|
| `@offboarding-bot start <username>` | 创建一个新的离职流程实例 | `@offboarding-bot start zhang.san` |
| `@offboarding-bot status <flow_id>` | 查询流程当前状态（结构化） | `@offboarding-bot status 8f3a2b1e` |
| `@offboarding-bot report <flow_id>` | 生成 AI 后台报告（§15.2） | `@offboarding-bot report 8f3a2b1e` |
| `@offboarding-bot suggest <flow_id>` | AI 建议下一步（§15.1）| `@offboarding-bot suggest 8f3a2b1e` |
| `@offboarding-bot list [active\|completed\|stuck]` | 列出流程实例（默认 active）| `@offboarding-bot list stuck` |
| `@offboarding-bot help` | 命令帮助 | `@offboarding-bot help` |

### 16.3 实现方式

**入站通道**（Bot 接收命令）：
- **优先方案**：Mattermost Outgoing Webhook，配置 trigger word `@offboarding-bot`，POST 到 `http://flow-api:8000/api/mattermost/webhook`
- **备选方案**：Mattermost Bot WebSocket Event Subscription，监听 `posted` 事件解析 `@offboarding-bot` 提及

**出站通道**（Bot 回复）：
- 使用 Bot Personal Access Token 调 `POST /api/v4/posts` 在原频道回复
- 富文本卡片（attachments）输出报告 / 进度 / 建议

### 16.4 启动流程的回复样例（评分点 1-9 一次性输出）

```
🤖 [AI 助手] 已启动离职流程
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 案件 ID: 8f3a2b1e
👤 离职员工: 张三 (zhang.san)
📅 创建时间: 2026-05-17 09:23

【角色清单】
• 离职员工: zhang.san
• 直属上级: li.si
• HR 专员: hr.alice
• HR 总监: hr.bob
• IT 设备管理员: it.charlie
• 财务专员: fin.david
• 法务合规: legal.eve

【任务步骤（10 个节点）】
1. ⏳ 离职申请          [waiting_human]   👤 zhang.san
2. ○ 上级审批
3. ○ HR 初审
4. ○ 设备归还      ┐
5. ○ 权限回收      │
6. ○ 知识交接      ├ 并行
7. ○ 财务结算      │
8. ○ 法务签字      ┘
9. ○ HR 终审
10. ○ 申请人最终确认
11. ○ 归档

【当前进度】 0/10 完成（刚启动）

【阻塞事项】 暂无 — 等待 zhang.san 填写离职申请

【是否需要真人协助】 是 — 张三需要先填写离职申请表

【建议下一步】 已自动发邮件给 zhang.san 触发离职申请填写

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ℹ️ AI 不会自动操作任何节点；所有决策（继续/退回/拒绝）必须人工确认
*Type `@offboarding-bot report 8f3a2b1e` 查看详细 AI 报告*
```

### 16.5 安全约束

- Outgoing Webhook 必须配置 **Token 校验**（防伪造请求）
- 命令解析使用白名单 + 严格正则，**不要 eval 任何用户输入**
- `start` 命令需校验提及者的 Mattermost role（仅 HR 角色或 Admin 可触发）

---

## 17. 任务逾期与证据缺失模拟（v0.4 新增）

### 17.1 逾期模拟

**默认配置**：每个 `waiting_human` 节点 SLA = 24h（可在 `.env` 调整 `NODE_TIMEOUT_HOURS=24`）。

**演示模式快速触发**（不用真等 24 小时）：
- `.env` 加 `DEMO_TIMEOUT_OVERRIDE_HOURS=0.05`（约 3 分钟即触发）
- 或 Mattermost `@offboarding-bot simulate-timeout <flow_id> <node_name>` 立即标记超时
- 或 HR Dashboard 提供 "模拟逾期" 按钮（仅 demo 模式可见）

**超时后行为**：
- APScheduler `timeout_scan` job 每分钟扫描 → 标记 `node_states.is_overdue=True`
- 触发 NOTI-05 提醒重发（assignee + HR）
- AI 报告（§15.2）的 "阻塞事项" 段自动列出所有超时节点

### 17.2 证据缺失模拟

**定义**：节点 `result_text` 长度 < 5 字符（或显式标记 `evidence_missing=True`）。

**演示模式触发**：
- 演示者在节点表单"提交"决策时只填 "ok" / "完成" 等极短文本
- 或直接 `@offboarding-bot simulate-evidence-missing <flow_id> <node_name>`

**AI 报告中的体现**：
- §15.2 的 "阻塞事项" 段会列出 "⚠️ XXX 节点 result_text 为空 / 内容过短，疑似证据缺失"
- HR 在 Dashboard 看到节点旁边出现 `⚠️ 证据待补充` 红色标签

**非演示模式（生产）**：
- 节点表单前端校验 `result_text` 至少 10 字符
- API 后端二次校验

---

## 18. 加分项：自动动作节点（API/Webhook 演示）（v0.4 新增）

### 18.1 目标

在 v1 演示一个**自动动作节点**，证明本架构不仅支持人机交互节点，也能挂自动动作（API / Webhook / 未来的 RPA）。这是 §15.0 评分点 #9 的"加分项"。

### 18.2 设计

**新增节点类型**：`AutoNode`（与 `HumanNode` 并列）
- 节点函数内**不调用 `interrupt()`**，直接执行业务逻辑后返回
- 同样要双写 `node_states`（status 直接 `done`）+ `action_logs`（actor=`system:auto`）
- 仍然触发 `notification_outbox`（让 HR 在 Mattermost 看到"自动执行"消息）

**演示节点**：`auto_archive_to_storage`
- **位置**：插入到 `applicant_final_confirm` → `archive` 之间作为 `archive` 节点的前置自动步骤
- **行为**：调用一个 mock 的 HTTP API（`POST http://mock-archive-service:5000/archive`），把整个流程的 `node_results` JSON 归档到 mock 服务
- **mock 服务**：在 `docker-compose.yml` 加一个简单的 `mock-archive-service` 容器（FastAPI 10 行）接收 POST 写入 `/data/{flow_id}.json` 文件

### 18.3 演示话术（面试时讲）

```
"看，这里有一个 auto_archive_to_storage 节点，状态直接是 done，actor 是 system:auto
这证明本架构同时支持人机交互节点（三态决策）和自动节点（API/Webhook）
未来要接 RPA 或者业务系统真实 API，模式完全一致：节点函数里调外部 API，双写业务表
但是 — 注意这里我故意没有把 device_return 等节点改成自动节点，因为：
1. 设备归还涉及法律责任，必须人工签字
2. 财务结算金额变动需要财务 review
3. 法务签字本质是法律行为，AI/自动节点无权代签
这就回到 §15.3 的 AI 边界声明：能不能自动做 ≠ 应不应该自动做"
```

### 18.4 实现优先级

- **v1（演示）**：仅实现 `auto_archive_to_storage` 一个节点 + mock 服务
- **v2**：接真实的资产系统 API（device_return 节点的写回操作）/ AD（权限回收的执行）等
- **v3**：接 RPA 框架（如 UiPath / Browser-use）演示更复杂自动化

---

> 下一步：基于本 PRD，进入 **架构设计文档（design.md）** 阶段，重点细化 LangGraph 节点契约、API 接口、状态机图、开源项目对比表。
