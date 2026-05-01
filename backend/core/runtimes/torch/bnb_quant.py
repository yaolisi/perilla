"""
BitsAndBytes 量化加载辅助（Torch VLM）

仅在 CUDA + 显式 manifest 开关时启用；非 CUDA 或未安装 bitsandbytes 时静默跳过。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from log import logger


def try_bitsandbytes_config(
    options: Dict[str, Any],
    *,
    resolved_device: str,
) -> Tuple[Optional[Any], bool]:
    """
    构建 transformers BitsAndBytesConfig；若应使用 bitsandbytes 加载则返回 (config, True)。

    第二项为 True 时调用方应使用 device_map=\"auto\" 且不要在加载后再对整个模型 .to(device)。
    """
    if (resolved_device or "").lower() != "cuda":
        if bool(options.get("load_in_4bit")) or bool(options.get("load_in_8bit")):
            logger.warning(
                "[Torch VLM] load_in_4bit/load_in_8bit requested but device=%s; quantization skipped",
                resolved_device,
            )
        return None, False

    load_4 = bool(options.get("load_in_4bit"))
    load_8 = bool(options.get("load_in_8bit"))
    if not load_4 and not load_8:
        return None, False

    try:
        import torch
        from transformers import BitsAndBytesConfig
    except Exception as exc:
        logger.warning("[Torch VLM] bitsandbytes/transformers unavailable: %s", exc)
        return None, False

    if load_4 and load_8:
        load_8 = False

    compute_dtype_str = (options.get("bnb_4bit_compute_dtype") or "float16").lower()
    compute_dtype = getattr(torch, compute_dtype_str, torch.float16)
    quant_type = str(options.get("bnb_4bit_quant_type") or "nf4")

    cfg = BitsAndBytesConfig(
        load_in_4bit=load_4,
        load_in_8bit=load_8,
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_quant_type=quant_type,
    )
    return cfg, True
