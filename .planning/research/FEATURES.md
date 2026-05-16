# Feature Research — AI 驱动的离职流程执行系统

**Domain:** State-machine driven workflow execution platform (HR offboarding 形态，但内核是 process engine)
**Researched:** 2026-05-16
**Confidence:** MEDIUM-HIGH（行业模式 HIGH；中国 HR SaaS 细节 LOW）

> **本项目独特定位（贯穿全文）**
> 不是「HR offboarding 业务系统」，是一个**展示型 process engine**，借离职流程这个有完整生命周期的场景，把"状态机驱动 + 人工中断恢复 + 双通道通知 + 一键登录 + 三态决策 + 申请人闭环"这一整套**流程平台能力**端到端呈现出来。
>
> 因此 features 分类的核心抓手是：
> - **流程引擎（process engine）features** = MUST，是平台本身能力
> - **业务系统（business app）features** = NOT，越做越像 HR 工具，与定位反向
>
> 所有 features 都按这把尺子归类。

---

## 0. 流程引擎 vs 业务系统的功能边界（核心定位辨析）

> 这是回答"v1 做什么 / v2 做什么 / 永远不做什么"的根本依据。

| 维度 | 流程引擎 features（**本项目要做**） | 业务系统 features（**本项目不做**） |
|---|---|---|
| **核心数据结构** | flow_instance / node_state / action_log（通用状态机原语） | device_inventory / payroll_record / contract（领域实体） |
| **节点行为** | 统一三态决策 + 自由文本 result | 每节点差异化表单 / 字段 / 验证逻辑 |
| **跨流程查询** | "哪些流程卡住了 / 平均节点耗时" | "张三的设备清单 / 王五的报销明细" |
| **集成方式** | 通知 outbox / webhook / IM bot | 业务系统 API client（资产 / AD / 财务） |
| **演进方向** | 流程模板可视化编排（v3 agent-builder） | 接入更多业务系统、覆盖更多 HR 场景 |
| **类比对象** | Camunda Zeebe / Temporal / LangGraph / Argo Workflow | Workday HCM / ServiceNow HR / 北森 |

**判断标准（红线测试）**：
> 一个 feature 提出来后，问"如果换成请假流程 / 报销流程，这个能力还成立吗？"
> - **YES** → 是流程引擎能力，归 MUST 或 DIFF
> - **NO**（只在离职场景成立）→ 是业务系统能力，归 NOT

举例：
- 三态决策 → 任何审批流程都适用 → **流程引擎能力，MUST**
- 设备清单录入表单 → 只有 IT 节点用 → **业务系统能力，NOT**
- 申请人最终确认时间线邮件 → 任何端到端流程都需要"对申请人闭环" → **流程引擎能力，DIFF**

---

## 1. Table Stakes（不做就不像一个流程引擎）

> 这里是工作流引擎类产品的最低基线。本项目 v1 必须全部覆盖，否则演示时会被一眼看出"不是真平台"。
> 行业参考：Camunda 8 / Temporal / Zeebe / n8n / Activepieces。

| # | Feature | 为什么是 baseline | 复杂度 | v1 已规划? | PRD 映射 |
|---|---|---|---|---|---|
| TS-01 | **状态机引擎 + 持久化** | 工作流引擎的字面含义。无 checkpoint 就只是脚本 | MED | YES | FLOW-01/03 |
| TS-02 | **人工任务（human task）+ 中断/恢复** | BPMN User Task 是业内基本概念，所有 enterprise workflow engine 都有 | MED | YES | FLOW-01, AUTH-02 |
| TS-03 | **二态/三态决策（approve/reject [+return]）** | 审批流程的最小决策原语。三态在中国 OA / HR 系统是标配，西方系统 approve/reject 二态 + rework button 实现同效 | LOW | YES | FLOW-04 |
| TS-04 | **DAG / 顺序 + 分支边** | 没有分支就不是流程，只是脚本。Conditional edges 是 LangGraph / Camunda / Temporal 共有原语 | MED | YES | FLOW-01/05 |
| TS-05 | **每节点 assignee（按人 / 按角色 / 按规则）** | 没法把任务派给具体人就不是协作流程 | LOW | YES | NOTI-01 |
| TS-06 | **任务通知（至少一个通道）** | 通常 email 是默认通道。没有通知就没人知道有任务 | LOW | YES | NOTI-01 |
| TS-07 | **审计日志 / action history** | 每次三态决策必须有 actor + timestamp + reason。SOC2 / GDPR 强要求 immutable audit log | LOW | YES | FLOW-02, 表 action_logs |
| TS-08 | **流程进度可视化（基本时间线）** | "现在到第几步、卡在谁那" 是流程平台用户最高频的问题 | MED | YES | WEB-04/05 |
| TS-09 | **崩溃恢复（durable execution）** | Temporal/LangGraph 的核心卖点。进程挂了不能丢任务 | MED | YES | FLOW-03 |
| TS-10 | **流程实例查询 / 列表（按状态 / 按 assignee）** | HR Dashboard 的最低能力。"我管的流程"、"我待办" | LOW | YES | WEB-05 |
| TS-11 | **任务认领（claim/release）** | BPMN 标准能力。即使 v1 一人一角色，逻辑也要在 | LOW | 部分 | AUTH-02（assignee 校验等价于隐式 claim） |
| TS-12 | **退回（return / send-back）路径配置** | 审批流的标配。仅 approve/reject 流程在中国体系下被认为"不完整" | MED | YES | FLOW-05 |

