"""后端镜像入口须使用 python main.py，以便 Settings→uvicorn.run 的生产参数（并发、代理头等）生效。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path


@pytest.mark.requires_monorepo
def test_backend_dockerfile_cmd_uses_python_main() -> None:
    p = repo_path("docker/backend.Dockerfile")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert 'CMD ["python", "main.py"]' in text
