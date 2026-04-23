"""
Skill v1 FastAPI 接口：创建、列表、获取、执行。
"""
from typing import Any, Dict, List, Optional, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.errors import raise_api_error
from core.skills import create_skill, get_skill, list_skills, SkillExecutor, update_skill, delete_skill
from core.skills.models import SkillType
from core.skills.registry import SkillRegistry
from core.security.deps import require_authenticated_platform_admin
from core.security.skill_policy import get_blocked_skills

router = APIRouter(
    prefix="/api/skills",
    tags=["skills"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)
MSG_SKILL_NOT_FOUND = "Skill not found"


class CreateSkillBody(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    category: str = ""
    type: SkillType = "prompt"
    input_schema: Optional[Dict[str, Any]] = None
    definition: Optional[Dict[str, Any]] = None
    enabled: bool = True


class UpdateSkillBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    category: Optional[str] = None
    type: Optional[SkillType] = None
    input_schema: Optional[Dict[str, Any]] = None
    definition: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class ExecuteSkillBody(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)


@router.post("")
async def api_create_skill(body: CreateSkillBody) -> Dict[str, Any]:
    """创建 Skill。"""
    skill = create_skill(
        name=body.name,
        description=body.description,
        category=body.category,
        type=body.type,
        definition=body.definition,
        input_schema=body.input_schema,
        enabled=body.enabled,
    )
    if not skill:
        raise_api_error(status_code=500, code="skill_create_failed", message="Failed to create skill")
    assert skill is not None
    SkillRegistry.register(cast(Any, skill))
    return cast(Dict[str, Any], skill.to_dict())


@router.get("")
async def api_list_skills() -> Dict[str, Any]:
    """列出所有 Skill。"""
    skills = list_skills(enabled_only=False)
    return {
        "object": "list",
        "data": [s.to_dict() for s in skills],
    }


@router.get("/{skill_id}")
async def api_get_skill(skill_id: str) -> Dict[str, Any]:
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
    return cast(Dict[str, Any], skill.to_dict())


@router.put("/{skill_id}")
async def api_update_skill(skill_id: str, body: UpdateSkillBody) -> Dict[str, Any]:
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
        definition=body.definition,
        input_schema=body.input_schema,
        enabled=body.enabled,
    )
    if not updated:
        raise_api_error(status_code=500, code="skill_update_failed", message="Failed to update skill")
    assert updated is not None
    return cast(Dict[str, Any], updated.to_dict())


@router.delete("/{skill_id}")
async def api_delete_skill(skill_id: str) -> Dict[str, Any]:
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
    return {"status": "ok"}


@router.post("/{skill_id}/execute")
async def api_execute_skill(skill_id: str, body: ExecuteSkillBody) -> Dict[str, Any]:
    """执行 Skill（供 Agent Runtime 使用）。返回 type + output（及可选的 error / prompt）。"""
    from core.skills.contract import SkillExecutionRequest
    
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
        input=body.inputs,
        trace_id=f"api_{skill_id}",
        caller_id="api",
    )
    
    # 使用 SkillExecutor 统一入口执行
    response = await SkillExecutor.execute(request)
    
    # 转换响应格式
    if response.status == "success":
        return {"type": "success", "output": response.output}
    elif response.status == "timeout":
        error = response.error if isinstance(response.error, dict) else {}
        return {"type": "error", "error": error.get("message", "Timeout")}
    else:
        error = response.error if isinstance(response.error, dict) else {}
        return {"type": "error", "error": error.get("message", "Unknown error")}