**结论**：v1 PRD 已覆盖 12/12，质量门 ✅。

---

## 2. Differentiators（这个项目的竞争优势 / 面试亮点）

> 在 table stakes 之上，能让面试官眼前一亮的能力。不是"做了多少功能"，而是"对'流程平台 vs 业务平台'的分离思考有多深"。

| # | Feature | 为什么是亮点 | 复杂度 | v1? | PRD 映射 | 面试卖点指数 |
|---|---|---|---|---|---|---|
| **DF-01** | **双层状态分离：LangGraph runtime ≠ 业务表** | 这是本项目最深的设计决策。绝大多数 demo 项目直接读 framework state，本项目把"引擎私有 checkpoint"和"业务可读 source-of-truth"显式拆开，是真正生产级思路（Temporal 自身也是 history table ≠ application state） | HIGH | YES | PRD §5.3 | ★★★★★ |
| **DF-02** | **申请人最终确认节点（applicant final confirm）** | 流程平台对申请人的"闭环回执"——绝大多数审批系统申请人只在开头出现一次，之后就消失。把它显式建模为最后一个 human node 是"流程对全角色负责"的思想体现 | MED | YES | FLOW-06, PRD §4.5 | ★★★★★ |
| **DF-03** | **邮件深链 JWT 一键登录（magic link）** | passwordless 登录 + 流程上下文绑定的组合。jti 一次性消费 + role/assignee 三元组绑定是教科书级实现（行业参考 Clerk / FusionAuth magic link） | MED | YES | AUTH-01/02/03 | ★★★★ |
| **DF-04** | **统一通用节点（自由文本 + 三态）** | 反 over-engineering 的设计选择：v1 不为每个节点写差异化表单，统一抽象，把"流程引擎能力"和"业务字段"显式解耦。`payload` JSONB 留给 v2 业务扩展 | LOW | YES | FLOW-04, PRD §4.2 | ★★★★ |
| **DF-05** | **邮件 + IM 双通道并行通知** | 邮件是正式 audit trail，IM 是触达加速器。"互补不替代"的设计——很多 demo 项目只做一个。Mattermost Interactive Message Buttons 让 IM 直接成为操作入口（v2） | MED | YES | NOTI-01/02 | ★★★ |
| **DF-06** | **演示模式：统一收件箱 + 角色前缀 + alias 邮箱** | 一位演示者用一个邮箱演 8 角色的工程化解法。`APP_MODE=demo` 开关 + `realbox+username@domain` 别名邮箱，是 demo / prod 切换的真实工程思维 | LOW | YES | NOTI-03, PRD §7.4 / §9.1.3 | ★★★★ |
| **DF-07** | **节点结果累积到 context.node_results[]** | 让申请人最终确认能聚合渲染时间线 — 这是"流程结果对申请人可解释"的载体。也为 LLM 摘要提供天然输入 | LOW | YES | PRD §4.3.1 | ★★★ |
| **DF-08** | **LLM 用作"流程末端摘要"而非主路径** | 反「AI 是一切」的克制设计：LLM 仅用于聚合各节点 result_text 生成自然语言总结段，失败降级到原始版本，**不阻塞流程**。这恰好对应 PRD「这不是 ChatBot」的核心判断 | LOW | YES | LLM-01/02/03 | ★★★★★ |
| **DF-09** | **超时扫描后台任务（24h 提醒）** | 工作流引擎的 SLA 概念的简化实现。即使是演示，"卡了 24h 自动催办"也比"永远 waiting" 显得专业 | LOW | YES | NOTI-05 | ★★ |
| **DF-10** | **流程模板 Python 硬编码（StateGraph）** | 反 over-engineering：v1 不做可视化编排，直接代码定义 DAG。这反而是 Temporal / Argo 的主流路线（code-first 流派），不是缺点。讲清楚 v3 才上 agent-builder 是 roadmap 成熟度的体现 | LOW | YES | FLOW-01, PRD §1.3 | ★★ |

**面试亮点 Top 3 推荐**：
1. **DF-01 双层状态分离** — 体现对工作流引擎本质的理解（runtime state 是引擎细节，business state 才是平台资产）
2. **DF-02 申请人最终确认** — 体现产品思维（流程平台要对全角色闭环，不止对 HR）
3. **DF-08 LLM 用作末端摘要** — 反 ChatBot 思维的克制 + 降级设计

---

## 3. Anti-Features（明确不做 — 防 scope creep）

> 这些 features 表面合理，但做了就会让项目滑向"业务系统"或"演示项目过度复杂"。每条都有"为什么不做"和"如果非要做该怎么做"。

