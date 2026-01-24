"""Croc 接收模块 - 通过 croc 接收跨机器传输的文件。"""

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 默认 croc 超时时间（秒）
DEFAULT_CROC_TIMEOUT = 300

# 默认最大文件大小（字节）
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50MB


async def receive_file_via_croc(
    croc_code: str,
    work_dir: Path,
    timeout_seconds: int = DEFAULT_CROC_TIMEOUT,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> Dict[str, Any]:
    """
    通过 croc 接收文件。

    Args:
        croc_code: croc 传输码
        work_dir: 工作目录（文件将保存到 work_dir/input/）
        timeout_seconds: 超时时间（秒）
        max_file_bytes: 最大文件大小（字节）

    Returns:
        Dict[str, Any]: {
            "ok": bool,
            "file_path": str (接收的文件路径),
            "filename": str,
            "size_bytes": int,
            "error_code": str (如果失败),
            "error_message": str (如果失败),
            "elapsed_ms": int,
            "timed_out": bool
        }
    """
    start_time = time.time()
    result = {
        "ok": False,
        "file_path": None,
        "filename": None,
        "size_bytes": 0,
        "error_code": None,
        "error_message": None,
        "elapsed_ms": 0,
        "timed_out": False,
        "exit_code": None,
        "stderr_tail": None
    }

    # 确保输入目录存在
    input_dir = work_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # 构建 croc 命令（使用参数数组，避免 shell 注入）
    #
    # croc v10+ 默认“新模式”：不再支持把 code 作为位置参数（会直接输出提示并 exit 0）。
    # 新模式下应通过环境变量 CROC_SECRET 传入 code，并直接运行 `croc`（不带 code 参数）。
    cmd = [
        "croc",
        "--yes",  # 自动确认接收
        "--out", str(input_dir),  # 输出目录
    ]

    try:
        # 执行 croc（shell=False 防止注入）
        env = os.environ.copy()
        env["CROC_SECRET"] = croc_code

        proc_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            cwd=str(input_dir),  # 在输入目录中执行
            env=env,
        )

        result["exit_code"] = proc_result.returncode
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        stdout_tail = proc_result.stdout[-500:] if proc_result.stdout else None
        stderr_tail = proc_result.stderr[-500:] if proc_result.stderr else None

        if proc_result.returncode != 0:
            result["error_code"] = "E_CROC_FAILED"
            result["error_message"] = proc_result.stderr or f"croc 返回错误码 {proc_result.returncode}"
            result["stderr_tail"] = stderr_tail or stdout_tail
            return result

        # 检查接收结果：查找接收到的文件
        received_files = list(input_dir.iterdir())

        if not received_files:
            result["error_code"] = "E_CROC_NO_FILE"
            result["error_message"] = "croc 执行成功但未接收到任何文件"
            result["stderr_tail"] = stderr_tail or stdout_tail
            return result

        # 只支持单文件，多文件时选择最大的
        if len(received_files) > 1:
            # 选择最大的文件
            received_files.sort(key=lambda f: f.stat().st_size if f.is_file() else 0, reverse=True)
            # 保留警告信息
            result["warnings"] = [f"接收到 {len(received_files)} 个文件，使用最大的文件"]

        # 只处理文件，跳过目录
        received_file = None
        for f in received_files:
            if f.is_file():
                received_file = f
                break

        if received_file is None:
            result["error_code"] = "E_CROC_NO_FILE"
            result["error_message"] = "接收到的内容不是文件"
            return result

        # 检查文件大小
        file_size = received_file.stat().st_size
        if file_size > max_file_bytes:
            # 超过大小限制，删除文件并返回错误
            received_file.unlink()
            result["error_code"] = "E_INPUT_TOO_LARGE"
            result["error_message"] = f"接收的文件过大: {file_size / 1024 / 1024:.2f}MB，超过限制 {max_file_bytes / 1024 / 1024:.2f}MB"
            return result

        # 成功
        result["ok"] = True
        result["file_path"] = str(received_file)
        result["filename"] = received_file.name
        result["size_bytes"] = file_size

        return result

    except subprocess.TimeoutExpired:
        result["error_code"] = "E_TIMEOUT"
        result["error_message"] = f"croc 接收超时（{timeout_seconds}秒）"
        result["timed_out"] = True
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return result

    except FileNotFoundError:
        result["error_code"] = "E_CROC_NOT_FOUND"
        result["error_message"] = "croc 未安装或不在 PATH 中"
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return result

    except Exception as e:
        result["error_code"] = "E_CROC_FAILED"
        result["error_message"] = str(e)
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return result


def is_croc_available() -> bool:
    """检查 croc 是否可用。"""
    try:
        proc_result = subprocess.run(
            ["croc", "--version"],
            capture_output=True,
            timeout=5,
            shell=False
        )
        return proc_result.returncode == 0
    except Exception:
        return False


def get_croc_version() -> Optional[str]:
    """获取 croc 版本。"""
    try:
        proc_result = subprocess.run(
            ["croc", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False
        )
        if proc_result.returncode == 0:
            return proc_result.stdout.strip()
        return None
    except Exception:
        return None
