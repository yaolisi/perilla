# perilla 调试手册（新手友好）

目标：遇到问题时，按“现象 -> 排查 -> 修复 -> 回归”的顺序快速定位。  
范围：本地开发、联调与发布后首轮排障。

---

## 1. 调试四步法

1. **确认范围**：单页面、单接口，还是全局异常  
2. **拿证据**：错误码、请求头、关键日志、复现步骤  
3. **做最小修复**：先恢复可用，再优化  
4. **补回归**：至少跑定向测试 + `make pr-check-fast`

---

## 2. 高频问题速查

## 2.1 `401/403`（鉴权或权限）

优先检查：

- `.env` 中 RBAC 与 API Key 设置
- 请求头 `X-Api-Key`、`X-Tenant-Id`
- CSRF 写请求是否带 `X-CSRF-Token` + cookie

复现验证：

```bash
curl -i -s -c /tmp/ov_cookie.txt http://127.0.0.1:8000/api/health | tee /tmp/ov_headers.txt
```

若返回 **400** 且文案含 **`tenant id required for protected path`**：说明路径落在租户强制前缀内（清单见 **`backend/middleware/tenant_paths.py`**），必须在请求中加 **`-H "X-Tenant-Id: <tenant>"`**，并与 API Key 的租户绑定一致；详解 **tutorial.md §10.4**。

---

## 2.2 `404`（资源查不到）

优先检查：

- 是否租户不一致（最常见）  
- 创建与查询是否走了相同 `X-Tenant-Id`  
- namespace 或 ID 是否拼错

---

## 2.3 `429`（限流）

优先检查：

- 是否短时间高频调用  
- 测试脚本是否并发过高  
- 限流配置是否过于收紧

处理建议：先降并发、延长重试间隔，再看是否要调整策略。

---

## 2.4 MCP 配置成功但 Agent 不可用

优先检查：

- MCP Server 是否启用  
- transport/base_url 是否可达  
- 后端协议与客户端生命周期是否正常

定向测试：

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_mcp_protocol.py \
  backend/tests/test_mcp_adapter.py \
  backend/tests/test_mcp_http_client_lifecycle.py
```

---

## 2.5 EventBus 合同校验失败

优先检查报错是否为数值字段类型问题。  
注意：当前规则下 `True/False` 不会被当作合法数值（bool 伪整型已收紧）。

定向回归：

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_event_bus_smoke_summary_contract.py \
  backend/tests/test_event_bus_smoke_result_contract.py \
  backend/tests/test_event_bus_smoke_gh_trigger_inputs_audit_contract.py \
  backend/tests/test_event_bus_smoke_gh_inputs_snapshot_contract.py
```

---

## 3. 日志与命令清单

常用运维命令（项目根目录）：

```bash
scripts/status.sh
scripts/logs.sh
scripts/healthcheck.sh
scripts/doctor.sh
```

开发常用检查：

```bash
make pr-check-fast
make pr-check
```

---

## 4. 什么时候该回滚

满足任一条件可触发回滚评估：

- MCP 主链路不可用且影响核心流程
- 配置刷新在关键页面大面积失效
- 合同校验误杀合法请求并持续出现

回滚顺序建议：

1. 高风险业务改动
2. 页面接入层
3. 基础能力层（composable/事件）
4. 工程脚本或 CI 改动

---

## 5. 排障后要做什么

- 记录复现步骤与根因
- 增加回归测试或监控
- 在 `tutorial-incident-runbook.md` 里补充经验条目（如为通用问题）
