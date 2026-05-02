# perilla 10 分钟极简上手

目标：第一次接触仓库的人，在约 10 分钟内完成 **启动 → 健康检查 → CSRF 验证 → 安全回归脚本**。

完整内容与排障见 **[README.md](README.md)**、**[tutorial.md](tutorial.md)**。

---

## 你将完成的事

1. 安装依赖并启动前后端（推荐与仓库脚本一致的 Conda 环境）  
2. 调用健康探针  
3. 验证写请求的 CSRF 链路  
4. （推荐）跑通租户与安全两条回归脚本  

---

## 前置条件

- Python 3.11+、Node.js 18+、Conda（推荐）  
- 已进入**项目根目录**（Standalone 常为克隆目录 `perilla`）

```bash
python --version
node --version
```

---

## 依赖安装（首次）

与根目录 `run-backend.sh` 对齐：环境名 **`ai-inference-platform`**。

```bash
conda create -n ai-inference-platform python=3.11 -y
cd backend
conda run -n ai-inference-platform pip install -r requirements.txt
cd ../frontend && npm install && cd ..
```

若已在激活的环境中，可直接 `pip install` / `npm install`。

---

## 启动服务

**推荐（项目根目录）**

```bash
./run-all.sh
```

**或分开展示**

```bash
./run-backend.sh    # 终端 A
./run-frontend.sh   # 终端 B
```

默认：后端 `http://127.0.0.1:8000`，前端 `http://localhost:5173`。

---

## 健康检查（必做）

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/live | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

预期：HTTP 200，状态字段正常。

---

## CSRF 写请求（必做）

先访问安全方法，写入 cookie 并读取响应头中的 token（需安装 [ripgrep](https://github.com/BurntSushi/ripgrep) `rg`）：

```bash
curl -i -s -c /tmp/ov_cookie.txt http://127.0.0.1:8000/api/health | tee /tmp/ov_headers.txt
export CSRF_TOKEN="$(rg "X-CSRF-Token:" /tmp/ov_headers.txt -i | awk '{print $2}' | tr -d '\r')"
echo "$CSRF_TOKEN"
```

示例写请求（按你环境替换 Key 与租户）：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/system/config" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: admin-key" \
  -H "X-Tenant-Id: tenant-dev" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{"runtimeAutoReleaseEnabled": true}' | jq .
```

缺少或错误的 `X-CSRF-Token` 应返回 **403**。

---

## 安全回归（强烈推荐）

在项目根目录：

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

通过：退出码 0，输出含 `passed` / 成功摘要。

报告位置：

- `backend/test-reports/tenant-security-summary.md`  
- `test-reports/security-regression-summary.md`  

---

## CI 手动触发（可选）

GitHub Actions：`tenant-security-regression`、`security-regression`。  
可选输入：`slow_threshold_seconds`（正整数）。PR 默认约 20s，main/master 约 30s；结果见 Step Summary 与 Artifacts。

---

## 常见失败速查

| 现象 | 处理 |
|------|------|
| `403 CSRF token validation failed` | 先 `GET /api/health` 拿 cookie 与 header，再发写请求 |
| **400** `tenant id required for protected path` | 路径是否命中租户强制前缀（**`backend/middleware/tenant_paths.py`**）；curl/脚本须显式 `X-Tenant-Id`，见 **tutorial.md §10.4** |
| Workflow **403/404** | 核对 `X-Tenant-Id`、namespace、Key 与租户绑定 |
| **429** | 降低频率或调整限流配置 |
| **409**（Idempotency） | 同 Key 须配同请求体；体变则换 Key |
| 执行 **PAUSED** | 是否存在 `approval` 节点；完成或拒绝审批 |

---

## 接下来读什么

- [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) — 新手实操版（上手与使用）  
- [tutorial.md](tutorial.md) — 全量教程  
- [tutorial-debug-playbook.md](tutorial-debug-playbook.md) — 调试手册（定位与回滚）  
- [tutorial-index.md](tutorial-index.md) — 索引与命令汇总  
- [tutorial-ops-checklist.md](tutorial-ops-checklist.md) — 发版清单  
