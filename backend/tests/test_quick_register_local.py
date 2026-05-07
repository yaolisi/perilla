"""quick_register_local：目录生成与 model.json 写入（扫描步骤 mock）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.models.quick_register_local as qr


def test_sanitize_model_id() -> None:
    assert qr.sanitize_model_id("  foo/bar  ") == "foo-bar"
    assert qr.sanitize_model_id("") == "model"


@pytest.mark.asyncio
async def test_run_quick_register_llm_gguf_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(qr, "_models_base_dir", lambda: tmp_path)
    scanned = False

    async def fake_scan() -> None:
        nonlocal scanned
        scanned = True

    monkeypatch.setattr(qr, "_run_local_scan", fake_scan)

    src = tmp_path / "weights.gguf"
    src.write_bytes(b"x")

    info = await qr.run_quick_register_llm_gguf(
        src,
        model_id="test-llm",
        name="Test LLM",
        copy_mode="copy",
    )

    assert scanned
    assert info["model_id"] == "test-llm"
    assert info["registry_id"] == "local:test-llm"

    dest_dir = tmp_path / "llm" / "test-llm"
    assert (dest_dir / "weights.gguf").is_file()
    mf = dest_dir / "model.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data["model_type"] == "llm"
    assert data["runtime"] == "llama.cpp"
    assert data["path"] == "weights.gguf"


@pytest.mark.asyncio
async def test_run_quick_register_embedding_onnx_with_tokenizer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(qr, "_models_base_dir", lambda: tmp_path)

    async def fake_scan() -> None:
        pass

    monkeypatch.setattr(qr, "_run_local_scan", fake_scan)

    onnx_f = tmp_path / "m.onnx"
    onnx_f.write_bytes(b"onnx")
    tok_f = tmp_path / "tokenizer.json"
    tok_f.write_bytes(b"{}")

    info = await qr.run_quick_register_embedding_onnx(
        onnx_f,
        model_id="emb1",
        name="Emb",
        copy_mode="copy",
        embedding_dim=768,
        tokenizer_path=tok_f,
    )

    assert info["registry_id"] == "local:emb1"
    dest = tmp_path / "embedding" / "emb1"
    assert (dest / "m.onnx").is_file()
    assert (dest / "tokenizer.json").is_file()
    data = json.loads((dest / "model.json").read_text(encoding="utf-8"))
    assert data["model_type"] == "embedding"
    assert data["metadata"]["embedding_dim"] == 768
    assert data["metadata"]["tokenizer"] == "tokenizer.json"


@pytest.mark.asyncio
async def test_run_quick_register_vlm_gguf_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(qr, "_models_base_dir", lambda: tmp_path)

    async def fake_scan() -> None:
        pass

    monkeypatch.setattr(qr, "_run_local_scan", fake_scan)

    main_f = tmp_path / "main.gguf"
    mp_f = tmp_path / "vision-mmproj.gguf"
    main_f.write_bytes(b"m")
    mp_f.write_bytes(b"p")

    info = await qr.run_quick_register_vlm_gguf(
        main_f,
        mp_f,
        model_id="vlm-quick",
        name="VLM Quick",
        copy_mode="copy",
        vlm_family="llava-1.5",
    )

    assert info["registry_id"] == "local:vlm-quick"
    dest = tmp_path / "vlm" / "vlm-quick"
    assert (dest / "main.gguf").is_file()
    assert (dest / "vision-mmproj.gguf").is_file()
    data = json.loads((dest / "model.json").read_text(encoding="utf-8"))
    assert data["model_type"] == "vlm"
    assert data["capabilities"] == ["chat", "vision"]
    assert data["metadata"]["mmproj_path"] == "vision-mmproj.gguf"
    assert data["metadata"]["vlm_family"] == "llava-1.5"
