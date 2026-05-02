# perilla 工程术语表（研发 / 测试 / 运维）

统一实现、排障与 CI 场景下的用语，便于跨角色沟通。

---

## 导航

- 工程版（当前）：`tutorial-glossary-engineering.md`
- 通用中英版：`tutorial-glossary-zh-en.md`
- 产品版：`tutorial-glossary-product.md`

快速跳转：

- [1. 身份、权限、隔离](#1-身份权限隔离)
- [2. Web 安全](#2-web-安全)
- [3. 可观测性与治理](#3-可观测性与治理)
- [4. CI/CD 与报告](#4-cicd-与报告)
- [5. 当前项目中的关键脚本映射](#5-当前项目中的关键脚本映射)
- [6. 高频误解与纠正](#6-高频误解与纠正)

---

## 1. 身份、权限、隔离

| 中文 | English | 工程语义 |
|---|---|---|
| 认证 | Authentication | “你是谁”，如 API Key 身份 |
| 鉴权 | Authorization | “你能做什么”，如 RBAC/scope |
| RBAC | Role-Based Access Control | 角色授权模型（admin/operator/viewer） |
| Scope | Scope | 细粒度能力权限，如 `workflow:write` |
| Tenant | Tenant | 隔离边界，跨租户访问应阻断 |
| Namespace | Namespace | 资源逻辑域，workflow 通常要求 namespace==tenant |
| Tenant Binding | Tenant Binding | API Key 可访问 tenant 映射 |
| 租户强制路径 | Tenant enforcement prefixes | `backend/middleware/tenant_paths.py` 中列出的 URL 前缀；命中则须显式租户头 |
| resolve_api_tenant_id | resolve_api_tenant_id | 仅用中间件注入的 `request.state.tenant_id`（及默认租户），不读头覆盖 state |
| get_effective_tenant_id | get_effective_tenant_id | state 未设置时可读 `TENANT_HEADER_NAME`，再回落默认租户 |

---

## 2. Web 安全

| 中文 | English | 工程语义 |
|---|---|---|
| XSS | Cross-Site Scripting | 前端渲染链路注入风险 |
| HTML 净化 | HTML Sanitization | DOMPurify 等白名单净化 |
| CSRF | Cross-Site Request Forgery | 跨站写请求伪造 |
| 双提交 Cookie | Double-Submit Cookie | Header token 必须与 cookie token 一致 |
| 安全方法 | Safe Methods | GET/HEAD/OPTIONS/TRACE（默认不要求 CSRF） |
| 写方法 | Mutating Methods | POST/PUT/PATCH/DELETE（要求 CSRF） |

---

## 3. 可观测性与治理

| 中文 | English | 工程语义 |
|---|---|---|
| Request ID | Request ID | 单请求标识（`X-Request-Id`） |
| Trace ID | Trace ID | 链路标识（`X-Trace-Id`） |
| 审计日志 | Audit Log | 关键控制面行为持久化留痕 |
| 限流 | Rate Limit | 保护服务容量、防止滥用 |
| 生产护栏 | Guardrails | 高危配置阻断启动 |
| Fail Fast | Fail Fast | 输入非法或配置违规时立即失败 |

---

## 4. CI/CD 与报告

| 中文 | English | 工程语义 |
|---|---|---|
| workflow_dispatch | Manual Trigger | 手动触发，可带参数 |
| Path Filter | Path Filter | 仅路径命中才触发 workflow |
| paths-ignore | Path Ignore | 文档改动不触发 |
| Step Summary | Step Summary | Actions 页面内联展示结果 |
| Artifact | Artifact | 测试报告下载产物 |
| 慢批次告警 | Slow Batch Warning | 超阈值标记 `⚠️` |
| Threshold | Threshold | `slow_threshold_seconds` |

---

## 5. 当前项目中的关键脚本映射

| 场景 | 脚本 | 说明 |
|---|---|---|
| tenant 隔离回归 | `backend/scripts/test_tenant_security_regression.sh` | 聚焦租户隔离路径 |
| 安全聚合回归 | `scripts/acceptance/run_security_regression.sh` | 聚合 RBAC/Audit/Trace/CSRF/XSS |
| RBAC 批次 | `scripts/acceptance/run_batch1_rbac.sh` | 角色相关 |
| Audit 批次 | `scripts/acceptance/run_batch2_audit.sh` | 审计相关 |
| Trace 批次 | `scripts/acceptance/run_batch3_trace.sh` | request/trace header 相关 |
| Web 安全批次 | `scripts/acceptance/run_batch5_web_security.sh` | CSRF + XSS 基线 |

---

## 6. 高频误解与纠正

1. “404 就是资源不存在”  
   - 纠正：在租户隔离场景中，404 也可能是防枚举策略。

2. “403 一定是 RBAC”  
   - 纠正：也可能是 scope 校验或 CSRF token 校验失败。

3. “XSS 只要前端转义就够了”  
   - 纠正：需多层防护（渲染策略 + 净化 + 组件级安全配置）。

4. “CI 只看红绿灯”  
   - 纠正：先看 Step Summary，再看 artifact/JUnit 明细。

---

## 7. 推荐日志字段（排障模板）

故障单建议固定记录：

- `request_id`
- `trace_id`
- `tenant_id`
- `api_key_scope`（如可取）
- `platform_role`
- `status_code`
- `path`
- `method`

这样跨团队交接时不需要反复补充上下文。

---

## 8. 继续阅读

- 术语全景图：`tutorial-glossary-zh-en.md`
- 面向产品/运营：`tutorial-glossary-product.md`
