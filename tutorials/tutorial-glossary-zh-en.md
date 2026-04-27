# perilla 中英术语对照（安全与治理）

统一代码评审、故障沟通、CI 与文档中的用语，减少歧义。

---

## 导航

- 通用版（当前）：`tutorial-glossary-zh-en.md`
- 产品版：`tutorial-glossary-product.md`
- 工程版：`tutorial-glossary-engineering.md`

快速跳转：

- [1. 核心平台术语](#1-核心平台术语)
- [2. 安全与权限术语](#2-安全与权限术语)
- [3. Web 安全术语](#3-web-安全术语本次改造重点)
- [4. 可观测性与回归术语](#4-可观测性与回归术语)
- [5. CI/CD 与报告术语](#5-cicd-与报告术语)
- [7. 新人最容易混淆的三组词](#7-新人最容易混淆的三组词)

---

## 1. 核心平台术语

| 中文 | English | 备注 |
|---|---|---|
| 推理网关 | Inference Gateway | 指后端统一入口（FastAPI） |
| 控制台 | Console | 指前端管理界面 |
| 能力模块 | Capability Module | 包含 Agent/Tool/Skill/Workflow |
| 工作流 | Workflow | 可编排执行单元 |
| 执行实例 | Execution | 某次 workflow run |
| 运行时 | Runtime | 模型或引擎运行环境 |
| 配置项 | Configuration | `.env` 或系统设置 |

---

## 2. 安全与权限术语

| 中文 | English | 备注 |
|---|---|---|
| 访问控制 | Access Control | 权限治理总称 |
| 角色 | Role | admin / operator / viewer |
| 基于角色访问控制 | RBAC | Role-Based Access Control |
| 权限范围 | Scope | 例如 `audit:read`, `workflow:write` |
| API Key | API Key | 调用身份凭证 |
| 租户 | Tenant | 多租户隔离主体 |
| 租户绑定 | Tenant Binding | API Key 可访问 tenant 列表 |
| 租户强制 | Tenant Enforcement | 缺省租户/跨租户拦截策略 |
| 命名空间 | Namespace | workflow 归属域，通常需与 tenant 对齐 |

---

## 3. Web 安全术语（本次改造重点）

| 中文 | English | 备注 |
|---|---|---|
| 跨站脚本攻击 | XSS | Cross-Site Scripting |
| 内容净化 | Sanitization | 通过白名单过滤危险标签/属性 |
| 原生 HTML 渲染 | Raw HTML Rendering | markdown 中 `html: true/false` 的关键风险点 |
| 跨站请求伪造 | CSRF | Cross-Site Request Forgery |
| 双提交 Cookie | Double-Submit Cookie | CSRF 常见防护模式 |
| 安全方法 | Safe Methods | GET/HEAD/OPTIONS/TRACE |
| 写请求 | Mutating Request | POST/PUT/PATCH/DELETE |
| 令牌 | Token | 这里指 CSRF token |

---

## 4. 可观测性与回归术语

| 中文 | English | 备注 |
|---|---|---|
| 请求 ID | Request ID | `X-Request-Id` |
| 链路追踪 ID | Trace ID | `X-Trace-Id` |
| 响应耗时 | Response Time | `X-Response-Time-Ms` |
| 审计日志 | Audit Log | 行为留痕 |
| 限流 | Rate Limit | 防滥用与保护系统 |
| 回归测试 | Regression Test | 防止旧功能被新改动破坏 |
| 租户安全回归 | Tenant Security Regression | 专注租户隔离 |
| 安全回归 | Security Regression | RBAC/Audit/Trace/CSRF/XSS |

---

## 5. CI/CD 与报告术语

| 中文 | English | 备注 |
|---|---|---|
| 工作流 | Workflow | GitHub Actions workflow |
| 手动触发 | Workflow Dispatch | 可带输入参数 |
| 路径过滤 | Path Filter | 控制何时触发 CI |
| 步骤摘要 | Step Summary | `$GITHUB_STEP_SUMMARY` |
| 构件 | Artifact | CI 产物下载 |
| 失败快速退出 | Fail Fast | 输入非法时立即失败 |
| 慢批次告警 | Slow Batch Warning | 超过阈值标记 `⚠️` |
| 阈值 | Threshold | 如 `slow_threshold_seconds` |

---

## 6. 推荐表达模板（沟通更清晰）

- 中文：`这个 403 是 CSRF token mismatch，不是 RBAC 拒绝。`  
  English: `This 403 is caused by CSRF token mismatch, not RBAC denial.`

- 中文：`该 workflow 返回 404 是租户隔离策略，避免泄露资源存在性。`  
  English: `This workflow 404 is from tenant isolation policy to avoid resource existence leakage.`

- 中文：`PR 安全回归出现慢批次告警，但功能回归通过。`  
  English: `Security regression on PR reports slow-batch warning, while functional checks still pass.`

---

## 7. 新人最容易混淆的三组词

1. **Authentication vs Authorization**  
   - Authentication：你是谁（例如 API Key 身份）  
   - Authorization：你能做什么（例如 RBAC + scope）

2. **Tenant vs Namespace**  
   - Tenant：租户身份边界  
   - Namespace：资源逻辑归属（在本项目中通常要求与 tenant 对齐）

3. **XSS vs CSRF**  
   - XSS：恶意脚本在页面执行  
   - CSRF：借用你的登录态伪造写请求

---

## 8. 使用建议

- PR 描述中建议同时写中英关键词，便于跨团队检索。  
- 故障单中优先固定以下字段：`role`、`tenant_id`、`request_id`、`trace_id`、`status_code`。  
- CI 失败时先看 Step Summary，再下载 artifact 细查。

---

## 9. 继续阅读

- 面向非技术同学：`tutorial-glossary-product.md`
- 面向研发/测试/运维：`tutorial-glossary-engineering.md`
