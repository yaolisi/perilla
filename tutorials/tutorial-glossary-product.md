# OpenVitamin Enhanced 产品术语表（面向非技术同学）

> 适用角色：产品经理、项目经理、运营、客户成功、业务分析。  
> 目标：用“业务可理解语言”快速对齐项目中常见词汇。

---

## 导航

- 产品版（当前）：`tutorial-glossary-product.md`
- 通用中英版：`tutorial-glossary-zh-en.md`
- 工程版：`tutorial-glossary-engineering.md`

快速跳转：

- [1. 产品与平台](#1-产品与平台)
- [2. 权限与多租户](#2-权限与多租户)
- [3. 安全相关（产品必须知道）](#3-安全相关产品必须知道)
- [4. CI 与上线](#4-ci-与上线)
- [5. 常见状态码（产品沟通版）](#5-常见状态码产品沟通版)

---

## 1. 产品与平台

| 术语 | 英文 | 一句话解释 |
|---|---|---|
| 平台 | Platform | OpenVitamin 的整体系统，不是单一聊天工具 |
| 控制台 | Console | 用户操作界面（前端） |
| 推理网关 | Inference Gateway | 后端统一入口，负责调度和治理 |
| 能力模块 | Capability Module | 平台可插拔能力，例如 Workflow、Agent、Tool |
| 工作流 | Workflow | 可复用、可编排的一组执行步骤 |
| 执行实例 | Execution | 工作流的一次具体运行记录 |

---

## 2. 权限与多租户

| 术语 | 英文 | 一句话解释 |
|---|---|---|
| 租户 | Tenant | 客户或业务隔离单元 |
| 命名空间 | Namespace | 资源归属标识，通常与租户对应 |
| 角色 | Role | 用户在平台中的权限档位 |
| 管理员 | Admin | 最高权限角色 |
| 操作员 | Operator | 日常操作角色，权限低于管理员 |
| 观察者 | Viewer | 只读角色，不能执行写操作 |

---

## 3. 安全相关（产品必须知道）

| 术语 | 英文 | 一句话解释 |
|---|---|---|
| XSS | Cross-Site Scripting | 页面被注入恶意脚本的风险 |
| CSRF | Cross-Site Request Forgery | 用户在不知情下被诱导发起写请求 |
| 审计日志 | Audit Log | 关键操作留痕记录 |
| 请求追踪 | Request Trace | 请求全链路标识，便于排障 |
| 限流 | Rate Limit | 防止高频请求压垮系统 |

---

## 4. CI 与上线

| 术语 | 英文 | 一句话解释 |
|---|---|---|
| 回归测试 | Regression Test | 确认新改动没有破坏旧能力 |
| 安全回归 | Security Regression | 专门验证权限与安全链路 |
| 工作流（CI） | Workflow | GitHub Actions 自动化任务 |
| Step Summary | Step Summary | CI 页面直接可读的结果摘要 |
| Artifact | Artifact | 可下载测试报告产物 |

---

## 5. 常见状态码（产品沟通版）

| 状态码 | 含义 | 常见原因 |
|---|---|---|
| 200 | 成功 | 请求通过 |
| 403 | 禁止访问 | 权限不足 / CSRF 校验失败 |
| 404 | 未找到 | 资源不存在或租户隔离策略隐藏资源 |
| 429 | 请求过多 | 命中限流 |
| 500 | 服务错误 | 后端异常，需要研发排查 |

---

## 6. 产品沟通建议话术

- “这个 403 是权限策略生效，不是系统宕机。”  
- “这个 404 可能是租户隔离，不一定是真的没有数据。”  
- “CI 红灯先看 Step Summary，再看 artifact 细节。”

---

## 7. 继续阅读

- 术语全景图：`tutorial-glossary-zh-en.md`
- 工程实现语义：`tutorial-glossary-engineering.md`
