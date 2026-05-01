"""仓库根路径解析：支持完整 monorepo 与仅含 backend 子树的拷贝跑测。

- **Monorepo**：顶层含 ``Makefile``、``backend/api`` 时，根目录为含 ``Makefile`` 的目录；
  ``repo_path("backend/scripts/foo.py")`` 指向 ``<根>/backend/scripts/foo.py``。
- **仅 backend 拷贝**：仅有 ``backend`` 内容（``api/``、``tests/``、``scripts/`` 同级）时，
  逻辑根为 **backend 目录本身**；``repo_path("backend/scripts/foo.py")`` 等价于
  ``<backend>/scripts/foo.py``。

依赖顶层 ``Makefile`` / ``scripts/pr-check.sh`` / ``.github`` / ``frontend`` 的合约测试应标
``@pytest.mark.requires_monorepo``（或在模块级 ``pytestmark``），在仅 backend 环境下自动跳过。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT: Path | None = None


def reset_repo_root_cache() -> None:
    """测试隔离：若需模拟多套布局可清空缓存（一般用不到）。"""
    global _REPO_ROOT
    _REPO_ROOT = None


def repo_root() -> Path:
    """返回逻辑仓库根目录（monorepo 顶层或 standalone 的 backend 目录）。"""
    global _REPO_ROOT
    if _REPO_ROOT is not None:
        return _REPO_ROOT

    here = Path(__file__).resolve()
    backend_tests = here.parent
    backend_dir = backend_tests.parent
    candidate_outer = backend_dir.parent

    if (
        (candidate_outer / "Makefile").is_file()
        and (candidate_outer / "backend").is_dir()
        and (candidate_outer / "backend" / "api").is_dir()
    ):
        _REPO_ROOT = candidate_outer
        return _REPO_ROOT

    if (
        (backend_dir / "api").is_dir()
        and (backend_dir / "tests").is_dir()
        and (backend_dir / "scripts").is_dir()
    ):
        _REPO_ROOT = backend_dir
        return _REPO_ROOT

    _REPO_ROOT = candidate_outer
    return _REPO_ROOT


def is_standalone_backend_layout() -> bool:
    """当前是否解析为「仅 backend 目录」（顶层无 Makefile）。"""
    root = repo_root()
    return (root / "api").is_dir() and not (root / "Makefile").exists()


def monorepo_contract_layout_available() -> bool:
    """是否存在完整 monorepo 合约常用顶层文件。"""
    root = repo_root()
    if is_standalone_backend_layout():
        return False
    return (root / "Makefile").is_file() and (root / "scripts" / "pr-check.sh").is_file()


def repo_path(relative: str) -> Path:
    """相对路径；standalone 下自动去掉 ``backend/`` 前缀。"""
    root = repo_root()
    rel = relative.replace("\\", "/")
    if rel.startswith("backend/") and not (root / "backend").is_dir():
        rel = rel[len("backend/") :]
    return root / rel


def repo_subprocess_env() -> dict[str, str]:
    """子进程 ``cwd=repo_root()`` 时注入 ``PYTHONPATH``（指向含 ``api`` / ``scripts`` 包的目录）。"""
    env = dict(os.environ)
    root = repo_root()
    pkg_root = root / "backend" if (root / "backend").is_dir() else root
    prev = env.get("PYTHONPATH", "")
    key = str(pkg_root)
    env["PYTHONPATH"] = key if not prev else f"{key}{os.pathsep}{prev}"
    return env


def repo_make_run(make_argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """在仓库根目录执行 ``make <target> ...``。"""
    return subprocess.run(["make", *make_argv], cwd=repo_root(), **kwargs)


def repo_run_python(script_repo_rel: str, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """在仓库根目录执行 ``python <script>``，并注入 ``PYTHONPATH``。"""
    env = repo_subprocess_env()
    extra = kwargs.pop("env", None)
    if extra:
        env = {**env, **extra}
    script = repo_path(script_repo_rel)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=repo_root(),
        env=env,
        **kwargs,
    )
