import sqlite3
from typing import Any, Dict, List, cast
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError

class SqlQueryTool(Tool):
    @property
    def name(self) -> str:
        return "sql.query"

    @property
    def description(self) -> str:
        return "Execute a SQL SELECT query against a database."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return cast(
            Dict[str, Any],
            create_input_schema({
                "query": {"type": "string", "description": "The SQL SELECT query to execute."},
                "db_path": {"type": "string", "description": "Path to the SQLite database file."}
            }, required=["query", "db_path"]),
        )

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "array", "items": {"type": "object"}}

    @property
    def required_permissions(self) -> List[str]:
        return ["sql.query"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "SQL Query",
            "icon": "Database",
            "category": "sql",
            "permissions_hint": [
                {"key": "sql.query", "label": "Read-only SQL queries (SELECT only)."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        query_raw = input_data.get("query")
        db_path_raw = input_data.get("db_path")
        query = query_raw if isinstance(query_raw, str) else ""
        db_path = db_path_raw if isinstance(db_path_raw, str) else ""
        
        if not query or not query.strip().upper().startswith("SELECT"):
            return ToolResult(success=False, data=None, error="Only SELECT queries are allowed.")
        if not db_path:
            return ToolResult(success=False, data=None, error="db_path is required.")

        try:
            target_abs = resolve_in_workspace(workspace=ctx.workspace, path=db_path)
        except WorkspacePathError as e:
            return ToolResult(success=False, data=None, error=str(e))

        if not target_abs.exists():
            return ToolResult(success=False, data=None, error=f"Database not found: {db_path}")

        try:
            conn = sqlite3.connect(f"file:{str(target_abs)}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute(query)
            
            columns = [description[0] for description in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            conn.close()
            return ToolResult(success=True, data=rows)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
