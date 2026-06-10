# 检测报告说明受控发布 — 试点操作协议

> 对应论文第 3.5 节。在测试租户执行，不替代正式质量管理制度。

## 1. 目标

验证表1 中「人机协同放行」「过程可审计」「输出可核验」在单一质量活动内是否按预期生效。

## 2. 前置条件

- [ ] Perilla 内网实例已启动（Conda 后端 + 前端）
- [ ] 可用本地 LLM（`/models` 页面可见）
- [ ] 已创建测试租户 `qa-pilot`（与生产租户隔离）
- [ ] 质量负责人、质量技术员各 1 名（试点评审角色）

## 3. 工作流准备

### 3.1 导入

```bash
cd /path/to/perilla
X_TENANT_ID=qa-pilot PUBLISH=1 \
  PYTHONPATH=backend python3 scripts/import_demo_workflow.py \
  demos/workflows/demo1-release-brief-gate.bundle.json
```

记录输出的 `workflow_id`。

### 3.2 画布改造（对照论文 3.5.2）

| 节点 | 调整项 |
|------|--------|
| `approval_plan` | 标题改为「质量负责人确认说明起草计划」 |
| `execute` | Prompt 改为检测说明撰写语境（见 §4 样本） |
| `checkpoint_verify` | `required_keys` 设为 `["text", "summary", "task_ref"]` |

保存 → 预检 → **发布版本**（记下 `version_id`）。

## 4. 样本 brief（12 组）

### 常规组（G01–G08，应 approve + checkpoint 通过）

| 编号 | brief 摘要 |
|------|------------|
| G01 | 食品抽检任务 FS-2026-0412：出具检测说明，引用 GB 5009 系列，面向委托方。 |
| G02 | 出厂检验任务 OC-2026-118：重金属项目说明，需列样品编号与检测依据。 |
| G03 | 能力验证活动 PT-2026-07：结果说明草稿，参加实验室间比对。 |
| G04 | 监督抽查 SC-2026-033：复检说明，原报告编号 REF-8821。 |
| G05 | 委托检验 CP-2026-256：农药残留说明，需注明方法检出限。 |
| G06 | 型式检验 TX-2026-019：标签合规性说明，附标准条款索引。 |
| G07 | 环境检测 EN-2026-088：废水排放说明，引用排放标准。 |
| G08 | 内部质量审核 IA-2026-Q2：不符合项说明整改记录。 |

### 对照组

| 编号 | 操作 | 预期 |
|------|------|------|
| G09 | approve 后正常完成 | 与 G01–G08 相同 |
| G10 | **reject** 审批 | 下游不得 SUCCESS，无 deliverable |
| G11 | approve，但临时将 required_keys 改为 `["nonexistent"]` | checkpoint 失败 |
| G12 | 重复 G01 brief（同版本工作流） | 验证可复现性 |

## 5. 执行与记录

每组执行：

1. Run 页提交 `{"brief": "..."}`  
2. 记录 `execution_id`、暂停时刻 `T_pause`  
3. 审批 API（示例）：

```bash
BASE=http://127.0.0.1:8000
WF={workflow_id}
EX={execution_id}
HDR="-H X-Tenant-Id: qa-pilot"

curl -s "$BASE/api/v1/workflows/$WF/executions/$EX/approvals" $HDR | jq .

curl -s -X POST "$BASE/api/v1/workflows/$WF/executions/$EX/approvals/{task_id}/approve" \
  $HDR -H "Content-Type: application/json" \
  -d '{"comment":"同意按计划在受控条件下生成说明"}' | jq .
```

拒绝组使用 `/reject` 端点。

4. 记录 `T_approve`、各节点状态、deliverable 字段  
5. 导出 Timeline（运行页）或 call-chain API

## 6. 评价指标

| 指标 | 计算 | 目标 |
|------|------|------|
| 审批前下游阻断率 | 未 approve 的执行中 execute 非 SUCCESS 占比 | 100% |
| 拒绝阻断率 | reject 组流程未完成占比 | 100% |
| Checkpoint 完备率 | approve 组 deliverable 含全部 required_keys | ≥90% |
| 审计记录完整率 | 有 approval_decisions + Timeline 节点链 | 100% |
| 审批时延 | T_approve − T_pause（分钟） | 描述性统计 |
| 配置可复现性 | G12 与 G01 同版本成功运行 | 100% |

自动初算：

```bash
PYTHONPATH=backend python3 scripts/eval_quality_record_governance.py \
  --workflow-id {workflow_id} --dry-run

# 网关可用时：
PYTHONPATH=backend python3 scripts/eval_quality_record_governance.py \
  --workflow-id {workflow_id} --live
```

## 7. 评审会

参会：质量负责人、质量技术员、信息化负责人。

材料：指标汇总表、2 个 Timeline 截图、1 份 reject 阻断证据、1 份 checkpoint 失败证据。

结论（三选一）：

- **可受控试运行** — 指标（1）（2）（4）（6）全部达标，且（3）≥90%
- **需整改** — 门控生效但完备率或审计有缺口，明确整改项与复测日期
- **不纳入** — 关键门控失效，不进入体系文件讨论

## 8. 与论文的关系

- 第 3.1—3.4 节：功能映射与 PoC 观察（已完成）
- 本节：场景化有效性验证（待实施）
- 实施结果回填论文时，建议新增「试点结果」小节或独立技术报告，不在未定稿前写入结论性有效率
