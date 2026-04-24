"""VLM API 辅助逻辑单元测试（不启动完整 HTTP 服务、不跑真实推理）。"""

from types import SimpleNamespace

from api.vlm import (
    VLMGenerateResponse,
    _routing_submeta_for_persist_vlm,
    _vlm_messages_for_model_selection,
)
from core.models.selector import ModelSelector


def test_vlm_messages_for_model_selection_includes_multimodal_image_url() -> None:
    msgs = _vlm_messages_for_model_selection(user_prompt="hello")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    assert isinstance(content, list)
    types = [c.get("type") for c in content if isinstance(c, dict)]
    assert "text" in types
    assert "image_url" in types


def test_vlm_messages_trigger_selector_image_detection() -> None:
    """保证 VLM 选模在 auto 路径上会被 ModelSelector 视为含图（needs_vision）。"""
    sel = ModelSelector()
    plain = [{"role": "user", "content": "no image"}]
    assert sel._has_image_content(plain) is False

    vlm_msgs = _vlm_messages_for_model_selection(user_prompt="with image")
    assert sel._has_image_content(vlm_msgs) is True


def test_routing_submeta_for_persist_vlm_missing_state() -> None:
    req = SimpleNamespace()
    req.state = SimpleNamespace()
    assert _routing_submeta_for_persist_vlm(req) is None  # type: ignore[arg-type]


def test_routing_submeta_for_persist_vlm_not_dict() -> None:
    req = SimpleNamespace()
    req.state = SimpleNamespace()
    req.state.chat_routing_metadata = "not-a-dict"
    assert _routing_submeta_for_persist_vlm(req) is None  # type: ignore[arg-type]


def test_routing_submeta_for_persist_vlm_empty_strings() -> None:
    req = SimpleNamespace()
    req.state = SimpleNamespace()
    req.state.chat_routing_metadata = {"resolved_model": "m", "resolved_via": ""}
    assert _routing_submeta_for_persist_vlm(req) is None  # type: ignore[arg-type]


def test_routing_submeta_for_persist_vlm_ok() -> None:
    req = SimpleNamespace()
    req.state = SimpleNamespace()
    req.state.chat_routing_metadata = {"resolved_model": "a", "resolved_via": "direct"}
    assert _routing_submeta_for_persist_vlm(req) == {  # type: ignore[arg-type]
        "resolved_model": "a",
        "resolved_via": "direct",
    }


def test_vlm_generate_response_model_metadata_optional() -> None:
    """OpenAPI/JSON 契约：与 chat 对齐的可选 metadata。"""
    with_meta = VLMGenerateResponse(
        model="m1",
        text="out",
        usage={"prompt_tokens": 1, "completion_tokens": 1},
        metadata={"resolved_model": "m1", "resolved_via": "selector"},
    )
    d = with_meta.model_dump()
    assert d["model"] == "m1"
    assert d["text"] == "out"
    assert d["metadata"] == {"resolved_model": "m1", "resolved_via": "selector"}

    no_meta = VLMGenerateResponse(model="m1", text="out")
    assert no_meta.model_dump()["metadata"] is None
