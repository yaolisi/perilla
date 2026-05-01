# vLLM 与 TensorRT-LLM 接入说明

本项目 **以 FastAPI 推理网关为中心**：新增后端时，优先采用 **OpenAI 兼容 HTTP API**，由现有 **OpenAI 兼容运行时 / Agent** 转发请求，避免在业务代码中嵌入各厂商私有 Python SDK（除非你有明确的本地集成需求）。

## 1. vLLM（推荐路径）

vLLM 通常以独立进程提供 **OpenAI Chat Completions 兼容服务**（路径多为 `/v1/chat/completions`）。

**集成思路：**

1. 在本机或同网段启动 vLLM，绑定已知 `base_url`（例如 `http://127.0.0.1:8001/v1`）。
2. 在 perilla 的模型描述 / 提供方配置中，将该模型声明为 **OpenAI 兼容远端**（具体字段名以你环境中的 `ModelDescriptor`、配置文件为准：`runtime` / `base_url` / `api_key`）。
3. 前端只调用 perilla 网关；网关将请求路由到 vLLM 服务。

**优点：** 流式（SSE）、并发与 continuous batching 由 vLLM 负责；网关侧保持统一鉴权、审计与限流。

**注意：** 默认仍遵循「本地优先 / 不外传」假设；若 vLLM 跑在另一台内网机器，请在网络与安全策略中显式放行。

## 2. NVIDIA TensorRT-LLM

TensorRT-LLM 常见用法同样是启动 **HTTP 服务**（具体入口随版本变化，请以当前 NVIDIA 文档为准）。只要暴露 **与 OpenAI 兼容** 的 Chat/Completion 接口，即可按与 vLLM **相同方式** 在网关中登记为远端模型。

**典型关注点：**

- GPU 驱动、CUDA 与 TensorRT-LLM 版本矩阵。
- 引擎构建时的序列长度、batch、精度（FP16/BF16/INT4）与显存占用。
- 若仅提供 gRPC 或非 OpenAI 形态 API，需要在网关侧新增专用 Adapter（工作量大，属于定制开发）。

## 3. Torch 本地 VLM 流式说明（生产运维）

对 **内置 Torch VLM**（`TorchVLMRuntime`），流式输出使用 Hugging Face `TextIteratorStreamer` 与后台线程中的 `model.generate`，经有界/无界队列桥接到 asyncio（见 `TorchVLMRuntime.generate_stream`）。

**行为与限制：**

- **首包延迟**：显著优于「整段 non-stream再推送」；吞吐仍受 GPU、推理队列并发度与模型实例管理约束。
- **无法强制中断 CUDA**：客户端断开或 asyncio 取消 **不能保证** 立刻结束 GPU 上的 `generate`；后台线程在超时 join 后仍会记录结构化日志（`TorchStreamHF` / `generation_thread_join_timeout`）。这与多数本地 HF 栈一致。
- **同步线程异常**：适配器或 `model.generate` 抛错会通过队列传到 SSE 消费者并冒泡为请求错误，避免无声失败。
- **OOM / 慢客户端**：可选 **有界 chunk 队列**（丢弃最旧 chunk 以腾出槽位给错误/结束标记），防止极端慢消费阻塞整条链路；默认 **0 = 无限队列**（依赖下游消费速度与单次生成长度）。

**可调参数（`config.settings` / 系统设置覆盖，camelCase）：**

| 键名 | 含义 |
|------|------|
| `torchStreamThreadJoinTimeoutSec` | HF `generate` 线程 join 超时（秒），超时仍存活记 error 级结构化日志 |
| `torchStreamChunkQueueMax` | 异步桥接队列深度；**0** 表示不限制 |

控制台：**设置 → Runtime** 中「Torch VLM 流式（服务端）」卡片与上述键同步（保存后写入系统配置）。

**Prometheus：** 流式请求被 asyncio 取消（如客户端断开导致上游取消）时，网关调用 `observe_inference_cancelled`，递增 `perilla_inference_cancelled_total`，并释放 `perilla_inference_requests_in_flight{operation="stream"}`，**不**计入 `perilla_inference_errors_total`。

**Chat 主路径：** `UnifiedModelAgent` 对流式/非流式的 **`asyncio.CancelledError`** 单独记录结构化事件（`inference_stream_cancelled` / `inference_cancelled`），**不**调用运行时 `record_request_failed`，避免把取消当成推理失败。

**SSE 生成器：** `api/chat.py` 中 `_stream_event_generator` 对 **`asyncio.CancelledError`** 记 **`chat_stream_cancelled`**；`finally` 中尽力 **`resume_store.finish(stream_id)`**，避免启用断点续传时会话长期卡在 `finished=False`。

代码入口：`backend/core/runtimes/torch/stream_hf.py`、`backend/core/runtimes/torch/torch_vlm_runtime.py`、`backend/core/system/runtime_settings.py`（`get_torch_stream_*`）、`backend/core/inference/gateway/inference_gateway.py`、`backend/core/agents/unified_agent.py`。

## 4. 小结

| 后端 | 推荐集成方式 |
|------|----------------|
| vLLM | OpenAI 兼容 HTTP → 网关 OpenAI 兼容运行时 |
| TensorRT-LLM | OpenAI 兼容 HTTP（若可用）→ 同上 |
| 本地 Torch VLM | 内置 Runtime + `generate_stream` |

若你需要 **固定配置文件片段**（YAML/JSON 示例），请以当前仓库中 `ModelDescriptor` 与部署文档为准进行拷贝修改，避免跨版本字段名不一致。
