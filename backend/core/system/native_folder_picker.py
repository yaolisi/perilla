"""
后端进程调用系统原生文件夹对话框（用于设置页「浏览」等）。
macOS / Windows 沿用既有 osascript / PowerShell；Linux 使用 zenity 或 kdialog。
无图形环境、用户取消或脚本失败时路径为 None；失败时可返回简短 stderr 摘要供前端展示。
"""

from __future__ import annotations

import asyncio
import platform
import shutil
from pathlib import Path
from typing import Literal

from log import logger


def _hint_from_stderr(stderr: bytes, max_len: int = 240) -> str | None:
    if not stderr:
        return None
    text = stderr.decode(errors="replace").strip()
    if not text:
        return None
    line = text.split("\n")[0].strip()
    if len(line) > max_len:
        return line[: max_len - 1] + "…"
    return line


def _applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


async def pick_folder(prompt: str = "Select folder") -> tuple[str | None, str | None]:
    """弹出原生文件夹选择器。返回 (绝对路径或 None, 失败时可展示的简短说明)。"""
    system = platform.system()
    try:
        if system == "Darwin":
            return await _pick_folder_darwin(prompt)
        if system == "Windows":
            return await _pick_folder_windows(prompt)
        if system == "Linux":
            return await _pick_folder_linux(prompt)
    except Exception as e:
        logger.warning("[native_folder_picker] pick_folder failed: %s", e)
        return (None, str(e)[:240])
    logger.warning("[native_folder_picker] unsupported platform: %s", system)
    return (None, None)


async def _pick_folder_darwin(prompt: str) -> tuple[str | None, str | None]:
    # 必须用 argv 传递整条 AppleScript，避免 shell 对引号/转义的破坏（曾导致 M 系列 Mac 下静默失败）。
    script = f'POSIX path of (choose folder with prompt "{_applescript_escape(prompt)}")'
    osascript = shutil.which("osascript") or "/usr/bin/osascript"
    proc = await asyncio.create_subprocess_exec(
        osascript,
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        p = stdout.decode().strip()
        return (p or None, None)
    hint = _hint_from_stderr(stderr)
    if hint:
        logger.warning(
            "[native_folder_picker] Darwin osascript failed rc=%s: %s",
            proc.returncode,
            hint,
        )
    return (None, hint)


async def _pick_folder_windows(prompt: str) -> tuple[str | None, str | None]:
    safe_prompt = prompt.replace("'", "''")
    cmd = (
        'powershell.exe -NoProfile -Command "& { $app = New-Object -ComObject Shell.Application; '
        f"$folder = $app.BrowseForFolder(0, '{safe_prompt}', 0); "
        'if ($folder) { $folder.Self.Path } }"'
    )
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        p = stdout.decode(errors="replace").strip()
        return (p or None, None)
    hint = _hint_from_stderr(stderr)
    return (None, hint)


async def _pick_folder_linux(prompt: str) -> tuple[str | None, str | None]:
    if shutil.which("zenity"):
        proc = await asyncio.create_subprocess_exec(
            "zenity",
            "--file-selection",
            "--directory",
            f"--title={prompt}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and stdout.strip():
            return (stdout.decode().strip(), None)
        if proc.returncode != 0:
            hint = _hint_from_stderr(stderr)
            return (None, hint)
        return (None, None)

    if shutil.which("kdialog"):
        start = str(Path.home())
        proc = await asyncio.create_subprocess_exec(
            "kdialog",
            "--getexistingdirectory",
            start,
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and stdout.strip():
            return (stdout.decode().strip(), None)
        if proc.returncode != 0:
            hint = _hint_from_stderr(stderr)
            return (None, hint)
        return (None, None)

    logger.warning(
        "[native_folder_picker] Linux: install zenity (GNOME) or kdialog (KDE) for folder picker, "
        "or enter the path manually in settings."
    )
    return (None, None)


def _pick_file_ps_title(prompt: str) -> str:
    """PowerShell 单引号标题安全转义。"""
    return prompt.replace("'", "''")


async def pick_file(
    prompt: str = "Select file",
    *,
    filter_kind: Literal["any", "gguf", "onnx"] = "any",
) -> tuple[str | None, str | None]:
    """
    弹出原生文件选择器。返回 (绝对路径或 None, 失败时可展示的简短说明)。
    filter_kind：Windows/Linux 下尽力筛选扩展名；macOS 一般为通用文件对话框。
    """
    system = platform.system()
    try:
        if system == "Darwin":
            return await _pick_file_darwin(prompt)
        if system == "Windows":
            return await _pick_file_windows(prompt, filter_kind=filter_kind)
        if system == "Linux":
            return await _pick_file_linux(prompt, filter_kind=filter_kind)
    except Exception as e:
        logger.warning("[native_folder_picker] pick_file failed: %s", e)
        return (None, str(e)[:240])
    logger.warning("[native_folder_picker] pick_file unsupported platform: %s", system)
    return (None, None)


async def _pick_file_darwin(prompt: str) -> tuple[str | None, str | None]:
    script = f'POSIX path of (choose file with prompt "{_applescript_escape(prompt)}")'
    osascript = shutil.which("osascript") or "/usr/bin/osascript"
    proc = await asyncio.create_subprocess_exec(
        osascript,
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        p = stdout.decode().strip()
        return (p or None, None)
    hint = _hint_from_stderr(stderr)
    if hint:
        logger.warning(
            "[native_folder_picker] Darwin choose file failed rc=%s: %s",
            proc.returncode,
            hint,
        )
    return (None, hint)


async def _pick_file_windows(
    prompt: str,
    *,
    filter_kind: Literal["any", "gguf", "onnx"],
) -> tuple[str | None, str | None]:
    safe_title = _pick_file_ps_title(prompt)
    if filter_kind == "gguf":
        filt = "GGUF (*.gguf)|*.gguf|All files (*.*)|*.*"
    elif filter_kind == "onnx":
        filt = "ONNX (*.onnx)|*.onnx|All files (*.*)|*.*"
    else:
        filt = "All files (*.*)|*.*"
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$dlg = New-Object System.Windows.Forms.OpenFileDialog; "
        f"$dlg.Title = '{safe_title}'; "
        f"$dlg.Filter = '{filt}'; "
        "if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $dlg.FileName }"
    )
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-STA",
        "-Command",
        ps_script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        p = stdout.decode(errors="replace").strip()
        return (p or None, None)
    hint = _hint_from_stderr(stderr)
    return (None, hint)


async def _pick_file_linux(
    prompt: str,
    *,
    filter_kind: Literal["any", "gguf", "onnx"],
) -> tuple[str | None, str | None]:
    if shutil.which("zenity"):
        args = [
            "zenity",
            "--file-selection",
            f"--title={prompt}",
            "--filename={}/".format(str(Path.home())),
        ]
        if filter_kind == "gguf":
            args.append("--file-filter=*.gguf")
        elif filter_kind == "onnx":
            args.append("--file-filter=*.onnx")
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and stdout.strip():
            return (stdout.decode().strip(), None)
        if proc.returncode != 0:
            hint = _hint_from_stderr(stderr)
            return (None, hint)
        return (None, None)

    logger.warning("[native_folder_picker] Linux file picker needs zenity for pick_file")
    return (None, None)
