# Mattermost 测试账号映射表

> 实例：`http://192.168.2.44:8065`
> Seed 完成时间：2026-05-16
> 一致来源：本文档 / `seed-mattermost.sh` / PRD §9.1.2

## Bot 账号（AI Agent 用）

| 字段           | 值                                                  |
| -------------- | --------------------------------------------------- |
| Username       | `offboarding-bot`                                   |
| Display Name   | 离职流程 Bot                                         |
| User ID        | `mte711kt9pf4zj7dtwib3pa3yr`                        |
| Owner          | `admin`                                             |
| Team           | `laios`                                             |
| PAT (敏感)     | 见 `hr/.env` 中 `MATTERMOST_BOT_TOKEN`（不在此文档明文）|
| 用途           | LangGraph Agent 调用 Mattermost REST API 发通知 / 卡片消息 |

> **使用示例**：
> ```bash
> curl -H "Authorization: Bearer $MATTERMOST_BOT_TOKEN" \
>      http://192.168.2.44:8065/api/v4/users/me
> ```
> 返回 `offboarding-bot` 用户信息即表示 token 有效。

## 账号一览（9 个，含 admin）

| # | Username     | 姓名         | 角色          | 部门 Team       | Mattermost Email                | **实际收件箱**          | 登录密码        |
|---|--------------|--------------|---------------|-----------------|---------------------------------|-------------------------|-----------------|
| 0 | `admin`      | —            | 系统管理员    | laios           | `jingzhi.lu+admin@wayz.ai`      | jingzhi.lu@wayz.ai      | `laios1855`   |
| 1 | `zhang.san`  | 张三         | 离职员工 ⭐   | engineering     | `1624456575+zhang.san@qq.com`   | 1624456575@qq.com       | `laios1855`    |
| 2 | `li.si`      | 李四         | 直属上级 ⭐   | engineering     | `1624456575+li.si@qq.com`       | 1624456575@qq.com       | `laios1855`    |
| 3 | `wang.wu`    | 王五         | 研发总监      | engineering     | `1691517500+wang.wu@qq.com`     | 1691517500@qq.com       | `laios1855`    |
| 4 | `hr.alice`   | Alice        | HR 专员       | hr              | `1691517500+hr.alice@qq.com`    | 1691517500@qq.com       | `laios1855`    |
| 5 | `hr.bob`     | Bob          | HR 总监 ⭐    | hr              | `1624456575+hr.bob@qq.com`      | 1624456575@qq.com       | `laios1855`    |
| 6 | `it.charlie` | Charlie      | IT 设备管理员 | it              | `1691517500+it.charlie@qq.com`  | 1691517500@qq.com       | `laios1855`    |
| 7 | `fin.david`  | David        | 财务结算专员  | finance         | `jingzhi.lu+fin.david@wayz.ai`  | jingzhi.lu@wayz.ai      | `laios1855`    |
| 8 | `legal.eve`  | Eve          | 法务合规      | legal           | `jingzhi.lu+legal.eve@wayz.ai`  | jingzhi.lu@wayz.ai      | `laios1855`    |

⭐ 主流程关键链路角色（离职员工 → 上级 → HR 终审）

## 按收件箱反查（演示者视角）

### 📥 `1624456575@qq.com`（QQ 主邮箱 — 主流程）

| Username    | 角色      | 何时会收到邮件 |
| ----------- | --------- | -------------- |
| `zhang.san` | 离职员工  | 提交申请后、被退回时、流程完成时 |
| `li.si`     | 直属上级  | 离职申请待审批 |
| `hr.bob`    | HR 总监   | HR 终审待处理 |

### 📥 `1691517500@qq.com`（QQ 二邮箱 — 部门管理）

| Username     | 角色          | 何时会收到邮件 |
| ------------ | ------------- | -------------- |
| `wang.wu`    | 研发总监      | 上级再上一级审核（如有） |
| `hr.alice`   | HR 专员       | HR 初审待处理 |
| `it.charlie` | IT 设备管理员 | 设备归还待处理 |

### 📥 `jingzhi.lu@wayz.ai`（Wayz 工作邮箱 — 后置 + 系统）

| Username     | 角色          | 何时会收到邮件 |
| ------------ | ------------- | -------------- |
| `admin`      | 系统管理员    | Mattermost 系统通知、密码重置 |
| `fin.david`  | 财务结算专员  | 财务结算待处理（含设备赔偿、折旧购买） |
| `legal.eve`  | 法务合规      | 保密 / 竞业协议签字待处理 |

## 按部门 Team 反查

| Team Name      | Display Name   | 成员                                    |
| -------------- | -------------- | --------------------------------------- |
| `laios`        | Laios 演示团队 | **所有 9 个账号**（admin + 8 测试）      |
| `engineering`  | 研发部         | zhang.san, li.si, wang.wu               |
| `hr`           | 人力资源部     | hr.alice, hr.bob                        |
| `it`           | IT 运维部      | it.charlie                              |
| `finance`      | 财务部         | fin.david                               |
| `legal`        | 法务部         | legal.eve                               |

## 上下级关系（流程内部用）

```
wang.wu (总监)
  ↑
li.si (上级)
  ↑
zhang.san (离职员工)

hr.bob (HR 总监)
  ↑
hr.alice (HR 专员)
```

`it.charlie` / `fin.david` / `legal.eve` 在演示流程里独立履职，不显式建立上下级。

## 登录方式

**Mattermost Web UI**：`http://192.168.2.44:8065`

可以用以下任一方式登录：

| 字段 | 输入 |
| --- | --- |
| Username 登录 | `zhang.san` + 密码 `laios1855` |
| Email 登录    | `1624456575+zhang.san@qq.com` + 密码 `laios1855` |

> 因为邮箱是 `+alias` 形式，建议演示时**统一用 username 登录**，避免在登录框敲长字符串。

## 切回生产模式（v1 → v2 升级时）

1. 把每个测试账号的 email 字段替换为真员工邮箱
2. 删除 `+alias` 形式的别名映射
3. 删除 `admin` 测试账号或保留作系统管理员
4. 业务代码 0 修改（账号 username / employee_id 不变）

## 重建 / 重置账号

如需重置所有测试数据：

```bash
# 在 192.168.2.44 上
cat /Users/admin/ai/resume/interview/liuxin/hr/deploy/mattermost/seed-mattermost.sh \
  | ssh GigaByte@192.168.2.44 'wsl -d Ubuntu -e bash -s'
```

脚本幂等：已存在的账号 / Team 会被跳过，但 email 字段会被强制更新到新方案。
