"""Legacy Office 格式转换引擎 - 使用 LibreOffice 将旧格式转换为新格式。

将 doc/xls/ppt 转换为 docx/xlsx/pptx，然后可以使用其他引擎处理。
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

# 默认转换超时时间（秒）
DEFAULT_SOFFICE_TIMEOUT = int(os.getenv("SOFFICE_TIMEOUT", "120"))

# 格式映射：旧格式 -> 新格式
LEGACY_FORMAT_MAP = {
    "doc": "docx",
    "xls": "xlsx",
    "ppt": "pptx",
}

# LibreOffice 转换格式映射
SOFFICE_OUTPUT_FORMAT = {
    "doc": "docx",
    "xls": "xlsx",
    "ppt": "pptx",
}


def is_legacy_format(file_type: str) -> bool:
    """检查是否是需要转换的旧格式。"""
    return file_type in LEGACY_FORMAT_MAP


def get_converted_format(file_type: str) -> Optional[str]:
    """获取转换后的格式。"""
    return LEGACY_FORMAT_MAP.get(file_type)


def is_soffice_available() -> bool:
    """检查 LibreOffice (soffice) 是否可用。"""
    try:
        # 尝试常见的 soffice 路径
        soffice_paths = [
            "soffice",  # 系统 PATH
            "/usr/bin/soffice",
            "/usr/local/bin/soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS
        ]

        for path in soffice_paths:
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    timeout=10,
                    shell=False
                )
                if result.returncode == 0:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        return False
    except Exception:
        return False


def get_soffice_path() -> Optional[str]:
    """获取 soffice 可执行文件路径。"""
    soffice_paths = [
        "soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]

    for path in soffice_paths:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                timeout=10,
                shell=False
            )
            if result.returncode == 0:
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None


async def convert_legacy_format(
    file_path: str,
    detected_type: str,
    work_dir: Path,
    timeout_seconds: int = DEFAULT_SOFFICE_TIMEOUT,
) -> Dict[str, Any]:
    """
    将旧格式 Office 文件转换为新格式。

    使用 LibreOffice headless 模式进行转换。

    Args:
        file_path: 输入文件路径
        detected_type: 检测到的文件类型（doc/xls/ppt）
        work_dir: 工作目录
        timeout_seconds: 转换超时时间（秒）

    Returns:
        Dict[str, Any]: {
            "ok": bool,
            "converted_path": str (转换后的文件路径),
            "converted_type": str (转换后的文件类型),
            "error_code": str (如果失败),
            "error_message": str (如果失败),
            "attempt": Dict (尝试记录),
            "elapsed_ms": int
        }
    """
    start_time = time.time()
    result = {
        "ok": False,
        "converted_path": None,
        "converted_type": None,
        "error_code": None,
        "error_message": None,
        "attempt": {
            "engine": "legacy_office",
            "status": "pending",
            "elapsed_ms": 0
        },
        "elapsed_ms": 0
    }

    # 检查是否支持该格式
    if detected_type not in LEGACY_FORMAT_MAP:
        result["error_code"] = "E_LEGACY_FORMAT_NOT_SUPPORTED"
        result["error_message"] = f"不支持的旧格式: {detected_type}"
        result["attempt"]["status"] = "error"
        result["attempt"]["error_code"] = result["error_code"]
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        result["attempt"]["elapsed_ms"] = result["elapsed_ms"]
        return result

    # 获取 soffice 路径
    soffice_path = get_soffice_path()
    if not soffice_path:
        result["error_code"] = "E_SOFFICE_NOT_FOUND"
        result["error_message"] = (
            "LibreOffice (soffice) 未安装或不在 PATH 中。\n"
            "请安装 LibreOffice：\n"
            "  - macOS: brew install --cask libreoffice\n"
            "  - Ubuntu: sudo apt install libreoffice\n"
            "  - Windows: 从 https://www.libreoffice.org 下载安装"
        )
        result["attempt"]["status"] = "error"
        result["attempt"]["error_code"] = result["error_code"]
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        result["attempt"]["elapsed_ms"] = result["elapsed_ms"]
        return result

    # 确保输出目录存在
    output_dir = work_dir / "converted"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取目标格式
    target_format = SOFFICE_OUTPUT_FORMAT[detected_type]

    # 构建 soffice 命令
    # 注意：使用参数数组，shell=False 防止命令注入
    cmd = [
        soffice_path,
        "--headless",
        "--convert-to", target_format,
        "--outdir", str(output_dir),
        str(file_path)
    ]

    try:
        proc_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            cwd=str(output_dir)
        )

        result["attempt"]["exit_code"] = proc_result.returncode

        if proc_result.returncode != 0:
            result["error_code"] = "E_LEGACY_CONVERT_FAILED"
            result["error_message"] = (
                f"LibreOffice 转换失败 (exit code: {proc_result.returncode})\n"
                f"stderr: {proc_result.stderr[-500:] if proc_result.stderr else 'N/A'}"
            )
            result["attempt"]["status"] = "error"
            result["attempt"]["error_code"] = result["error_code"]
            result["attempt"]["stderr_tail"] = proc_result.stderr[-500:] if proc_result.stderr else None
            result["elapsed_ms"] = int((time.time() - start_time) * 1000)
            result["attempt"]["elapsed_ms"] = result["elapsed_ms"]
            return result

        # 查找转换后的文件
        input_stem = Path(file_path).stem
        expected_output = output_dir / f"{input_stem}.{target_format}"

        if not expected_output.exists():
            # 尝试查找任何新生成的文件
            converted_files = list(output_dir.glob(f"*.{target_format}"))
            if converted_files:
                expected_output = converted_files[0]
            else:
                result["error_code"] = "E_LEGACY_OUTPUT_NOT_FOUND"
                result["error_message"] = (
                    f"转换似乎成功，但未找到输出文件。\n"
                    f"期望路径: {expected_output}"
                )
                result["attempt"]["status"] = "error"
                result["attempt"]["error_code"] = result["error_code"]
                result["elapsed_ms"] = int((time.time() - start_time) * 1000)
                result["attempt"]["elapsed_ms"] = result["elapsed_ms"]
                return result

        # 检查输出文件大小
        output_size = expected_output.stat().st_size
        if output_size == 0:
            result["error_code"] = "E_LEGACY_OUTPUT_EMPTY"
            result["error_message"] = "转换后的文件为空"
            result["attempt"]["status"] = "error"
            result["attempt"]["error_code"] = result["error_code"]
            result["elapsed_ms"] = int((time.time() - start_time) * 1000)
            result["attempt"]["elapsed_ms"] = result["elapsed_ms"]
            return result

        # 成功
        result["ok"] = True
        result["converted_path"] = str(expected_output)
        result["converted_type"] = target_format
        result["attempt"]["status"] = "success"
        result["attempt"]["output_size"] = output_size
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        result["attempt"]["elapsed_ms"] = result["elapsed_ms"]

        return result

    except subprocess.TimeoutExpired:
        result["error_code"] = "E_TIMEOUT"
        result["error_message"] = f"LibreOffice 转换超时 ({timeout_seconds}秒)"
        result["attempt"]["status"] = "error"
        result["attempt"]["error_code"] = result["error_code"]
        result["attempt"]["timed_out"] = True
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        result["attempt"]["elapsed_ms"] = result["elapsed_ms"]
        return result

    except Exception as e:
        result["error_code"] = "E_LEGACY_CONVERT_FAILED"
        result["error_message"] = str(e)
        result["attempt"]["status"] = "error"
        result["attempt"]["error_code"] = result["error_code"]
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        result["attempt"]["elapsed_ms"] = result["elapsed_ms"]
        return result
