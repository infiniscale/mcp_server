"""输入验证模块 - 路径白名单、大小限制、扩展名白名单。"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# 支持的扩展名白名单
ALLOWED_EXTENSIONS = {
    # 文档格式
    "pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "csv",
    # 文本格式
    "txt", "md", "markdown", "html", "htm", "rst", "latex", "tex", "epub", "odt",
    # 图片格式
    "png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp"
}

# 默认最大文件大小 (MB)
DEFAULT_MAX_FILE_MB = 50

# croc code 格式正则（数字-单词-单词-单词 或类似格式）
CROC_CODE_PATTERN = re.compile(r"^\d+-[a-zA-Z]+-[a-zA-Z]+-[a-zA-Z]+$")


class ValidationError(Exception):
    """验证错误。"""
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def validate_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证输入参数。

    Args:
        args: 工具调用参数

    Returns:
        dict: {
            "valid": bool,
            "source_type": "file_path" | "url" | "croc_code",
            "source_value": str,
            "error_code": str (如果无效),
            "error_message": str (如果无效)
        }
    """
    file_path = args.get("file_path")
    url = args.get("url")
    croc_code = args.get("croc_code")

    # 检查输入来源（三选一）
    sources = [(k, v) for k, v in [("file_path", file_path), ("url", url), ("croc_code", croc_code)] if v]

    if len(sources) == 0:
        return {
            "valid": False,
            "error_code": "E_INPUT_MISSING",
            "error_message": "必须提供 file_path、url 或 croc_code 其中之一"
        }

    if len(sources) > 1:
        return {
            "valid": False,
            "error_code": "E_INPUT_CONFLICT",
            "error_message": f"只能提供一种输入方式，但收到了: {', '.join(k for k, v in sources)}"
        }

    source_type, source_value = sources[0]

    # 根据来源类型进行具体验证
    if source_type == "file_path":
        return validate_file_path(source_value, args)
    elif source_type == "url":
        return validate_url(source_value, args)
    elif source_type == "croc_code":
        return validate_croc_code(source_value, args)

    return {"valid": False, "error_code": "E_UNKNOWN", "error_message": "未知错误"}