| # | Anti-Feature | 看起来该做 | 实际问题 | 替代方案 | 来自 PRD §1.3/§4.4 ? |
|---|---|---|---|---|---|
| **NOT-01** | **每节点差异化表单 / 字段** (设备清单的完好/损坏/折旧选项；财务的工资单字段) | "看起来才像真离职系统" | 一旦做了就是业务系统，与 v1 定位矛盾。8 个节点 × 5 个字段 = 40 个表单要维护，掩盖流程引擎本质 | 统一通用表单 + 自由文本 + `payload` JSONB 留给 v2 | YES |
| **NOT-02** | **与外部业务系统真实 API 集成** (资产管理 / AD/LDAP / 财务) | "离职系统不接 AD 怎么自动收权限" | v1 演示不需要，集成对接是无底洞，3 周做不完。架构上 `integration/` 目录留适配器接口即可 | 通用文本 + 三态决策模拟人工执行 | YES |
| **NOT-03** | **流程模板可视化编排 / DAG 编辑器** | "BPM 不就是拖拽吗" | 自研 visual editor 至少 6 周。LangGraph code-first 在 demo 阶段完全够，反而符合 Temporal 流派 | v3 接入 agent-builder 或 Camunda Modeler 嵌入 | YES |
| **NOT-04** | **多种离职类型流程**（主动 / 被动 / 协议 / 退休） | "完整 HR 系统都有这些" | 4 个模板 = 4 倍维护成本。v1 一个 `standard_offboarding` 把双层状态 / 三态 / 并行 / 申请人确认全打通就够 | flow_template 字段已预留，v2 增加新模板即可 | YES |
| **NOT-05** | **节点附件上传** (设备照片 / 签字扫描件) | "签字交接总要附件吧" | 文件存储 / 安全扫描 / 链接生成是独立子系统，跟流程引擎正交，引入会喧宾夺主 | 留接口，前端禁用上传按钮 | YES |
| **NOT-06** | **节点二级子流程（执行 + 审核）** | "权威节点应该有复核" | 二级子流程让状态机变成嵌套图，调试 / 可视化复杂度指数上升。所有 8 节点单层就足够演示 | 流程模板字段 `payload.sub_workflow` 保留扩展点 | YES |
| **NOT-07** | **SSO 集成（OIDC / SAML / LDAP）** | "企业系统不上 SSO 不像话" | 演示用邮件深链一键登录已等价完成"免账号密码"目标。SSO 引入会绑死某个 IdP（Mattermost OAuth、Keycloak、企业 AD）增加部署复杂度 | 一键登录 = passwordless 等效；生产化阶段再接 SSO | YES |
| **NOT-08** | **企业微信 / 飞书适配器** | "国内 HR 都在用这俩" | 演示阶段 Mattermost 已经能跑通"IM 双通道"语义，适配器实现是重复劳动。预留 `notification/adapter` 接口比直接实现重要 | 适配器接口预留，v2 按需补 | YES |
| **NOT-09** | **移动端 / 响应式** | "扫码审批多方便" | 演示场景是面试官在 PC 上看 demo，Mobile-first 适配 + 触摸交互调优至少 1 周，没有 ROI | Desktop-first；CSS 用 Tailwind 响应式 utility 减少未来重写成本 | YES |
| **NOT-10** | **多语言 / i18n** | "国际化是基础能力" | 中文界面 + 中文邮件足够覆盖目标演示场景。i18n 框架引入 + 文案外提是纯成本，无收益 | 全中文硬编码 | YES |
| **NOT-11** | **可视化状态机图（React Flow / Mermaid 实时渲染）** | "BPMN 工具不都有流程图吗" | 实时同步状态到图节点 + 动画 + 高亮当前节点至少 3 天。Demo 时一张静态 DAG 截图 + 时间线表格效果相当 | 截图放 PRD / README，前端时间线表格替代 | 隐含（未列） |
| **NOT-12** | **通用聊天界面 / ChatBot 风格交互** | "AI 项目不就是聊天吗" | 跟项目定位反向 — 这恰是 PRD §1.3 第一条非目标 | 操作面板（表单 + 按钮）+ LLM 仅做幕后摘要 | YES |
| **NOT-13** | **多租户 / SaaS 化** | "企业系统都是多租户" | 单实例 demo 用 0 多租户需求。引入 tenant_id / 数据隔离会让所有 SQL 变复杂 | 单租户 + 注释里说明 v2 加 tenant_id 列 | 隐含 |
| **NOT-14** | **权限管理系统（RBAC 配置后台）** | "总要管权限吧" | role 字段 hardcode 在 seed 数据里 6 种就够。配置后台是独立子系统 | role 写死 + JWT payload 携带 + API 装饰器校验 | YES（PRD §1.3） |
| **NOT-15** | **节点级别的细粒度回滚（撤销最近一步）** | "不小心点错怎么办" | 反向状态机 / 反作用补偿是 saga pattern，复杂度极高。三态决策已经给了"退回"出口 | "退回到上游节点" 已是软回滚 | 隐含 |
| **NOT-16** | **流程指标 / BI 报表（平均耗时、SLA 达标率）** | "管理者要看数据" | 数据已经在 action_logs，但报表 UI / 图表渲染至少 2 天。Demo 阶段没有"积累的数据"可看 | 留 SQL 视图给 v2 BI 工具消费 | 隐含 |
| **NOT-17** | **自动节点（agent / service task 真实执行外部 API）** | "AI Agent 应该能自己执行任务" | 一旦 agent 真去调 AD/财务，就是业务系统了；且失败处理 / 重试 / 回滚是另一坨 saga 复杂度 | 所有节点 v1 都是 human node；agent node 留 v3 | 隐含 |

