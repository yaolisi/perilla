# OpenVitamin Enhanced 10 分钟极简上手

> 目标：第一次接触项目的人，在 10 分钟内完成“启动 + 安全验证 + 回归脚本”。

完整教程与错误码跳转见 **[README.md](README.md)**、**[tutorial.md](tutorial.md)**。

---

## 0. 你将完成什么

1. 安装依赖并启动前后端  
2. 验证健康探针  
3. 验证 CSRF 写请求链路  
4. 跑通 tenant/security 两条安全回归脚本

---

## 1. 前置条件

- Python 3.11+
- Node.js 18+
- Conda（推荐）
- 已获取仓库并进入项目根目录（Standalone 通常为 `openvitamin_enhanced_docker`）

快速检查：

```bash
python --version
node --version
```

---

## 2. 安装依赖（首次一次）

后端：

```bash
cd backend
pip install -r requirements.txt
cd ..
```

前端：

```bash
cd frontend
npm install
cd ..
```

---

## 3. 启动服务

终端 A（后端）：

```bash
cd backend
python main.py
```

终端 B（前端）：

```bash
cd frontend
npm run dev
```

---

## 4. 第一步健康检查（必须）

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/live | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

预期：三个接口都返回 200 且状态正常。

---

## 5. 第二步安全检查：CSRF（必须）

先拿 token（会写 cookie）：

```bash
curl -i -s -c /tmp/ov_cookie.txt http://127.0.0.1:8000/api/health | tee /tmp/ov_headers.txt
export CSRF_TOKEN="$(rg "X-CSRF-Token:" /tmp/ov_headers.txt -i | awk '{print $2}' | tr -d '\r')"
echo "$CSRF_TOKEN"
```

再发一个写请求（示例：system config）：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/system/config" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: admin-key" \
  -H "X-Tenant-Id: tenant-dev" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{"runtimeAutoReleaseEnabled": true}' | jq .
```

如果不带 `X-CSRF-Token` 或 token 不匹配，预期 `403`。

---

## 6. 第三步安全回归（推荐必跑）

在项目根目录执行：

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

通过标准：

- 输出 `passed`
- 退出码为 0

会生成摘要：

- `backend/test-reports/tenant-security-summary.md`
- `test-reports/security-regression-summary.md`

---

## 7. CI 手动触发（可选）

在 GitHub Actions 触发：

- `tenant-security-regression`
- `security-regression`

可选输入：

- `slow_threshold_seconds`（必须正整数，如 `20`）

说明：

- PR 默认阈值 20s
- main/master 默认阈值 30s
- 结果可在 Step Summary 直接查看

---

## 8. 常见失败快速处理

- `403 CSRF token validation failed`  
  - 先 `GET /api/health` 取 token，再带 cookie + header 发写请求
- `404/403 workflow`  
  - 检查 `X-Tenant-Id` 与 namespace、API Key tenant 绑定
- `429`  
  - 降低压测频率或调整限流配置

---

## 9. 接下来读什么

- 全量教程：`tutorial.md`
- 教程导航：`tutorial-index.md`
- 运维清单：`tutorial-ops-checklist.md`
