from typing import Any, Dict, List, Optional

def create_input_schema(
    properties: Dict[str, Any], required: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Helper to create a standard JSON Schema for tool inputs."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or []
    }
