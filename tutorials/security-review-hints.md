# perilla：安全与逻辑审查提示（归档）

**静态架构与关键点代码审查**结论摘要，与 [tutorial-security-baseline.md](tutorial-security-baseline.md) 中的 MUST 基线互补；**不能替代**渗透测试或线上专项测试。

---

## 1. 威胁模型（必读）

本平台默认面向 **本地优先 / 内网可信** 场景（单用户或团队私有部署）。  
一旦服务暴露到 **公网** 或 **多团队共享主机**，必须在配置与权限模型上显式收紧，否则「开发友好默认值」会与「强隔离预期」冲突。

---

## 2. 高优先级提示

### 2.1 RBAC 与「无 API Key」行为

- 启用 RBAC 时，若请求 **未携带** `X-Api-Key`，角色会回落到 **`rbac_default_role`（默认为 `operator`）**。  
- **含义**：仅靠「不配 Key」通常**不会**自动变成只读；若期望匿名或普通客户端仅为浏览能力，应在生产将 **`RBAC_DEFAULT_ROLE=viewer`**（或等价配置），并通过 Key 授予管理员/操作员权限。  
- **逻辑相关性**：与「单机省事」一致，与「互联网暴露默认安全」不一致——属于威胁模型不匹配，需配置纠正。

### 2.2 `RBAC_ENABLED=false`（常见于调试）

- 关闭 RBAC 时，中间件会将平台角色视为 **Operator**，控制面写能力边界依赖其它机制（若未配合将过宽）。  
- 生产必须通过 `DEBUG=false` 触发的自动收敛（见主教程「生产安全护栏」）并保持 RBAC 打开。

### 2.3 高危默认与生产护栏（`DEBUG=false`）

默认配置偏开发体验，例如：

- `file_read_allowed_roots` 等路径类配置需收敛；**生产**下对 `"/"`、空 CORS、HTTP 工具无 host 等组合有 **Fail-Fast 阻断**（见 `tutorial-security-baseline.md`）。  
- 若在生产使用 `SECURITY_GUARDRAILS_STRICT=false` 或保持 `DEBUG=true`，护栏与自动收敛可能**不生效或减弱**，高危默认值会回流。

### 2.4 控制面接口一致性（示例）

- **`GET /api/system/browse-directory`**：在服务端触发目录选择相关逻辑；应与「系统敏感操作需管理员」策略一致审视暴露范围（本地单机与共享主机风险不同）。  
- 建议在架构评审中将其视为 **调试/运维能力**，限定访问面（网络 ACL、仅本机、或管理员角色）。

---

## 3. 中优先级提示

### 3.1 多租户与 `X-Tenant-Id`

- 租户标识由请求头注入；**真正隔离**依赖租户强制、API Key–租户绑定及存储/查询层的 **tenant 过滤**。  
- Workflow 等路径已显式做了 namespace/tenant 对齐；其它数据面需按模块继续防 **跨租户 IDOR**（定期做面向接口的鉴权审查）。

### 3.2 CSRF 与「非浏览器客户端」

- CSRF 双提交主要保护 **浏览器 + Cookie** 场景。脚本、服务间调用若不使用同源 Cookie 链路，行为与浏览器不一致——应在集成文档中写清调用约定（密钥、路径、是否禁用 CSRF 的开发期配置等）。

### 3.3 前端身份头（如 `X-User-Id`）

- 来自浏览器存储的头**可被篡改**；后端应仅将其作**展示/归因**辅助，**不得**作为唯一授权依据；鉴权应以 **API Key / RBAC / 会话策略**为准。

### 3.4 动态 SQL 与表名

- 向量检索等路径若拼接表名，需确保表名来源**不可被用户控制**；新增功能时避免将外部输入拼入 SQL 标识符。

---

## 4. 已对齐的对抗能力（摘要）

- 生产 **Fail-Fast** 护栏与 **strict** 开关（见 `tutorial-security-baseline.md`）。  
- **RBAC / Tenant / Scope / 审计 / 限流 / Trace / CSRF（后端）与 XSS 基线（前端）** 分层共存。  
- CSRF token 比较使用 **timing-safe** 比较。

---

## 5. 建议动作（落地优先级）

1. **公网或共享运行时**：强制 `RBAC_ENABLED=true`，将 **`rbac_default_role` 设为 `viewer`**，仅向运维发放 admin/operator Key；复核 `system`、备份、模型、workflow 等写路径。  
2. **重新审视** 调试类系统接口的暴露范围与角色要求。  
3. **部署清单**：核对 `DEBUG`、`CORS_ALLOWED_ORIGINS`、`FILE_READ_ALLOWED_ROOTS`、`TOOL_NET_*`、`CSRF_COOKIE_SECURE`（HTTPS）。  
4. **后端**：梳理依赖 `X-User-Id` 的路由，确认不参与鉴权决策。

---

## 6. 相关文档

> Standalone 包内：下列教程与本文件位于同一目录（`tutorials/`），下列链接为同目录引用。

- [tutorial-security-baseline.md](tutorial-security-baseline.md) — MUST 基线与阻断规则  
- [tutorial-ops-checklist.md](tutorial-ops-checklist.md) — 发版前短清单  
- [tutorial-index.md](tutorial-index.md) — 教程总入口  
- [README.md](../README.md) — 项目说明（含摘要链接）
