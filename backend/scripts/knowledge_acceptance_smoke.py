#!/usr/bin/env python3
"""
知识库/RAG 能力一键验收脚本（冒烟）。

覆盖链路：
1) 创建知识库
2) 创建版本（v2）
3) 上传文档
4) 按 version_label 检索
5) 图谱检索
6) reindex（内容不变，预期跳过）

示例：
  cd backend && python scripts/knowledge_acceptance_smoke.py --embedding-model-id embedding:test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import httpx
except ImportError:
    print("需要安装 httpx: pip install httpx")
    raise SystemExit(1)


def _print_step(title: str) -> None:
    print(f"\n[{title}]")


def _safe_get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _build_headers(api_key: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key.strip():
        headers["X-Api-Key"] = api_key.strip()
    return headers


def _check(cond: bool, message: str, failures: list[str]) -> None:
    if cond:
        print(f"  PASS - {message}")
    else:
        print(f"  FAIL - {message}")
        failures.append(message)


def _request_raise(resp: httpx.Response, name: str) -> dict[str, Any]:
    try:
        resp.raise_for_status()
    except Exception as e:
        body = resp.text[:800]
        raise RuntimeError(f"{name} failed: {e}; body={body}") from e
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"{name} returned non-object json")
    return data


def run_smoke(
    *,
    base_url: str,
    embedding_model_id: str,
    api_key: str,
    top_k: int,
    timeout_seconds: float,
    output_file: str,
) -> int:
    failures: list[str] = []
    report: dict[str, Any] = {"ok": False, "steps": {}}
    base = base_url.rstrip("/")
    headers = _build_headers(api_key)
    timeout = httpx.Timeout(timeout_seconds)

    with httpx.Client(base_url=base, headers=headers, timeout=timeout) as client:
        _print_step("1. 创建知识库")
        kb_payload = {
            "name": "Smoke KB",
            "description": "knowledge acceptance smoke",
            "embedding_model_id": embedding_model_id,
            "chunk_size": 256,
            "chunk_overlap": 32,
            "chunk_size_overrides": {"txt": 256},
        }
        kb_data = _request_raise(client.post("/api/knowledge-bases", json=kb_payload), "create_knowledge_base")
        kb_id = str(kb_data.get("id", "")).strip()
        report["steps"]["create_kb"] = {"kb_id": kb_id, "response": kb_data}
        _check(bool(kb_id), "创建知识库返回 kb_id", failures)

        _print_step("2. 创建版本(v2)")
        ver_data = _request_raise(
            client.post(
                f"/api/knowledge-bases/{kb_id}/versions",
                json={"version_label": "v2", "notes": "smoke-release-v2"},
            ),
            "create_kb_version",
        )
        version_id = str(ver_data.get("id", "")).strip()
        report["steps"]["create_version"] = {"version_id": version_id, "response": ver_data}
        _check(bool(version_id), "创建版本返回 version_id", failures)

        _print_step("3. 上传文档")
        file_content = (
            "OpenVINO 是 Intel 开发的 AI 推理框架。\n"
            "如何配置 OpenVINO 的 GPU 设备：设置 device=GPU。\n"
            "如果是 CPU 设备请设置 device=CPU。\n"
        ).encode("utf-8")
        files = {"file": ("openvino_gpu.txt", file_content, "text/plain")}
        up_data = _request_raise(
            client.post(f"/api/knowledge-bases/{kb_id}/documents", files=files),
            "upload_document",
        )
        doc_id = str(up_data.get("id", "")).strip()
        report["steps"]["upload_document"] = {"doc_id": doc_id, "response": up_data}
        _check(bool(doc_id), "上传文档返回 doc_id", failures)

        _print_step("4. 按 version_label 检索")
        search_data = _request_raise(
            client.post(
                f"/api/knowledge-bases/{kb_id}/search",
                json={"query": "OpenVINO GPU 配置", "top_k": top_k, "version_label": "v2"},
            ),
            "search_by_version_label",
        )
        data_items = search_data.get("data") if isinstance(search_data.get("data"), list) else []
        first = data_items[0] if data_items else {}
        report["steps"]["search"] = {"count": len(data_items), "first": first, "response": search_data}
        _check(len(data_items) > 0, "version_label 检索返回结果", failures)
        _check(bool(_safe_get(first, "version_id")), "检索结果包含 version_id", failures)
        _check(bool(_safe_get(first, "document_id")), "检索结果包含 document_id", failures)
        _check(bool(_safe_get(first, "chunk_id")), "检索结果包含 chunk_id", failures)

        _print_step("5. 图谱检索")
        graph_data = _request_raise(
            client.post(
                f"/api/knowledge-bases/{kb_id}/graph/search",
                json={"query": "Intel 开发了什么", "top_k": top_k, "version_id": version_id},
            ),
            "graph_search",
        )
        graph_items = graph_data.get("data") if isinstance(graph_data.get("data"), list) else []
        gfirst = graph_items[0] if graph_items else {}
        report["steps"]["graph_search"] = {"count": len(graph_items), "first": gfirst, "response": graph_data}
        _check(len(graph_items) > 0, "图谱检索返回关系", failures)
        _check(bool(_safe_get(gfirst, "source_entity")), "图谱结果包含 source_entity", failures)
        _check(bool(_safe_get(gfirst, "relation")), "图谱结果包含 relation", failures)
        _check(bool(_safe_get(gfirst, "target_entity")), "图谱结果包含 target_entity", failures)

        _print_step("6. reindex（内容不变应跳过）")
        reindex_data = _request_raise(
            client.post(f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/reindex"),
            "reindex_document",
        )
        message = str(reindex_data.get("message", ""))
        report["steps"]["reindex"] = {"message": message, "response": reindex_data}
        _check("Skipped re-indexing" in message, "reindex 在内容不变时返回跳过", failures)

    ok = len(failures) == 0
    report["ok"] = ok
    report["failures"] = failures
    report["base_url"] = base
    report["embedding_model_id"] = embedding_model_id

    print("\n[结果]")
    if ok:
        print("  PASS - 验收通过")
    else:
        print("  FAIL - 存在失败项")
        for item in failures:
            print(f"    - {item}")

    if output_file.strip():
        out = Path(output_file).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告已写入: {out}")

    return 0 if ok else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库/RAG 一键验收冒烟脚本")
    parser.add_argument("--base-url", default="http://localhost:8000", help="后端 base URL")
    parser.add_argument("--embedding-model-id", required=True, help="用于创建知识库的 embedding 模型 ID")
    parser.add_argument("--api-key", default="", help="可选：X-Api-Key")
    parser.add_argument("--top-k", type=int, default=5, help="检索 top_k")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP 超时秒数")
    parser.add_argument("--output-file", default="", help="可选：输出 JSON 报告路径")
    args = parser.parse_args()

    if args.top_k <= 0:
        print("--top-k 必须 > 0")
        return 1

    try:
        return run_smoke(
            base_url=str(args.base_url),
            embedding_model_id=str(args.embedding_model_id),
            api_key=str(args.api_key),
            top_k=int(args.top_k),
            timeout_seconds=float(args.timeout_seconds),
            output_file=str(args.output_file),
        )
    except Exception as e:
        print(f"[异常] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