def validate_file_path(file_path: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """验证本地文件路径。"""
    path = Path(file_path)

    # 1. 路径穿越检查
    try:
        # 解析绝对路径
        resolved = path.resolve()
        # 检查是否包含 .. 或其他路径穿越
        if ".." in str(path):
            return {
                "valid": False,
                "error_code": "E_PATH_TRAVERSAL",
                "error_message": "路径中不允许包含 '..'"
            }
    except Exception as e:
        return {
            "valid": False,
            "error_code": "E_PATH_INVALID",
            "error_message": f"无效的路径: {str(e)}"
        }

    # 2. 文件存在性检查
    if not path.exists():
        return {
            "valid": False,
            "error_code": "E_FILE_NOT_FOUND",
            "error_message": f"文件不存在: {file_path}"
        }

    if not path.is_file():
        return {
            "valid": False,
            "error_code": "E_NOT_A_FILE",
            "error_message": f"路径不是文件: {file_path}"
        }

    # 2.5 允许目录白名单检查（对齐 .env.template）
    require_allowlist = os.getenv("MCP_CONVERT_REQUIRE_ALLOWLIST", "true").strip().lower() in ("1", "true", "yes", "y", "on")
    roots_raw = os.getenv("MCP_CONVERT_ALLOWED_INPUT_ROOTS", "")
    roots = [r.strip() for r in roots_raw.split(",") if r.strip()]

    if require_allowlist and not roots:
        return {
            "valid": False,
            "error_code": "E_PATH_NOT_ALLOWED",
            "error_message": "未配置允许目录白名单（MCP_CONVERT_ALLOWED_INPUT_ROOTS）"
        }

    if roots:
        allowed = False
        try:
            resolved_path = Path(file_path).resolve()
        except Exception as e:
            return {
                "valid": False,
                "error_code": "E_PATH_INVALID",
                "error_message": f"无法解析文件路径: {str(e)}"
            }

        for root in roots:
            try:
                root_path = Path(root).expanduser().resolve()
                try:
                    if resolved_path.is_relative_to(root_path):
                        allowed = True
                        break
                except AttributeError:
                    if str(resolved_path).startswith(str(root_path)):
                        allowed = True
                        break
            except Exception:
                continue

        if not allowed:
            return {
                "valid": False,
                "error_code": "E_PATH_NOT_ALLOWED",
                "error_message": "文件路径不在允许目录白名单内"
            }

    # 3. 扩展名检查
    ext = path.suffix.lower().lstrip(".")
    if ext and ext not in ALLOWED_EXTENSIONS:
        return {
            "valid": False,
            "error_code": "E_EXTENSION_NOT_ALLOWED",
            "error_message": f"不支持的文件扩展名: .{ext}。支持的扩展名: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        }

    # 4. 文件大小检查
    max_file_mb = args.get("max_file_mb")
    if max_file_mb is None:
        try:
            max_file_mb = float(os.getenv("MCP_CONVERT_MAX_FILE_MB", str(DEFAULT_MAX_FILE_MB)))
        except Exception:
            max_file_mb = DEFAULT_MAX_FILE_MB
    max_file_bytes = max_file_mb * 1024 * 1024
    file_size = path.stat().st_size

    if file_size > max_file_bytes:
        return {
            "valid": False,
            "error_code": "E_INPUT_TOO_LARGE",
            "error_message": f"文件过大: {file_size / 1024 / 1024:.2f}MB，超过限制 {max_file_mb}MB"
        }

    return {
        "valid": True,
        "source_type": "file_path",
        "source_value": str(resolved)
    }


def validate_url(url: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """验证 URL。"""
    from urllib.parse import urlparse

    # 1. 协议检查
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {
            "valid": False,
            "error_code": "E_URL_FORBIDDEN",
            "error_message": f"不支持的 URL 协议: {parsed.scheme}。仅支持 http/https"
        }

    # 2. 主机名检查
    if not parsed.netloc:
        return {
            "valid": False,
            "error_code": "E_URL_INVALID",
            "error_message": "URL 缺少主机名"
        }

    # 3. SSRF 防护（基础检查，完整实现在 Todo 2.3）
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return {
            "valid": False,
            "error_code": "E_URL_FORBIDDEN",
            "error_message": "不允许访问本地地址"
        }

    # 检查私有 IP 范围（基础检查）
    if hostname.startswith(("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                           "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                           "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                           "172.30.", "172.31.", "192.168.", "169.254.")):
        return {
            "valid": False,
            "error_code": "E_URL_FORBIDDEN",
            "error_message": "不允许访问内网地址"
        }

    return {
        "valid": True,
        "source_type": "url",
        "source_value": url
    }


def validate_croc_code(croc_code: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """验证 croc code。"""
    # 1. 格式检查
    code = croc_code.strip()

    # croc code 通常是 "数字-单词-单词-单词" 格式
    # 但也可能有其他变体，这里做宽松检查
    if not code:
        return {
            "valid": False,
            "error_code": "E_CROC_CODE_INVALID",
            "error_message": "croc code 不能为空"
        }

    # 检查是否包含危险字符（防止命令注入）
    if any(c in code for c in [";", "&", "|", "$", "`", "(", ")", "{", "}", "<", ">", "\n", "\r"]):
        return {
            "valid": False,
            "error_code": "E_CROC_CODE_INVALID",
            "error_message": "croc code 包含非法字符"
        }

    # 长度检查
    if len(code) > 100:
        return {
            "valid": False,
            "error_code": "E_CROC_CODE_INVALID",
            "error_message": "croc code 过长"
        }

    return {
        "valid": True,
        "source_type": "croc_code",
        "source_value": code
    }
