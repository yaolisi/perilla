"""
从向导生成最小 model.json 并完成本地模型目录布局（含可选 symlink / 复制权重）。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Literal, Optional

from log import logger


def sanitize_model_id(raw: str) -> str:
    s = raw.strip()
    if not s:
        return "model"
    s = re.sub(r"[^a-zA-Z0-9._-]", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if len(s) > 80:
        s = s[:80].rstrip("-")
    return s or "model"


def _models_base_dir() -> Path:
    from config.settings import settings
    from core.system.settings_store import get_system_settings_store

    store = get_system_settings_store()
    configured_dir = store.get_setting("dataDirectory") or settings.local_model_directory
    return Path(configured_dir).expanduser().resolve()


def _link_or_copy_into_dir(
    src: Path,
    dest_dir: Path,
    copy_mode: Literal["symlink", "copy"],
) -> Path:
    """将单个文件放入 dest_dir，返回目标文件路径。"""
    dest_file = dest_dir / src.name
    if dest_file.exists():
        raise ValueError(f"目标文件已存在：{dest_file}")
    if copy_mode == "symlink":
        try:
            dest_file.symlink_to(src.resolve())
        except OSError as e:
            logger.warning("[quick_register_local] symlink failed (%s), fallback to copy", e)
            shutil.copy2(src, dest_file)
    else:
        shutil.copy2(src, dest_file)
    return dest_file


async def _run_local_scan() -> None:
    from core.models.scanner.local import LocalScanner

    await LocalScanner().scan()


def quick_register_llm_gguf(
    source_path: Path,
    *,
    model_id: Optional[str],
    name: Optional[str],
    copy_mode: Literal["symlink", "copy"],
) -> dict[str, Any]:
    """
    在 <data>/llm/<model_id>/ 下写入 model.json，并将权重以 symlink 或复制方式放入同目录。
    """
    src = source_path.expanduser().resolve()
    if not src.is_file():
        raise ValueError("源路径必须是已存在的文件")
    if src.suffix.lower() != ".gguf":
        raise ValueError("请选择 .gguf 权重文件")

    mid = sanitize_model_id(model_id or src.stem)
    base = _models_base_dir()
    dest_dir = base / "llm" / mid
    if dest_dir.exists():
        raise ValueError(f"模型目录已存在，请更换「模型 ID」或删除目录后重试：{dest_dir}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = _link_or_copy_into_dir(src, dest_dir, copy_mode)

    display_name = (name or "").strip() or mid
    manifest: dict[str, Any] = {
        "model_id": mid,
        "name": display_name,
        "model_type": "llm",
        "runtime": "llama.cpp",
        "format": "gguf",
        "path": dest_file.name,
        "capabilities": ["chat"],
        "description": f"Local LLM (quick register): {mid}",
        "metadata": {
            "n_ctx": 8192,
            "n_gpu_layers": -1,
        },
    }
    manifest_path = dest_dir / "model.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "model_id": mid,
        "registry_id": f"local:{mid}",
        "manifest_path": str(manifest_path),
        "dest_dir": str(dest_dir),
    }


def quick_register_embedding_onnx(
    source_path: Path,
    *,
    model_id: Optional[str],
    name: Optional[str],
    copy_mode: Literal["symlink", "copy"],
    embedding_dim: int,
    tokenizer_path: Optional[Path],
) -> dict[str, Any]:
    """在 <data>/embedding/<model_id>/ 下写入 ONNX embedding 的 model.json。"""
    src = source_path.expanduser().resolve()
    if not src.is_file():
        raise ValueError("源路径必须是已存在的文件")
    if src.suffix.lower() != ".onnx":
        raise ValueError("请选择 .onnx 模型文件")

    tok: Optional[Path] = None
    if tokenizer_path is not None:
        tok = tokenizer_path.expanduser().resolve()
        if not tok.is_file():
            raise ValueError("分词器路径必须是已存在的文件")

    mid = sanitize_model_id(model_id or src.stem)
    base = _models_base_dir()
    dest_dir = base / "embedding" / mid
    if dest_dir.exists():
        raise ValueError(f"模型目录已存在，请更换「模型 ID」或删除目录后重试：{dest_dir}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    onnx_dest = _link_or_copy_into_dir(src, dest_dir, copy_mode)

    metadata: dict[str, Any] = {
        "embedding_dim": int(embedding_dim),
    }
    if tok is not None:
        tok_dest = _link_or_copy_into_dir(tok, dest_dir, copy_mode)
        metadata["tokenizer"] = tok_dest.name

    display_name = (name or "").strip() or mid
    manifest: dict[str, Any] = {
        "model_id": mid,
        "name": display_name,
        "model_type": "embedding",
        "runtime": "onnx",
        "path": onnx_dest.name,
        "capabilities": ["embedding"],
        "description": f"Local embedding (quick register): {mid}",
        "metadata": metadata,
    }
    manifest_path = dest_dir / "model.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "model_id": mid,
        "registry_id": f"local:{mid}",
        "manifest_path": str(manifest_path),
        "dest_dir": str(dest_dir),
    }


def quick_register_vlm_gguf(
    main_gguf_path: Path,
    mmproj_gguf_path: Path,
    *,
    model_id: Optional[str],
    name: Optional[str],
    copy_mode: Literal["symlink", "copy"],
    vlm_family: Optional[str],
) -> dict[str, Any]:
    """
    在 <data>/vlm/<model_id>/ 下写入 llama.cpp VLM 的 model.json（主 GGUF + mmproj GGUF）。
    """
    main_src = main_gguf_path.expanduser().resolve()
    mmproj_src = mmproj_gguf_path.expanduser().resolve()
    if not main_src.is_file() or not mmproj_src.is_file():
        raise ValueError("主模型与 mmproj 路径必须是已存在的文件")
    if main_src.suffix.lower() != ".gguf" or mmproj_src.suffix.lower() != ".gguf":
        raise ValueError("主模型与 mmproj 均须为 .gguf 文件")
    if main_src == mmproj_src:
        raise ValueError("主模型与 mmproj 不能为同一文件")

    mid = sanitize_model_id(model_id or main_src.stem)
    base = _models_base_dir()
    dest_dir = base / "vlm" / mid
    if dest_dir.exists():
        raise ValueError(f"模型目录已存在，请更换「模型 ID」或删除目录后重试：{dest_dir}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    main_dest = _link_or_copy_into_dir(main_src, dest_dir, copy_mode)
    if main_dest.name == mmproj_src.name:
        raise ValueError(
            "主模型与 mmproj 文件名相同，无法放入同一目录；请将其中一个改名后再注册。"
        )
    mmproj_dest = _link_or_copy_into_dir(mmproj_src, dest_dir, copy_mode)

    family = (vlm_family or "").strip() or "llava-1.5"
    display_name = (name or "").strip() or mid
    manifest: dict[str, Any] = {
        "model_id": mid,
        "name": display_name,
        "model_type": "vlm",
        "runtime": "llama.cpp",
        "format": "gguf",
        "path": main_dest.name,
        "capabilities": ["chat", "vision"],
        "description": f"Local VLM llama.cpp (quick register): {mid}",
        "metadata": {
            "modality": "vlm",
            "vlm_family": family,
            "mmproj_path": mmproj_dest.name,
            "context_length": 4096,
            "n_gpu_layers": -1,
            "n_threads": 8,
        },
    }
    manifest_path = dest_dir / "model.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "model_id": mid,
        "registry_id": f"local:{mid}",
        "manifest_path": str(manifest_path),
        "dest_dir": str(dest_dir),
    }


async def run_quick_register_llm_gguf(
    source_path: Path,
    *,
    model_id: Optional[str],
    name: Optional[str],
    copy_mode: Literal["symlink", "copy"],
) -> dict[str, Any]:
    info = quick_register_llm_gguf(
        source_path,
        model_id=model_id,
        name=name,
        copy_mode=copy_mode,
    )
    await _run_local_scan()
    return info


async def run_quick_register_embedding_onnx(
    source_path: Path,
    *,
    model_id: Optional[str],
    name: Optional[str],
    copy_mode: Literal["symlink", "copy"],
    embedding_dim: int,
    tokenizer_path: Optional[Path],
) -> dict[str, Any]:
    info = quick_register_embedding_onnx(
        source_path,
        model_id=model_id,
        name=name,
        copy_mode=copy_mode,
        embedding_dim=embedding_dim,
        tokenizer_path=tokenizer_path,
    )
    await _run_local_scan()
    return info


async def run_quick_register_vlm_gguf(
    main_gguf_path: Path,
    mmproj_gguf_path: Path,
    *,
    model_id: Optional[str],
    name: Optional[str],
    copy_mode: Literal["symlink", "copy"],
    vlm_family: Optional[str],
) -> dict[str, Any]:
    info = quick_register_vlm_gguf(
        main_gguf_path,
        mmproj_gguf_path,
        model_id=model_id,
        name=name,
        copy_mode=copy_mode,
        vlm_family=vlm_family,
    )
    await _run_local_scan()
    return info
