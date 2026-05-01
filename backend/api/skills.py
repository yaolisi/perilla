"""
Skill v1 FastAPI 接口：创建、列表、获取、执行。
"""
from typing import List, Literal, Optional, Union

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from api.errors import raise_api_error
from middleware.user_context import get_user_id
from core.skills import create_skill, get_skill, list_skills, SkillExecutor, update_skill, delete_skill
from core.skills.models import Skill, SkillType
from core.skills.registry import SkillRegistry
from core.security.deps import require_authenticated_platform_admin
from core.security.skill_policy import get_blocked_skills

router = APIRouter(
    prefix="/api/skills",
    tags=["skills"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)
MSG_SKILL_NOT_FOUND = "Skill not found"


class SkillV1JsonMap(BaseModel):
    """Skill v1 API 中的 definition / schema / 执行 inputs 等自由 JSON 对象。"""

    model_config = ConfigDict(extra="allow")


class SkillV1ApiRecord(BaseModel):
    """与 `Skill.to_dict()` 对齐的 API 展示模型（v1 存储）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    category: str
    type: SkillType
    definition: SkillV1JsonMap
    input_schema: SkillV1JsonMap
    enabled: bool
    is_mcp: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SkillListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    data: List[SkillV1ApiRecord]


class SkillDeleteApiResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class SkillExecuteSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["success"] = "success"
    output: SkillV1JsonMap


class SkillExecuteErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["error"] = "error"
    error: str


SkillExecuteApiResponse = Union[SkillExecuteSuccessResponse, SkillExecuteErrorResponse]


def _skill_record(skill: Skill) -> SkillV1ApiRecord:
    return SkillV1ApiRecord.model_validate(skill.to_dict())


class CreateSkillBody(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    category: str = ""
    type: SkillType = "prompt"
    input_schema: Optional[SkillV1JsonMap] = None
    definition: Optional[SkillV1JsonMap] = None
    enabled: bool = True


class UpdateSkillBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    category: Optional[str] = None
    type: Optional[SkillType] = None
    input_schema: Optional[SkillV1JsonMap] = None
    definition: Optional[SkillV1JsonMap] = None
    enabled: Optional[bool] = None


class ExecuteSkillBody(BaseModel):
    inputs: SkillV1JsonMap = Field(default_factory=SkillV1JsonMap)


@router.post("")
async def api_create_skill(body: CreateSkillBody) -> SkillV1ApiRecord:
    """创建 Skill。"""
    skill = create_skill(
        name=body.name,
        description=body.description,
        category=body.category,
        type=body.type,
        definition=body.definition.model_dump(mode="json") if body.definition is not None else None,
        input_schema=body.input_schema.model_dump(mode="json") if body.input_schema is not None else None,
        enabled=body.enabled,
    )
    if not skill:
        raise_api_error(status_code=500, code="skill_create_failed", message="Failed to create skill")
    assert skill is not None
    SkillRegistry.register(skill)
    return _skill_record(skill)


@router.get("")
async def api_list_skills() -> SkillListResponse:
    """列出所有 Skill。"""
    skills = list_skills(enabled_only=False)
    return SkillListResponse(data=[_skill_record(s) for s in skills])


@router.get("/{skill_id}")
async def api_get_skill(skill_id: str) -> SkillV1ApiRecord:
    """获取单个 Skill。"""
    skill = get_skill(skill_id)
    if not skill:
        raise_api_error(
            status_code=404,
            code="skill_not_found",
            message=MSG_SKILL_NOT_FOUND,
            details={"skill_id": skill_id},
        )
    assert skill is not None
    return _skill_record(skill)


@router.put("/{skill_id}")
async def api_update_skill(skill_id: str, body: UpdateSkillBody) -> SkillV1ApiRecord:
    """更新 Skill。"""
    if skill_id.startswith("builtin_"):
        raise_api_error(
            status_code=400,
            code="skill_builtin_immutable",
            message="Cannot update built-in skill",
            details={"skill_id": skill_id},
        )
    skill = get_skill(skill_id)
    if not skill:
        raise_api_error(
            status_code=404,
            code="skill_not_found",
            message=MSG_SKILL_NOT_FOUND,
            details={"skill_id": skill_id},
        )
    updated = update_skill(
        skill_id,
        name=body.name,
        description=body.description,
        category=body.category,
        type=body.type,
        definition=body.definition.model_dump(mode="json") if body.definition is not None else None,
        input_schema=body.input_schema.model_dump(mode="json") if body.input_schema is not None else None,
        enabled=body.enabled,
    )
    if not updated:
        raise_api_error(status_code=500, code="skill_update_failed", message="Failed to update skill")
    assert updated is not None
    return _skill_record(updated)


@router.delete("/{skill_id}")
async def api_delete_skill(skill_id: str) -> SkillDeleteApiResponse:
    """删除 Skill。内置 builtin_* 不可删除。"""
    if skill_id.startswith("builtin_"):
        raise_api_error(
            status_code=400,
            code="skill_builtin_immutable",
            message="Cannot delete built-in skill",
            details={"skill_id": skill_id},
        )
    if not delete_skill(skill_id):
        raise_api_error(
            status_code=404,
            code="skill_not_found",
            message=MSG_SKILL_NOT_FOUND,
            details={"skill_id": skill_id},
        )
    return SkillDeleteApiResponse()


@router.post("/{skill_id}/execute")
async def api_execute_skill(
    request: Request, skill_id: str, body: ExecuteSkillBody
) -> SkillExecuteApiResponse:
    """执行 Skill（供 Agent Runtime 使用）。返回 type + output（及可选的 error / prompt）。"""
    from core.skills.contract import SkillExecutionRequest

    user_id = get_user_id(request)
    
    skill = get_skill(skill_id)
    if not skill:
        raise_api_error(
            status_code=404,
            code="skill_not_found",
            message=MSG_SKILL_NOT_FOUND,
            details={"skill_id": skill_id},
        )

    blocked = get_blocked_skills([skill_id])
    if blocked:
        raise_api_error(
            status_code=403,
            code="skill_execution_blocked",
            message=f"dangerous skill execution blocked by server policy: {blocked[0]}",
            details={"skill_id": skill_id, "blocked_skill": blocked[0]},
        )
    
    # 构建执行请求
    request = SkillExecutionRequest(
        skill_id=skill_id,
        input=body.inputs.model_dump(mode="json"),
        trace_id=f"api_{skill_id}",
        caller_id="api",
        metadata={"user_id": user_id} if user_id else {},
    )
    
    # 使用 SkillExecutor 统一入口执行
    response = await SkillExecutor.execute(request)
    
    # 转换响应格式
    if response.status == "success":
        raw_out = response.output
        payload = raw_out if isinstance(raw_out, dict) else {}
        return SkillExecuteSuccessResponse(output=SkillV1JsonMap.model_validate(payload))
    elif response.status == "timeout":
        error = response.error if isinstance(response.error, dict) else {}
        return SkillExecuteErrorResponse(error=str(error.get("message", "Timeout")))
    else:
        error = response.error if isinstance(response.error, dict) else {}
        return SkillExecuteErrorResponse(error=str(error.get("message", "Unknown error")))