**Scope creep 红线**：以上 17 条任一进入 v1 都会爆 3 周时间预算。

---

## 4. 针对原始 9 个关键问题的明确答复

### Q1: 流程引擎 vs 业务系统功能边界？

**答**：见 §0 红线测试。一句话总结：**做"能被任何审批流程复用"的能力（流程引擎），不做"只在离职场景成立"的能力（业务系统）**。

参考：Camunda / Temporal / Zeebe 都是流程引擎，自己不提供业务字段；Workday / ServiceNow HR / 北森 是业务系统，自带千百个业务字段。本项目走前者路线。

### Q2: 三态决策（advance/return/reject）是行业标准还是创新？

**答**：**部分标准 + 部分中国式表达**。
- 西方 BPMN 体系：通常是二态（approve/reject）+ "rework button"（PeopleSoft、Oracle BPM 都有 Rework 按钮把文档退回 In Progress）
- 中国 OA / 钉钉 / 飞书 / 北森体系：三态明确（同意 / 退回 / 拒绝）是标配，与中国审批文化相关（领导习惯"打回去修改"而非直接拒绝）
- Camunda 等 BPMN 引擎：用 exclusive gateway + 多个 outcome 表达三态，但没有 native "return to previous step"

**结论**：三态决策**是"中国式审批"事实标准**，不是创新但也不是西方 BPMN 原生。本项目把它显式列为统一节点契约（FLOW-04）是合理的本地化选择，可以作为"了解中国 enterprise workflow 语境"的小亮点讲。

