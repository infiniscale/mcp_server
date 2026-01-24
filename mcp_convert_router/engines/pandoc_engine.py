"""Pandoc 引擎封装 - 使用 Pandoc 进行文档转换。"""

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Pandoc 超时时间（秒）
PANDOC_TIMEOUT = int(os.getenv("PANDOC_TIMEOUT", "60"))

# 支持的输入格式
PANDOC_INPUT_FORMATS = {
    "docx": "docx",
    "html": "html",
    "htm": "html",
    "txt": "plain",
    "markdown": "markdown",
    "md": "markdown",
    "rst": "rst",
    "latex": "latex",
    "tex": "latex",
    "epub": "epub",
    "odt": "odt",
    "rtf": "rtf",
}


async def convert_with_pandoc(
    file_path: str,
    detected_type: str,
    work_dir: Path,
    extract_media: bool = True,
) -> Dict[str, Any]:
    """
    使用 Pandoc 将文件转换为 Markdown。

    Args:
        file_path: 输入文件路径
        detected_type: 识别的文件类型
        work_dir: 工作目录
        extract_media: 是否提取媒体文件（图片等）

    Returns:
        Dict[str, Any]: {
            "ok": bool,
            "markdown_text": str,
            "output_dir": str,
            "files": List[str],
            "warnings": List[str],
            "attempt": Dict,
            "error_code": str (如果失败),
            "error_message": str (如果失败)
        }
    """
    start_time = time.time()
    attempt = {
        "engine": "pandoc",
        "status": "running",
        "error_code": None,
        "error_message": None,
        "elapsed_ms": 0,
        "timed_out": False,
        "exit_code": None,
        "stderr_tail": None
    }

    file_path = Path(file_path)
    warnings = []
    files = []

    # 确定输入格式
    input_format = _get_input_format(detected_type, file_path.suffix)
    if not input_format:
        attempt["status"] = "error"
        attempt["error_code"] = "E_TYPE_UNSUPPORTED"
        attempt["error_message"] = f"Pandoc 不支持的文件类型: {detected_type}"
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_TYPE_UNSUPPORTED",
            "error_message": f"Pandoc 不支持的文件类型: {detected_type}",
            "warnings": warnings
        }

    # 构建命令参数（使用参数数组，避免 shell 注入）
    output_dir = work_dir / "output"
    output_dir.mkdir(exist_ok=True)

    cmd = [
        "pandoc",
        str(file_path),
        "-f", input_format,
        "-t", "markdown",
        "--wrap=none",  # 不自动换行
    ]

    # 提取媒体文件
    if extract_media:
        media_dir = output_dir / "media"
        media_dir.mkdir(exist_ok=True)
        cmd.extend(["--extract-media", str(media_dir)])

    try:
        # 执行 Pandoc（shell=False 防止注入）
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PANDOC_TIMEOUT,
            shell=False
        )

        attempt["exit_code"] = result.returncode
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)

        if result.returncode != 0:
            attempt["status"] = "error"
            attempt["error_code"] = "E_PANDOC_FAILED"
            attempt["stderr_tail"] = result.stderr[-500:] if result.stderr else None
            attempt["error_message"] = f"Pandoc 返回错误码 {result.returncode}"

            return {
                "ok": False,
                "attempt": attempt,
                "error_code": "E_PANDOC_FAILED",
                "error_message": result.stderr or f"Pandoc 返回错误码 {result.returncode}",
                "warnings": warnings
            }

        # 成功
        markdown_text = result.stdout
        attempt["status"] = "success"

        # 检查是否有警告
        if result.stderr:
            warnings.append(f"Pandoc 警告: {result.stderr[:200]}")

        # 收集媒体文件
        if extract_media:
            media_dir = output_dir / "media"
            if media_dir.exists():
                files = [str(f.relative_to(output_dir)) for f in media_dir.rglob("*") if f.is_file()]

        return {
            "ok": True,
            "markdown_text": markdown_text,
            "output_dir": str(output_dir),
            "files": files,
            "warnings": warnings,
            "attempt": attempt
        }

    except subprocess.TimeoutExpired:
        attempt["status"] = "error"
        attempt["error_code"] = "E_TIMEOUT"
        attempt["error_message"] = f"Pandoc 执行超时（{PANDOC_TIMEOUT}秒）"
        attempt["timed_out"] = True
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)

        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_TIMEOUT",
            "error_message": f"Pandoc 执行超时（{PANDOC_TIMEOUT}秒）",
            "warnings": warnings
        }

    except FileNotFoundError:
        attempt["status"] = "error"
        attempt["error_code"] = "E_PANDOC_NOT_FOUND"
        attempt["error_message"] = "Pandoc 未安装或不在 PATH 中"
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)

        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_PANDOC_NOT_FOUND",
            "error_message": "Pandoc 未安装或不在 PATH 中",
            "warnings": warnings
        }

    except Exception as e:
        attempt["status"] = "error"
        attempt["error_code"] = "E_PANDOC_FAILED"
        attempt["error_message"] = str(e)
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)

        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_PANDOC_FAILED",
            "error_message": str(e),
            "warnings": warnings
        }


def _get_input_format(detected_type: str, file_ext: str) -> Optional[str]:
    """获取 Pandoc 输入格式。"""
    ext = file_ext.lstrip(".").lower()

    # 优先使用检测到的类型
    if detected_type in PANDOC_INPUT_FORMATS:
        return PANDOC_INPUT_FORMATS[detected_type]

    # 其次使用扩展名
    if ext in PANDOC_INPUT_FORMATS:
        return PANDOC_INPUT_FORMATS[ext]

    return None


def is_pandoc_available() -> bool:
    """检查 Pandoc 是否可用。"""
    try:
        result = subprocess.run(
            ["pandoc", "--version"],
            capture_output=True,
            timeout=5,
            shell=False
        )
        return result.returncode == 0
    except Exception:
        return False
