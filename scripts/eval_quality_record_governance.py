#!/usr/bin/env python3
"""检测报告说明受控发布 — 治理试点评估脚本。

对应论文第 3.5 节与 docs/research/quality-record-governance-pilot-protocol.md。

用法:
  # 打印样本、指标说明与记录模板
  python3 scripts/eval_quality_record_governance.py --dry-run

  # 从手工记录 JSON 计算指标
  python3 scripts/eval_quality_record_governance.py --records pilot-records.json

  # 从网关拉取最近执行并辅助核对（须先完成试点运行）
  PYTHONPATH=backend python3 scripts/eval_quality_record_governance.py \\
    --workflow-id wf_xxx --live

  # G01/G10 冒烟（优先连 live 网关，不可达时回落 in-process TestClient）
  PYTHONPATH=backend python3 scripts/eval_quality_record_governance.py --smoke
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "demos/workflows/demo1-release-brief-gate.bundle.json"


SAMPLE_BRIEFS: dict[str, str] = {
    "G01": "食品抽检任务 FS-2026-0412：出具检测说明，引用 GB 5009 系列，面向委托方。",
    "G02": "出厂检验任务 OC-2026-118：重金属项目说明，需列样品编号与检测依据。",
    "G03": "能力验证活动 PT-2026-07：结果说明草稿，参加实验室间比对。",
    "G04": "监督抽查 SC-2026-033：复检说明，原报告编号 REF-8821。",
    "G05": "委托检验 CP-2026-256：农药残留说明，需注明方法检出限。",
    "G06": "型式检验 TX-2026-019：标签合规性说明，附标准条款索引。",
    "G07": "环境检测 EN-2026-088：废水排放说明，引用排放标准。",
    "G08": "内部质量审核 IA-2026-Q2：不符合项说明整改记录。",
    "G09": "食品抽检任务 FS-2026-0412：出具检测说明，引用 GB 5009 系列，面向委托方。",
    "G10": "出厂检验任务 OC-2026-119：用于审批拒绝对照组。",
    "G11": "委托检验 CP-2026-257：用于 Checkpoint 缺项对照组。",
    "G12": "食品抽检任务 FS-2026-0412：可复现性重复组。",
}

REQUIRED_KEYS = ["text", "summary", "task_ref"]

RECORD_TEMPLATE: list[dict[str, Any]] = [
    {
        "case_id": "G01",
        "approved": True,
        "rejected": False,
        "execute_success_before_approve": False,
        "final_completed": True,
        "deliverable_keys_ok": True,
        "has_timeline": True,
        "has_approval_decision": True,
        "approval_latency_min": None,
        "notes": "",
    },
    {
        "case_id": "G10",
        "approved": False,
        "rejected": True,
        "execute_success_before_approve": False,
        "final_completed": False,
        "deliverable_keys_ok": False,
        "has_timeline": True,
        "has_approval_decision": True,
        "approval_latency_min": None,
        "notes": "拒绝后流程不得完成",
    },
]


@dataclass
class Metrics:
    pre_approve_block_rate: float | None
    reject_block_rate: float | None
    checkpoint_completeness_rate: float | None
    audit_completeness_rate: float | None
    reproducibility_rate: float | None
    approval_latency_min_samples: list[float]

    def verdict(self) -> str:
        checks = [
            self.pre_approve_block_rate == 1.0,
            self.reject_block_rate == 1.0,
            self.audit_completeness_rate == 1.0,
            self.reproducibility_rate == 1.0,
            self.checkpoint_completeness_rate is not None
            and self.checkpoint_completeness_rate >= 0.9,
        ]
        if all(checks):
            return "可受控试运行"
        if self.pre_approve_block_rate == 1.0 and self.reject_block_rate == 1.0:
            return "需整改"
        return "不纳入"


def _request(method: str, url: str, *, body: dict | None = None, headers: dict | None = None) -> Any:
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def _api_headers() -> dict[str, str]:
    hdrs: dict[str, str] = {}
    api_key = os.environ.get("PERILLA_API_KEY", "").strip()
    if api_key:
        hdrs["Authorization"] = f"Bearer {api_key}"
    tenant = os.environ.get("X_TENANT_ID", "default").strip()
    if tenant:
        hdrs["X-Tenant-Id"] = tenant
    return hdrs


def compute_metrics(records: list[dict[str, Any]]) -> Metrics:
    by_id = {str(r["case_id"]): r for r in records}

    pre_cases = [r for r in records if not r.get("rejected")]
    pre_ok = [
        r
        for r in pre_cases
        if not r.get("execute_success_before_approve", False)
    ]
    pre_rate = len(pre_ok) / len(pre_cases) if pre_cases else None

    reject_cases = [r for r in records if r.get("rejected")]
    reject_ok = [r for r in reject_cases if not r.get("final_completed", True)]
    reject_rate = len(reject_ok) / len(reject_cases) if reject_cases else None

    approve_done = [
        r
        for r in records
        if r.get("approved") and not r.get("rejected") and r.get("final_completed")
    ]
    ck_ok = [r for r in approve_done if r.get("deliverable_keys_ok")]
    ck_rate = len(ck_ok) / len(approve_done) if approve_done else None

    audit_ok = [r for r in records if r.get("has_timeline") and r.get("has_approval_decision")]
    audit_rate = len(audit_ok) / len(records) if records else None

    repro_cases = [by_id.get("G01"), by_id.get("G12")]
    repro_cases = [r for r in repro_cases if r]
    repro_ok = [r for r in repro_cases if r.get("final_completed")]
    repro_rate = len(repro_ok) / len(repro_cases) if len(repro_cases) == 2 else None

    latencies = [
        float(r["approval_latency_min"])
        for r in records
        if r.get("approval_latency_min") is not None
    ]

    return Metrics(
        pre_approve_block_rate=pre_rate,
        reject_block_rate=reject_rate,
        checkpoint_completeness_rate=ck_rate,
        audit_completeness_rate=audit_rate,
        reproducibility_rate=repro_rate,
        approval_latency_min_samples=latencies,
    )


def print_dry_run() -> None:
    print("=== 检测报告说明受控发布 · 试点评估（dry-run）===\n")
    print("样本 brief（12 组）：")
    for cid, brief in SAMPLE_BRIEFS.items():
        print(f"  {cid}: {brief}")
    print("\nCheckpoint required_keys 建议:", ", ".join(REQUIRED_KEYS))
    print("\n评价指标与目标：")
    print("  1. 审批前下游阻断率 = 100%")
    print("  2. 拒绝阻断率 = 100%")
    print("  3. Checkpoint 完备率 ≥ 90%")
    print("  4. 审计记录完整率 = 100%")
    print("  5. 审批时延（描述性）")
    print("  6. 配置可复现性（G01 vs G12）= 100%")
    print("\n记录模板 JSON（可复制为 pilot-records.json 后填写）：")
    print(json.dumps(RECORD_TEMPLATE, ensure_ascii=False, indent=2))
    print("\n操作协议: docs/research/quality-record-governance-pilot-protocol.md")


def load_live_hints(workflow_id: str) -> list[dict[str, Any]]:
    base = os.environ.get("PERILLA_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    headers = _api_headers()
    url = f"{base}/api/v1/workflows/{workflow_id}/executions?limit=20&live=true"
    try:
        data = _request("GET", url, headers=headers)
    except (urllib.error.URLError, SystemExit) as exc:
        print(f"无法连接网关: {exc}", file=sys.stderr)
        return []

    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    hints: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        eid = item.get("execution_id") or item.get("id")
        state = item.get("state") or item.get("execution_state")
        hints.append(
            {
                "execution_id": eid,
                "state": state,
                "hint": "对照 protocol 填写 pilot-records.json",
            }
        )
    return hints


class HttpClient:
    """统一 live urllib 与 TestClient 调用。"""

    def __init__(self, *, base_url: str = "", test_client: Any = None, headers: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.test_client = test_client
        self.headers = dict(headers or {})
        self._csrf_token = ""
        self._opener: urllib.request.OpenerDirector | None = None
        if self.test_client is None and self.base_url:
            jar = http.cookiejar.CookieJar()
            self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            self._prime_csrf()

    def _prime_csrf(self) -> None:
        if self._opener is None:
            return
        url = f"{self.base_url}/api/health"
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with self._opener.open(req, timeout=10) as resp:
                self._csrf_token = (resp.headers.get("X-CSRF-Token") or "").strip()
        except Exception:
            self._csrf_token = ""

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        params: dict | None = None,
        timeout: float = 120.0,
    ) -> tuple[int, Any]:
        if self.test_client is not None:
            url = path
            if params:
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                url = f"{path}?{qs}"
            if method.upper() == "GET":
                resp = self.test_client.get(url, headers=self.headers)
            else:
                resp = self.test_client.post(url, json=body or {}, headers=self.headers)
            try:
                return int(resp.status_code), resp.json()
            except Exception:
                return int(resp.status_code), resp.text

        qs = ""
        if params:
            qs = "?" + "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url = f"{self.base_url}{path}{qs}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        hdrs = {"Content-Type": "application/json", "Accept": "application/json", **self.headers}
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and self._csrf_token:
            hdrs["X-CSRF-Token"] = self._csrf_token
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
        opener = self._opener or urllib.request
        try:
            with opener.open(req, timeout=timeout) as resp:
                token = (resp.headers.get("X-CSRF-Token") or "").strip()
                if token:
                    self._csrf_token = token
                raw = resp.read().decode("utf-8")
                code = int(resp.status)
                try:
                    return code, json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError:
                    return code, raw
        except urllib.error.HTTPError as exc:
            token = (exc.headers.get("X-CSRF-Token") or "").strip()
            if token:
                self._csrf_token = token
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                return int(exc.code), json.loads(detail)
            except json.JSONDecodeError:
                return int(exc.code), detail


def _health_ok(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


@contextmanager
def _inprocess_client() -> Iterator[HttpClient]:
    sys.path.insert(0, str(ROOT / "backend"))
    import main as main_mod
    from config.settings import settings
    from core.security.deps import require_platform_write
    from core.security.rbac import PlatformRole
    from fastapi.testclient import TestClient

    prev_csrf = bool(getattr(settings, "csrf_enabled", True))
    settings.csrf_enabled = False
    settings.tenant_enforcement_enabled = False
    settings.tenant_api_key_binding_enabled = False
    main_mod.app.dependency_overrides[require_platform_write] = lambda: PlatformRole.OPERATOR
    with TestClient(main_mod.app) as tc:
        try:
            yield HttpClient(
                test_client=tc,
                headers={"X-User-Id": "qa-pilot-smoke", "X-Tenant-Id": "default"},
            )
        finally:
            main_mod.app.dependency_overrides.pop(require_platform_write, None)
            settings.csrf_enabled = prev_csrf


def _resolve_published_version(client: HttpClient, workflow_id: str) -> str:
    code, body = client.request("GET", f"/api/v1/workflows/{workflow_id}")
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"查询工作流失败: {code} {body}")
    version_id = str(body.get("published_version_id") or "").strip()
    if version_id:
        return version_id
    code, listed = client.request("GET", f"/api/v1/workflows/{workflow_id}/versions")
    if code == 200 and isinstance(listed, dict):
        for item in listed.get("items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("state") or "").lower() == "published":
                vid = str(item.get("version_id") or "").strip()
                if vid:
                    return vid
    latest = str(body.get("latest_version_id") or "").strip()
    if latest:
        return latest
    raise RuntimeError(f"工作流 {workflow_id} 无已发布版本")


def _load_workflow_from_records(records_path: Path) -> tuple[str, str | None]:
    records = json.loads(records_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise RuntimeError("records 文件须为 JSON 数组")
    for rec in records:
        if not isinstance(rec, dict):
            continue
        wf = str(rec.get("workflow_id") or "").strip()
        if wf:
            ver = str(rec.get("version_id") or "").strip() or None
            return wf, ver
    raise RuntimeError(f"{records_path} 中未找到 workflow_id")


def _merge_records(existing: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(r["case_id"]): r for r in existing if isinstance(r, dict) and r.get("case_id")}
    for rec in updates:
        by_id[str(rec["case_id"])] = rec
    order = ["G01", "G10", "G12"] + sorted(
        cid for cid in by_id if cid not in {"G01", "G10", "G12"}
    )
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for cid in order:
        if cid in by_id and cid not in seen:
            merged.append(by_id[cid])
            seen.add(cid)
    for cid, rec in by_id.items():
        if cid not in seen:
            merged.append(rec)
    return merged


def _import_workflow(client: HttpClient) -> tuple[str, str, bool]:
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    dag = bundle["dag"]
    base_name = str(bundle.get("workflow_name") or "QA Pilot · 质量记录受控发布")
    wf_name = f"{base_name} · smoke-{uuid.uuid4().hex[:8]}"
    code, created = client.request(
        "POST",
        "/api/v1/workflows",
        body={
            "namespace": "default",
            "name": wf_name,
            "description": "质量信息化治理试点冒烟",
            "tags": ["qa-pilot", "smoke"],
            "metadata": {"pilot": "quality-record-governance"},
        },
    )
    if code not in (200, 201):
        raise RuntimeError(f"创建工作流失败: {code} {created}")
    workflow_id = str(created.get("id") or "")
    code, version = client.request(
        "POST",
        f"/api/v1/workflows/{workflow_id}/versions",
        body={"dag": dag, "description": "smoke import"},
    )
    if code not in (200, 201):
        raise RuntimeError(f"创建版本失败: {code} {version}")
    version_id = str(version.get("version_id") or "")
    published = False
    code, _pub = client.request(
        "POST",
        f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish",
        body={},
    )
    if code in (200, 201, 204):
        published = True
    return workflow_id, version_id, published


def _start_execution(
    client: HttpClient, workflow_id: str, brief: str, *, version_id: str | None = None
) -> str:
    code, body = client.request(
        "POST",
        f"/api/v1/workflows/{workflow_id}/executions",
        body={
            "workflow_id": workflow_id,
            "version_id": version_id,
            "input_data": {"brief": brief},
            "global_context": {},
            "trigger_type": "api",
        },
        params={"wait": "false"},
    )
    if code not in (200, 201):
        raise RuntimeError(f"启动执行失败: {code} {body}")
    execution_id = str(body.get("execution_id") or body.get("id") or "")
    if not execution_id:
        raise RuntimeError(f"无 execution_id: {body}")
    return execution_id


def _get_status(client: HttpClient, workflow_id: str, execution_id: str) -> dict:
    paths = (
        f"/api/v1/workflows/{workflow_id}/executions/{execution_id}",
        f"/api/v1/workflows/{workflow_id}/executions/{execution_id}/status",
    )
    last_err: Exception | None = None
    for path in paths:
        try:
            code, body = client.request("GET", path, timeout=25.0)
        except (TimeoutError, urllib.error.URLError) as exc:
            last_err = exc
            continue
        if code == 200 and isinstance(body, dict):
            return body
        last_err = RuntimeError(f"查询状态失败: {code} {body}")
    if last_err:
        raise last_err
    raise RuntimeError("查询状态失败: unknown")


def _wait_until(
    client: HttpClient,
    workflow_id: str,
    execution_id: str,
    *,
    want_states: set[str],
    timeout: float = 180.0,
    poll: float = 2.0,
    require_genuine_terminal: bool = False,
) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        try:
            last = _get_status(client, workflow_id, execution_id)
        except (TimeoutError, urllib.error.URLError):
            time.sleep(poll)
            continue
        state = str(last.get("state") or "").lower()
        if state in want_states:
            if require_genuine_terminal and state in {"failed", "cancelled", "timeout"}:
                if not _is_genuine_terminal(last):
                    time.sleep(poll)
                    continue
            return last
        if state in {"failed", "cancelled", "completed", "timeout"}:
            if require_genuine_terminal and not _is_genuine_terminal(last):
                time.sleep(poll)
                continue
            return last
        time.sleep(poll)
    return last


def _list_approvals(client: HttpClient, workflow_id: str, execution_id: str) -> list[dict]:
    code, body = client.request(
        "GET",
        f"/api/v1/workflows/{workflow_id}/executions/{execution_id}/approvals",
    )
    if code != 200:
        raise RuntimeError(f"列出审批失败: {code} {body}")
    items = body.get("items") if isinstance(body, dict) else None
    return items if isinstance(items, list) else []


def _approve(client: HttpClient, workflow_id: str, execution_id: str, task_id: str) -> None:
    code, body = client.request(
        "POST",
        f"/api/v1/workflows/{workflow_id}/executions/{execution_id}/approvals/{task_id}/approve",
        body={"comment": "冒烟：同意生成说明"},
    )
    if code != 200:
        raise RuntimeError(f"审批失败: {code} {body}")


def _reject(client: HttpClient, workflow_id: str, execution_id: str, task_id: str) -> None:
    code, body = client.request(
        "POST",
        f"/api/v1/workflows/{workflow_id}/executions/{execution_id}/approvals/{task_id}/reject",
        body={"comment": "冒烟：拒绝放行"},
    )
    if code != 200:
        raise RuntimeError(f"拒绝失败: {code} {body}")


def _node_named(status: dict, node_id: str) -> dict | None:
    for item in status.get("node_states") or []:
        if isinstance(item, dict) and item.get("node_id") == node_id:
            return item
    return None


def _is_genuine_terminal(status: dict) -> bool:
    """忽略审批后短暂的伪 failed（execute 尚未终态）。"""
    state = str(status.get("state") or "").lower()
    if state == "completed":
        return True
    if state not in {"failed", "cancelled", "timeout"}:
        return False
    nodes = status.get("node_states") or []
    if not nodes:
        return False
    execute = _node_named(status, "execute")
    if not execute:
        return all(
            str((n or {}).get("state") or "").lower()
            in {"success", "failed", "skipped", "cancelled", "timeout"}
            for n in nodes
            if isinstance(n, dict)
        )
    execute_state = str(execute.get("state") or "").lower()
    return execute_state in {"success", "failed", "skipped", "cancelled", "timeout"}


def _deliverable_from_detail(detail: dict) -> tuple[bool, bool]:
    """从执行详情判断 deliverable / checkpoint 是否满足 text+summary。"""
    checkpoint_ok = False
    deliverable_ok = False
    execute = _node_named(detail, "execute")
    if execute:
        out = (
            execute.get("output_data")
            or execute.get("output")
            or execute.get("result")
            or {}
        )
        if isinstance(out, dict):
            deliverable_ok = all(str(out.get(k) or "").strip() for k in ("text", "summary"))
    checkpoint = _node_named(detail, "checkpoint_verify")
    if checkpoint and str(checkpoint.get("state") or "").lower() == "success":
        checkpoint_ok = True
    if not deliverable_ok:
        out_data = detail.get("output_data") if isinstance(detail.get("output_data"), dict) else {}
        nested = out_data.get("deliverable")
        if isinstance(nested, dict):
            deliverable_ok = all(str(nested.get(k) or "").strip() for k in ("text", "summary"))
    return deliverable_ok, checkpoint_ok


def _run_approve_case(
    client: HttpClient,
    workflow_id: str,
    version_id: str,
    *,
    case_id: str,
    brief: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """G01/G12 批准路径：暂停 → 批准 → completed + deliverable 校验。"""
    execution_id = _start_execution(client, workflow_id, brief, version_id=version_id)
    status = _wait_until(client, workflow_id, execution_id, want_states={"paused"}, timeout=180)
    state = str(status.get("state") or "").lower()
    approvals = _list_approvals(client, workflow_id, execution_id)
    execute_before = _node_named(status, "execute")
    execute_before_ok = not (
        execute_before and str(execute_before.get("state", "")).lower() == "success"
    )
    completed = False
    deliverable_ok = False
    checkpoint_ok = False
    detail: dict = status
    code = 0
    if state == "paused" and approvals:
        _approve(client, workflow_id, execution_id, str(approvals[0].get("id")))
        status = _wait_until(
            client,
            workflow_id,
            execution_id,
            want_states={"completed", "failed"},
            timeout=600,
            require_genuine_terminal=True,
        )
        code, detail = client.request(
            "GET", f"/api/v1/workflows/{workflow_id}/executions/{execution_id}"
        )
        if code == 200 and isinstance(detail, dict):
            completed = str(detail.get("state") or status.get("state") or "").lower() == "completed"
            deliverable_ok, checkpoint_ok = _deliverable_from_detail(detail)
        else:
            completed = str(status.get("state") or "").lower() == "completed"
    case_report = {
        "execution_id": execution_id,
        "paused": state == "paused",
        "pre_approve_execute_blocked": execute_before_ok,
        "final_state": status.get("state"),
        "completed": completed,
        "deliverable_text_summary": deliverable_ok,
        "checkpoint_passed": checkpoint_ok,
    }
    record = {
        "case_id": case_id,
        "approved": True,
        "rejected": False,
        "execute_success_before_approve": not execute_before_ok,
        "final_completed": completed,
        "deliverable_keys_ok": deliverable_ok,
        "checkpoint_passed": checkpoint_ok,
        "has_timeline": bool(
            (detail if code == 200 else status).get("node_states")
            or status.get("node_timeline")
        ),
        "has_approval_decision": bool(approvals),
        "workflow_id": workflow_id,
        "execution_id": execution_id,
    }
    return case_report, record


def run_g12(
    *,
    base_url: str | None = None,
    prefer_live: bool = True,
    workflow_id: str | None = None,
    version_id: str | None = None,
    records_path: Path | None = None,
) -> dict[str, Any]:
    """G12 可复现性对照：复用 G01 同版本工作流，重复 brief 批准路径。"""
    report: dict[str, Any] = {"mode": None, "cases": {}, "records": [], "ok": False}
    base = (base_url or os.environ.get("PERILLA_API_BASE", "http://127.0.0.1:8000")).rstrip("/")

    wf_id = (workflow_id or "").strip()
    ver_id = (version_id or "").strip() or None
    if not wf_id and records_path:
        wf_id, ver_id = _load_workflow_from_records(records_path)
    if not wf_id:
        raise RuntimeError("G12 须提供 --workflow-id 或含 workflow_id 的 --records")

    if prefer_live and _health_ok(base):
        headers = _api_headers()
        headers.setdefault("X-User-Id", "qa-pilot-smoke")
        headers.setdefault("X-Tenant-Id", "default")
        client = HttpClient(base_url=base, headers=headers)
        report["mode"] = "live"
    else:
        report["mode"] = "inprocess"

    def _run_with(client: HttpClient) -> None:
        nonlocal ver_id
        if not ver_id:
            ver_id = _resolve_published_version(client, wf_id)
        report["workflow_id"] = wf_id
        report["version_id"] = ver_id
        case_report, record = _run_approve_case(
            client,
            wf_id,
            ver_id,
            case_id="G12",
            brief=SAMPLE_BRIEFS["G12"],
        )
        record["notes"] = "可复现性：同版本工作流重复 G01 brief，批准后 completed"
        report["cases"]["G12"] = case_report
        report["records"].append(record)

    if report["mode"] == "live":
        _run_with(client)
    else:
        with _inprocess_client() as client:
            _run_with(client)

    if report["records"]:
        merged_for_metrics = list(report["records"])
        if records_path and records_path.is_file():
            existing = json.loads(records_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                merged_for_metrics = _merge_records(existing, report["records"])
        metrics = compute_metrics(merged_for_metrics)
        report["metrics"] = {
            "pre_approve_block_rate": metrics.pre_approve_block_rate,
            "reject_block_rate": metrics.reject_block_rate,
            "checkpoint_completeness_rate": metrics.checkpoint_completeness_rate,
            "audit_completeness_rate": metrics.audit_completeness_rate,
            "reproducibility_rate": metrics.reproducibility_rate,
        }
        report["verdict"] = metrics.verdict()
        g12 = report["cases"].get("G12", {})
        report["ok"] = (
            g12.get("paused")
            and g12.get("completed")
            and g12.get("deliverable_text_summary")
            and metrics.reproducibility_rate == 1.0
        )
    return report


def run_smoke(*, base_url: str | None = None, prefer_live: bool = True) -> dict[str, Any]:
    report: dict[str, Any] = {"mode": None, "cases": {}, "records": [], "ok": False}
    base = (base_url or os.environ.get("PERILLA_API_BASE", "http://127.0.0.1:8000")).rstrip("/")

    if prefer_live and _health_ok(base):
        headers = _api_headers()
        headers.setdefault("X-User-Id", "qa-pilot-smoke")
        headers.setdefault("X-Tenant-Id", "default")
        client = HttpClient(base_url=base, headers=headers)
        report["mode"] = "live"
    else:
        report["mode"] = "inprocess"

    def _run_with(client: HttpClient) -> None:
        wf_id, ver_id, published = _import_workflow(client)
        report["workflow_id"] = wf_id
        report["version_id"] = ver_id
        report["published"] = published

        # G10：拒绝应阻断完成
        ex10 = _start_execution(client, wf_id, SAMPLE_BRIEFS["G10"], version_id=ver_id)
        st10 = _wait_until(client, wf_id, ex10, want_states={"paused"}, timeout=180)
        state10 = str(st10.get("state") or "").lower()
        approvals10 = _list_approvals(client, wf_id, ex10)
        g10_ok = False
        if state10 == "paused" and approvals10:
            _reject(client, wf_id, ex10, str(approvals10[0].get("id")))
            st10 = _wait_until(client, wf_id, ex10, want_states={"failed", "cancelled", "completed"}, timeout=60)
            g10_ok = str(st10.get("state") or "").lower() in {"failed", "cancelled"}
        report["cases"]["G10"] = {
            "execution_id": ex10,
            "paused": state10 == "paused",
            "final_state": st10.get("state"),
            "reject_block": g10_ok,
        }
        report["records"].append(
            {
                "case_id": "G10",
                "approved": False,
                "rejected": True,
                "execute_success_before_approve": _node_named(st10, "execute") is not None
                and str((_node_named(st10, "execute") or {}).get("state", "")).lower() == "success",
                "final_completed": str(st10.get("state") or "").lower() == "completed",
                "deliverable_keys_ok": False,
                "has_timeline": bool(st10.get("node_states") or st10.get("node_timeline")),
                "has_approval_decision": bool(approvals10),
            }
        )

        # G01：批准路径
        ex01 = _start_execution(client, wf_id, SAMPLE_BRIEFS["G01"], version_id=ver_id)
        st01 = _wait_until(client, wf_id, ex01, want_states={"paused"}, timeout=180)
        state01 = str(st01.get("state") or "").lower()
        approvals01 = _list_approvals(client, wf_id, ex01)
        execute_before = _node_named(st01, "execute")
        execute_before_ok = not (
            execute_before and str(execute_before.get("state", "")).lower() == "success"
        )
        g01_ok = False
        deliverable_ok = False
        checkpoint_ok = False
        detail: dict = st01
        code = 0
        if state01 == "paused" and approvals01:
            _approve(client, wf_id, ex01, str(approvals01[0].get("id")))
            st01 = _wait_until(
                client,
                wf_id,
                ex01,
                want_states={"completed", "failed"},
                timeout=600,
                require_genuine_terminal=True,
            )
            code, detail = client.request(
                "GET", f"/api/v1/workflows/{wf_id}/executions/{ex01}"
            )
            if code == 200 and isinstance(detail, dict):
                g01_ok = str(detail.get("state") or st01.get("state") or "").lower() == "completed"
                deliverable_ok, checkpoint_ok = _deliverable_from_detail(detail)
            else:
                g01_ok = str(st01.get("state") or "").lower() == "completed"
                deliverable_ok = False
                checkpoint_ok = False
        report["cases"]["G01"] = {
            "execution_id": ex01,
            "paused": state01 == "paused",
            "pre_approve_execute_blocked": execute_before_ok,
            "final_state": st01.get("state"),
            "completed": g01_ok,
            "deliverable_text_summary": deliverable_ok,
            "checkpoint_passed": checkpoint_ok,
        }
        report["records"].append(
            {
                "case_id": "G01",
                "approved": True,
                "rejected": False,
                "execute_success_before_approve": not execute_before_ok,
                "final_completed": g01_ok,
                "deliverable_keys_ok": deliverable_ok,
                "checkpoint_passed": checkpoint_ok,
                "has_timeline": bool(
                    (detail if code == 200 else st01).get("node_states")
                    or st01.get("node_timeline")
                ),
                "has_approval_decision": bool(approvals01),
            }
        )

    if report["mode"] == "live":
        _run_with(client)
    else:
        with _inprocess_client() as client:
            _run_with(client)

    if report["records"]:
        metrics = compute_metrics(report["records"])
        report["metrics"] = {
            "pre_approve_block_rate": metrics.pre_approve_block_rate,
            "reject_block_rate": metrics.reject_block_rate,
            "checkpoint_completeness_rate": metrics.checkpoint_completeness_rate,
            "audit_completeness_rate": metrics.audit_completeness_rate,
        }
        report["verdict"] = metrics.verdict()
        g01 = report["cases"].get("G01", {})
        report["ok"] = (
            report["cases"].get("G10", {}).get("reject_block")
            and g01.get("paused")
            and g01.get("completed")
            and g01.get("deliverable_text_summary")
            and metrics.pre_approve_block_rate == 1.0
            and metrics.reject_block_rate == 1.0
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="质量记录受控发布试点评估")
    parser.add_argument("--dry-run", action="store_true", help="打印样本与记录模板")
    parser.add_argument("--records", type=Path, help="试点记录 JSON 路径")
    parser.add_argument("--workflow-id", help="工作流 ID（--live 时使用）")
    parser.add_argument("--live", action="store_true", help="列出最近执行供核对")
    parser.add_argument("--smoke", action="store_true", help="运行 G01/G10 冒烟")
    parser.add_argument(
        "--g12",
        action="store_true",
        help="运行 G12 可复现性对照（复用已有 workflow_id / 已发布版本）",
    )
    parser.add_argument("--version-id", help="工作流版本 ID（--g12 可选，缺省取已发布版本）")
    parser.add_argument(
        "--merge-records",
        action="store_true",
        help="写入记录时与已有 JSON 按 case_id 合并，而非覆盖",
    )
    parser.add_argument("--base-url", default=os.environ.get("PERILLA_API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--inprocess-only", action="store_true", help="仅用 TestClient，不连 uvicorn")
    parser.add_argument("--export-template", type=Path, help="导出记录模板到文件")
    parser.add_argument(
        "--write-records",
        type=Path,
        help="冒烟结束后将 records 写入 JSON（如 docs/research/pilot-records.json）",
    )
    args = parser.parse_args()

    if args.export_template:
        args.export_template.write_text(
            json.dumps(RECORD_TEMPLATE, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已写入模板: {args.export_template}")
        return

    if args.smoke:
        report = run_smoke(
            base_url=args.base_url,
            prefer_live=not args.inprocess_only,
        )
        if args.write_records and report.get("records"):
            args.write_records.parent.mkdir(parents=True, exist_ok=True)
            payload = report["records"]
            if args.merge_records and args.write_records.is_file():
                existing = json.loads(args.write_records.read_text(encoding="utf-8"))
                payload = _merge_records(existing, payload)
            args.write_records.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"已写入试点记录: {args.write_records}", file=sys.stderr)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report.get("ok") else 1)

    if args.g12:
        report = run_g12(
            base_url=args.base_url,
            prefer_live=not args.inprocess_only,
            workflow_id=args.workflow_id,
            version_id=args.version_id,
            records_path=args.records,
        )
        if args.write_records and report.get("records"):
            args.write_records.parent.mkdir(parents=True, exist_ok=True)
            payload = report["records"]
            if args.merge_records or args.write_records.is_file():
                existing: list[dict[str, Any]] = []
                if args.write_records.is_file():
                    existing = json.loads(args.write_records.read_text(encoding="utf-8"))
                elif args.records and args.records.is_file():
                    existing = json.loads(args.records.read_text(encoding="utf-8"))
                payload = _merge_records(existing, payload)
            args.write_records.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"已写入试点记录: {args.write_records}", file=sys.stderr)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report.get("ok") else 1)

    if args.dry_run or (not args.records and not args.live):
        print_dry_run()
        return

    if args.live:
        if not args.workflow_id:
            raise SystemExit("--live 须同时提供 --workflow-id")
        hints = load_live_hints(args.workflow_id)
        print(json.dumps(hints, ensure_ascii=False, indent=2))
        print("\n请根据执行结果填写 --records JSON 后重新运行以计算指标。")
        return

    if args.records:
        records = json.loads(args.records.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise SystemExit("records 文件须为 JSON 数组")
        metrics = compute_metrics(records)
        report = {
            "metrics": {
                "pre_approve_block_rate": metrics.pre_approve_block_rate,
                "reject_block_rate": metrics.reject_block_rate,
                "checkpoint_completeness_rate": metrics.checkpoint_completeness_rate,
                "audit_completeness_rate": metrics.audit_completeness_rate,
                "reproducibility_rate": metrics.reproducibility_rate,
                "approval_latency_min_samples": metrics.approval_latency_min_samples,
            },
            "verdict": metrics.verdict(),
            "case_count": len(records),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