[Sources: [HR Approval Workflow Patterns](https://www.cflowapps.com/approval-workflow-design-patterns/), [Oracle PeopleSoft Rework Button](https://docs.oracle.com/cd/E28727_01/hcm91fp2/eng/psbooks/hepf/htm/hepf12.htm), [Camunda BPMN User Task](https://docs.camunda.org/get-started/quick-start/user-task/)]

### Q3: 并行节点（fan-out/fan-in）在 HR 工作流中的常见模式？

**答**：**标配能力，模式成熟**。
- BPMN 用 parallel gateway（AND gateway）的成对模式 — 一个 split + 一个 join 是 Camunda 推荐 best practice
- LangGraph 的 fan-out 通过多条 add_edge 自然实现，fan-in 通过多入度节点等待所有上游完成
- 本项目"设备归还 / 权限回收 / 知识交接 / 财务结算" 4 路并行 + 法务签字汇入 HR 终审 = 教科书式 fan-out/fan-in

**潜在坑**（PITFALLS.md 会再提）：LangGraph 并行节点的 state 合并语义 — 多个分支同时写同一个 state key 时的 reducer 行为需要明确测试。

[Source: [Camunda Parallel Gateway](https://docs.camunda.io/docs/components/modeler/bpmn/parallel-gateways/)]

### Q4: 邮件 + IM 双通道在工作流引擎中的成熟度？

**答**：**邮件是行业 default，IM 双通道是 enterprise upgrade**。
- 所有工作流引擎都内置 email 通道（Camunda Tasklist、Temporal SDK、n8n）
- IM 通道（Slack / Mattermost / Teams / 飞书 / 企业微信）通过 Incoming Webhook + Interactive Message Buttons 实现，Slack/Mattermost 都有成熟的 button → webhook 模式，n8n 有现成 template
- 本项目 v1 用 Mattermost Bot Token + Incoming Webhook 已经是标准做法
- "在 IM 直接点按钮决策"（PRD §7.2）是 v2 升级，目前邮件深链已经够用

**亮点角度**：很多 demo 项目只做一个通道，做双通道并标注"邮件正式归档 / IM 触达加速"的职责分工，是平台思维的体现。

[Sources: [Mattermost Interactive Messages](https://developers.mattermost.com/integrate/plugins/interactive-messages/), [Slack Approval Workflow](https://api.slack.com/best-practices/blueprints/approval-workflows)]

### Q5: "申请人最终确认"这种回执环节在行业里叫什么、怎么实现？

**答**：**没有统一术语，但概念存在**。
- 行业叫法分散：
  - **acknowledgment / final sign-off**（项目管理体系）
  - **exit packet acknowledgment**（HR offboarding 文档体系）
  - **applicant confirmation step**（自定义流程）
- HR offboarding 最佳实践：要求离职员工"confirm that they received, understood, and complied with company's policies"，一般通过签字纸质文件 / 邮件回执完成
- 但在**state-machine workflow engine 里把它显式建模为最后一个 human node**，并不常见 — 大多数实现把它放在流程之外的"邮件归档"步骤
- 本项目的实现路径合理：
  1. 流程模板里加 `applicant_final_confirm` 节点
  2. assignee = 离职员工本人
  3. 节点函数聚合 `context.node_results[]` 渲染汇总邮件
  4. 用同一套深链 token 让申请人一键登录
  5. 只给"确认 / 退回"两个动作（去掉 reject）

**亮点角度**：显式建模是本项目的差异化设计（DF-02），可以重点讲"流程对全角色闭环"的设计哲学。

[Sources: [Oyster - Offboarding Acknowledgment](https://www.oysterhr.com/glossary/offboarding), [HRCloud Offboarding Best Practices](https://www.hrcloud.com/blog/best-practices-for-employee-offboarding-process)]

### Q6: 卡点诊断 / 超时升级 / 自动重新分配等高级功能？

**答**：**enterprise BPM 标配，本项目按 v1 / v2 / v3 分级**。

| 能力 | 行业成熟度 | 本项目 v1 | v2 升级路径 |
|---|---|---|---|
| **SLA timer / deadline** | Camunda native (boundary timer event) | NOTI-05 (>24h 后台扫描) 简化版 | 节点级 SLA 配置 + DB 字段 |
| **自动升级** (>SLA 通知上级) | Cflow / Workato 都有 | NOTI-05 重发到 assignee + HR 等效 | 多级升级路径（manager → director → VP） |
| **自动重新分配** (assignee 不在 → 转给同角色其他人) | 高级 BPM 才有 | 不做 | v2 接入 HR 系统后做 capacity-based routing |
| **卡点诊断（bottleneck analytics）** | 多数有 dashboard | 不做 | action_logs 已有数据，v2 BI 表盘 |
| **AI 预测哪些任务会 miss SLA** | 2026 新趋势（predictive task routing） | 不做 | 可作为 v3 LLM 增强方向 |

**v1 落地**：仅 NOTI-05（24h 后台扫描 + 重发邮件给 assignee + HR）。这是基线，太简陋会被觉得"不专业"，太复杂会拖慢进度。

[Sources: [Cflow Escalation Rules](https://www.cflowapps.com/how-automated-escalation-rules-reduce-approval-bottlenecks/), [Predictive Task Routing](https://www.mymobilelyfe.com/artificial-intelligence/predictive-task-routing-stop-slas-from-sneaking-up-on-your-team/)]

### Q7: 审计 / 合规 / 操作日志的标准要求？

**答**：**SOC2 / GDPR 都强要求 immutable audit log**。
- 必有字段：actor / action / timestamp / target / before-after value
- 必须 tamper-evident（append-only，不可删改）
- 必须可按 actor 反查（GDPR data subject rights）
- 必须支持留存期管理（GDPR storage limitation）
- HR 数据是合规高敏感类（"the most attractive data set in the organization"）

**本项目落地**：
- ✅ `action_logs` 表已是 append-only 设计（每次三态决策一条记录，PRD §6.1）
- ✅ `notifications` 表记录通知发送 / 失败 / 重试
- ⚠️ v1 不实现"软删除标记 / 留存期到自动归档" — 可以在 PITFALLS.md 标记为"v2 必须补"
- ⚠️ v1 不做时间戳的密码学签名 / hash chain — over-engineering，不做

**亮点角度**：可以在面试时主动说"v1 已做 append-only audit，符合 SOC2 baseline；v2 才考虑 hash chain"，展示对合规的认知层级。

[Sources: [SOC2 + GDPR HR](https://hireroad.com/resources/soc-2-without-the-headache-hrs-step-by-step-survival-guide), [Immutable Audit Log Best Practices](https://www.sonarsource.com/resources/library/audit-logging/)]

### Q8: 流程模板自定义 vs 硬编码 DAG 的取舍？

**答**：**code-first vs visual editor 是两个流派，本项目站 code-first**。

| 流派 | 代表 | 优势 | 劣势 |
|---|---|---|---|
| **Code-first** (本项目) | Temporal / LangGraph / Argo / Prefect | 灵活、版本控制、IDE 支持、单元测试容易 | 业务方改不动 |
| **Visual editor** | Camunda Modeler / n8n / Activepieces / Zapier | 业务方可改 | 复杂逻辑表达困难、版本控制差、testing 弱 |

**2026 趋势**：sophisticated 团队 = Temporal (业务逻辑 code-first) + Camunda Modeler (BPM 治理可视化) **混合用**。

**本项目决策**：v1 硬编码 `StateGraph`（Python class）完全合理 — 流程模板就 1 个（standard_offboarding），改流程 = 改代码，重新部署。这是 Temporal 流派的主流做法。v3 才考虑接入 agent-builder。

**演示卖点**：硬编码不是缺点，是"反过度设计"的克制。讲清楚 "v1 用 code-first 是因为流程模板只有 1 个，没有可视化编排的 ROI；v3 待业务方真要自定义时再上 visual editor" 比"做一半的可视化编辑器"更专业。

[Sources: [LangGraph vs Temporal 2026](https://agentmarketcap.ai/blog/2026/04/08/langgraph-vs-temporal-long-running-agent-workflows-2026), [Workflow Definition: Argo vs Airflow](https://medium.com/@karthik.kvssk/workflow-definition-flexibility-argo-workflows-vs-airflow-5e035990d0e3)]

### Q9: SSO / 单点登录在演示项目中的取舍？

**答**：**演示阶段不做 SSO，用邮件深链一键登录等价替代**。
- SSO 真实需求 = "不输账号密码就能进系统"
- 邮件深链 + JWT + jti 一次性消费 = passwordless login，**功能上等价于 SSO**，且：
  - 不绑定特定 IdP（Mattermost OAuth / Keycloak / 企业 AD）
  - 部署只需一份 .env，演示开箱即用
  - 安全模型清晰（jti 一次性 + role 三元组绑定 + 24h 兜底过期）

**v1 决策**：邮件深链一键登录（DF-03）+ 在 PRD 里明确"SSO 留生产化阶段"

**亮点角度**：很多 demo 项目要么完全不做登录（裸奔），要么直接上 Keycloak（杀鸡用牛刀）。本项目"按演示场景选 magic link，留 SSO 给生产" 是有判断力的取舍。**Magic link 也是 Clerk / FusionAuth / Slack 推荐的现代 passwordless 方案**，不 cheap。

[Sources: [Magic Links Security Deep Dive](https://securityboulevard.com/2026/05/are-magic-links-secure-a-technical-deep-dive-into-email-based-authentication/), [Clerk Magic Links](https://clerk.com/blog/magic-links)]

---

## 5. Feature Dependencies

```
TS-01 状态机引擎 + 持久化
  ├── TS-02 人工任务中断/恢复
  │     └── DF-03 JWT 一键登录 (依赖 human task interrupt)
  │           └── DF-02 申请人最终确认 (依赖 magic link 给申请人发回执)
  ├── TS-04 DAG + 分支
  │     └── TS-12 退回路径配置 (依赖条件边)
  │           └── TS-03 三态决策 (依赖退回)
  └── TS-09 崩溃恢复
        └── DF-01 双层状态分离 (业务表是崩溃后重建权威)

TS-07 审计日志
  └── DF-07 节点结果累积 (action_logs + node_results 是同一份)
        └── DF-02 申请人确认时间线 (依赖结果累积)
              └── DF-08 LLM 摘要 (依赖节点结果作为 input)

NOTI-01 邮件通知
  ├── DF-05 双通道并行 (与 NOTI-02 同源)
  ├── DF-06 演示模式收件箱 (邮件网关层覆写)
  └── DF-09 超时扫描重发 (依赖通知 outbox + 状态机能查 waiting)

NOT-01 差异化表单  ⊥  DF-04 通用节点 (互斥，选了一个就放弃另一个)
NOT-07 SSO        ⊥  DF-03 magic link (功能重叠，演示阶段二选一)
NOT-11 可视化状态机图  ⊥  WEB-04 时间线表格 (展示同样信息，选轻量方案)
```

### 关键依赖说明

- **DF-02 申请人确认依赖 DF-07 节点结果累积**：没有 `context.node_results[]` 就无法聚合渲染汇总邮件
- **DF-01 双层状态分离是 v1 必选**：所有 UI / 申请人确认 / HR Dashboard 都读业务表，不读 LangGraph checkpoint
- **NOT-01 vs DF-04 是互斥设计选择**：v1 选 DF-04（通用表单），v2 才考虑 NOT-01（差异化）
- **NOT-07 SSO vs DF-03 magic link**：演示阶段 magic link 已等价 SSO，二者功能重叠

---

## 6. MVP Definition（与 PRD v0.3 active list 对齐）

### v1（演示版，3 周交付）

**MUST（不做就不像产品）**：
- ✅ FLOW-01/02/03/04/05/06 — 状态机 + 双写业务表 + 崩溃恢复 + 三态决策 + 退回路径 + 申请人确认 (覆盖 TS-01/04/07/12, DF-02/07)
- ✅ AUTH-01/02/03/04 — JWT 深链 + 一键登录 + jti 一次性 + role 绑定 (覆盖 TS-02, DF-03)
- ✅ NOTI-01/02/03/04/05 — 邮件 + Mattermost + 演示模式 + 通知 outbox + 超时扫描 (覆盖 TS-05/06, DF-05/06/09)
- ✅ WEB-01/02/03/04/05 — 静态前端 + 一键登录 + 通用表单 + 确认页时间线 + HR Dashboard (覆盖 TS-08/10, DF-04)
- ✅ SEED-01/02/03 — Mattermost team/user + custom attr + 演示触发器
- ✅ DEPLOY-01/02/03/04 — Docker Compose + nginx + 一键部署 + .env.example

**SHOULD（强差异化 / 面试亮点）**：
- ✅ LLM-01/02/03 — GLM 摘要 + 失败降级 (DF-08，3 个亮点之一)

**v1 范围质量门**：
- [x] table stakes 12/12 覆盖
- [x] differentiators 10/10 全部规划，3 个标 ★★★★★ 的亮点都在 v1
- [x] anti-features 17/17 都明确不做或留 v2/v3

### v2（生产化预备，假设 6-8 周）

**触发条件**：演示得到正向反馈，决定走真实业务

- 与外部业务系统真实 API 集成（资产 / AD / 财务，对应 NOT-02）
- 每节点差异化表单 / 字段（对应 NOT-01）
- 多种离职流程模板（主动 / 被动 / 协议，对应 NOT-04）
- 节点附件上传（对应 NOT-05）
- 节点二级子流程（执行 + 审核，对应 NOT-06）
- SSO 集成（OIDC / SAML，对应 NOT-07）
- 企业微信 / 飞书适配器（对应 NOT-08）
- Mattermost IM 内直接点按钮决策（升级 DF-05）
- 节点级 SLA 配置 + 多级升级（升级 DF-09）
- BI 报表（流程耗时 / SLA 达标率，对应 NOT-16）

### v3（agent-builder 阶段，理论上限）

- 流程模板可视化编排（对应 NOT-03）
- 自动节点 / agent node（真实执行外部 API，对应 NOT-17）
- AI 卡点诊断（预测哪些任务会 miss SLA）
- 多租户 / SaaS 化（对应 NOT-13）

---

## 7. Feature Prioritization Matrix（v1 范围）

| Feature ID | User Value | Implementation Cost | Priority | Why |
|---|---|---|---|---|
| FLOW-01/02/03 状态机三件套 | HIGH | MED | **P1** | 平台基座，没有就什么都跑不起来 |
| FLOW-04 三态决策 | HIGH | LOW | **P1** | 节点契约的核心 |
| FLOW-05 退回路径 | HIGH | LOW | **P1** | 演示完整性需要 |
| FLOW-06 申请人确认 | HIGH | MED | **P1** | DF-02 头号亮点 |
| AUTH-01/02/03/04 | HIGH | MED | **P1** | 没登录就没法演示 |
| NOTI-01 邮件 | HIGH | LOW | **P1** | 唯一确定可达的通道 |
| NOTI-02 Mattermost | MED | LOW | **P1** | 双通道亮点 |
| NOTI-03 演示模式 | HIGH | LOW | **P1** | 一人演 8 角色的关键 |
| NOTI-04 通知 outbox | MED | LOW | **P1** | 审计需要 |
| NOTI-05 超时扫描 | LOW | LOW | **P2** | nice-to-have，可作为后期 polish |
| LLM-01/02/03 GLM 摘要 | MED | LOW | **P1** | DF-08 亮点，且失败降级低风险 |
| SEED-01/02/03 | HIGH | LOW | **P1** | 演示前置 |
| WEB-01/02/03/04/05 | HIGH | MED | **P1** | 没 UI 就没法演 |
| DEPLOY-01/02/03/04 | HIGH | LOW | **P1** | 一键部署是演示前提 |

**P1 = 必须有；P2 = 应该有，能上就上；P3 = nice-to-have**

v1 PRD active list 没有 P3 项 — 范围控制良好。

---

## 8. Competitor Feature Analysis（流程引擎 vs 业务系统）

| Feature | Camunda 8 (流程引擎) | Temporal (durable execution) | ServiceNow HR (业务系统) | 北森 (HR SaaS) | **本项目方案** |
|---|---|---|---|---|---|
| 状态机定义 | BPMN XML（可视化） | code-first（Python/Go/TS SDK） | 内置流程模板 + 自定义 | 内置 + 可视化 | **code-first Python (LangGraph StateGraph)** |
| 三态决策 | Gateway + 多 outcome（需建模） | activity return value | 内置 approve/reject/return | 内置三态 | **统一节点契约（FLOW-04）** |
| 人工任务 | Tasklist UI | SDK + 自建 UI | 内置 Employee Center | 内置 ESS | **自建 UI（Next.js 多角色页面）** |
| 通知通道 | 插件式 | 自建 | 内置 email/SMS/Push | 内置 email + 钉钉/飞书 | **email (QQ SMTP) + Mattermost 双通道** |
| 崩溃恢复 | Zeebe broker | 引擎核心能力（event sourcing） | 平台保证 | 平台保证 | **PostgresSaver checkpoint** |
| 审计日志 | History event log | event history | 完整审计模块 | 完整审计 | **action_logs + notifications 表** |
| 一键登录 | SSO (Keycloak) | 自建 | 内置 SSO | 内置 SSO | **magic link JWT** |
| 业务字段 | ❌ 不管 | ❌ 不管 | ✅ 千百个字段 | ✅ 完整 HCM | **❌ 通用文本（与 Camunda/Temporal 同路线）** |
| BI 报表 | Optimize 模块 | 接外部 BI | 内置 dashboard | 内置 | **❌ v1 不做** |
| 可视化编排 | Camunda Modeler | ❌（code-first） | 内置 | 内置 | **❌ v1 不做（与 Temporal 同路线）** |
| 申请人闭环 | 需自建 | 需自建 | 内置 onboarding/offboarding 模板 | 内置 | **✅ 显式 final_confirm 节点（亮点）** |

**关键定位**：本项目在能力光谱上**靠近 Camunda/Temporal**（流程引擎流派），远离 ServiceNow HR / 北森（业务系统流派）。这与 PRD §1.2 "构建一个有状态有角色有交接的流程引擎" 完全一致。

---

## 9. 给 Roadmap 的建议

基于 features 分类，建议 phase 拆分（如果用 GSD 规划）：

| Phase | 包含 features | Rationale |
|---|---|---|
| **Phase 1: 流程引擎骨架** | FLOW-01/02/03, DEPLOY-01/02/03/04 | 先把 LangGraph + Postgres + docker compose up 跑通 |
| **Phase 2: 三态决策 + 节点契约** | FLOW-04/05, AUTH-01/02/03/04 | 通用节点表单契约 + 一键登录链路 |
| **Phase 3: 通知双通道** | NOTI-01/02/03/04, SEED-01/02/03 | 邮件 + Mattermost + 演示模式 + 测试组织数据 |
| **Phase 4: 申请人闭环** | FLOW-06, WEB-04 | 申请人确认节点 + 时间线 UI（DF-02 亮点） |
| **Phase 5: 前端整体 + LLM 摘要** | WEB-01/02/03/05, LLM-01/02/03 | 通用表单 + HR Dashboard + GLM 摘要 |
| **Phase 6: SLA + 演示打磨** | NOTI-05, 端到端 demo 脚本 | 超时扫描 + 演示讲稿 + 录屏 |

**phase 1 → 6 的依赖链**：状态机 → 三态决策 → 通知 → 申请人闭环 → 前端 → 打磨。每个 phase 都能独立 demo 一个 milestone，不会出现 "做了一半都没法跑" 的窘境。

---

## 10. Sources

### Workflow Engine 流派
- [LangGraph vs Temporal 2026 Decision Guide](https://agentmarketcap.ai/blog/2026/04/08/langgraph-vs-temporal-long-running-agent-workflows-2026) — code-first vs durable execution 取舍
- [Camunda 8 Parallel Gateway Docs](https://docs.camunda.io/docs/components/modeler/bpmn/parallel-gateways/) — fan-out/fan-in 标准
- [Temporal vs Airflow vs Argo](https://www.xgrid.co/resources/temporal-vs-airflow-vs-argo-workflow-orchestration/) — 主流引擎对比
- [What Is a Workflow Engine 2026](https://automationatlas.io/answers/what-is-workflow-engine/) — 流程引擎定义
- [BPM Decoupling 2026](https://kissflow.com/workflow/bpm/decoupling-process-logic-from-tools-with-bpm/) — 流程平台 vs 业务工具边界

### HR Offboarding 业务系统流派
- [ServiceNow + Workday Integration](https://www.dotsquares.com/press-and-events/tech/servicenow-hr-onboarding-offboarding-case-study) — 业务系统能力参考
- [Oyster HR - Offboarding Glossary](https://www.oysterhr.com/glossary/offboarding) — 行业术语
- [HRCloud - Offboarding Best Practices](https://www.hrcloud.com/blog/best-practices-for-employee-offboarding-process) — 申请人确认环节实践
- [Stonebranch - Hire-to-Retire Lifecycle](https://www.stonebranch.com/blog/employee-onboarding-and-offboarding-workflow-pattern-orchestrating-the-hire-to-retire-lifecycle) — 完整生命周期流程

### 三态决策与审批模式
- [Cflow - HR Approval Workflow Patterns](https://www.cflowapps.com/approval-workflow-design-patterns/) — return/reject 模式
- [Oracle PeopleSoft - Rework Button](https://docs.oracle.com/cd/E28727_01/hcm91fp2/eng/psbooks/hepf/htm/hepf12.htm) — 西方"退回"实现
- [Camunda BPMN User Task Quickstart](https://docs.camunda.org/get-started/quick-start/user-task/) — BPMN 二态默认

### SLA / 升级 / 卡点
- [Cflow - Escalation Rules](https://www.cflowapps.com/how-automated-escalation-rules-reduce-approval-bottlenecks/) — 自动升级
- [Predictive Task Routing](https://www.mymobilelyfe.com/artificial-intelligence/predictive-task-routing-stop-slas-from-sneaking-up-on-your-team/) — AI 预测 SLA miss
- [Cflow - Process Bottlenecks](https://www.cflowapps.com/process-bottlenecks/) — 卡点检测方法

### 审计与合规
- [SOC2 + GDPR HR Survival Guide](https://hireroad.com/resources/soc-2-without-the-headache-hrs-step-by-step-survival-guide) — HR 数据合规
- [Sonar - Audit Logging Best Practices](https://www.sonarsource.com/resources/library/audit-logging/) — immutable audit
- [GDPR to SOC2 Practical Guide](https://medium.com/@aleyacyrus/from-gdpr-to-soc-2-a-practical-guide-to-building-compliance-into-your-software-7416422ba374) — 两套规范交集

### Magic Link / Passwordless
- [Magic Links Security Deep Dive (May 2026)](https://securityboulevard.com/2026/05/are-magic-links-secure-a-technical-deep-dive-into-email-based-authentication/) — jti 一次性、SHA-256 hash 存储
- [Clerk - Magic Links Guide](https://clerk.com/blog/magic-links) — 实现参考
- [FusionAuth Passwordless](https://fusionauth.io/docs/v1/tech/passwordless/magic-links) — 企业级实现

### IM 通道
- [Mattermost Interactive Messages](https://developers.mattermost.com/integrate/plugins/interactive-messages/) — button → webhook
- [Slack Approval Workflows Blueprint](https://api.slack.com/best-practices/blueprints/approval-workflows) — 同模式参考

### 中国 HR SaaS
- [北森 HR SaaS 综合介绍](https://www.beisen.com/product/hrsaas/) — 综合 HCM 能力
- [HR SaaS 中国市场综述](https://www.jiemian.com/article/7899188.html) — 国内市场结构

---

*Feature research for: AI 驱动的离职流程执行系统（state-machine workflow engine 流派）*
*Researched: 2026-05-16*
*Confidence: MEDIUM-HIGH — 国际流程引擎 + 西方 HR offboarding 行业模式 HIGH；中国 HR SaaS 细分功能 LOW（结论不影响本项目方向）*
