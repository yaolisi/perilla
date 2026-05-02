"""
多模态能力在本工程中的落点（入口索引 + 类型再导出，不重复实现业务逻辑）。

**为何不放 ``core/runtimes/multimodal/`` 下三个独立大文件**  
运行时实现已在 ``core.runtimes``（VLM、perception、各后端适配）；文档解析已在
``core.knowledge.document_parser``。再建平行模块易造成第二套 Parser、与
``RuntimeFactory`` 分叉。

**分层落点（扩展时请改这些位置，而非新建同名模块）**

1. **网关与多模态策略**  
   ``core.inference.providers.provider_runtime_adapter.ProviderRuntimeAdapter``（带图请求与模型 vision 能力校验）、  
   ``core.inference.gateway.inference_gateway.InferenceGateway``（image_url 大小与 data URL 策略）。

2. **VLM 推理与统一类型**  
   ``core.runtimes.vlm_runtime``、``core.runtimes.vlm_types``；工厂见 ``core.runtimes.factory.RuntimeFactory``  
   （``torch`` / ``llama.cpp`` 等 VLM 构建器）。具体实现：``llama_vlm_runtime``、``torch/torch_vlm_runtime`` 等。

3. **计算机视觉工具链（非生成式「理解」）**  
   ``core.runtimes.perception``、``core.tools.yolo``、内置 vision 插件。

4. **Agent 侧：上传、技能路由、workspace 图像**  
   ``core.agent_runtime``、``api.agents``（如 ``builtin_vlm.generate``、``vision.detect_objects`` 相关提示）。

5. **文档 → 文本（RAG 索引）**  
   仅维护 ``core.knowledge.document_parser.DocumentParser``。扫描件/版式/表格等「复杂文档」应在该模块内  
   增量扩展（如 OCR、版面），索引管线 ``core.knowledge.indexer`` 自动受益。

**推荐演进顺序（与本仓库现状匹配）**

- P0：在 ``document_parser`` 上增强失败场景（扫描 PDF 等），与网关侧附件策略一致。  
- P1：会话多图、VLM 输出与 RAG 的 chunk 策略在插件/Agent 层显式化（复用现有 RAG 与 Tool）。  
- P2：若需独立「多模态编排服务」，在 ``core.multimodal`` 下仅增加**薄封装**（调用上述模块），避免复制 Runtime。

再导出以下符号，供新代码 ``from core.multimodal import ...`` 单点引用。
"""

from __future__ import annotations

from core.knowledge.document_parser import DocumentParser, ParsedDocument, ParsedPage
from core.runtimes.vlm_types import (
    ImageInput,
    VLMGenerationConfig,
    VLMRequest,
    VLMResponse,
)

__all__ = [
    "DocumentParser",
    "ParsedDocument",
    "ParsedPage",
    "ImageInput",
    "VLMGenerationConfig",
    "VLMRequest",
    "VLMResponse",
]
