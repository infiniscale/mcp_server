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

# croc code 格式正则（常见格式：数字-单词-单词-单词）
CROC_CODE_PATTERN = re.compile(r"^\d+-[a-zA-Z]+-[a-zA-Z]+-[a-zA-Z]+$")
# 本项目的 croc_send 默认生成短码（字母数字），用于程序化传递
SHORT_CROC_CODE_PATTERN = re.compile(r"^[a-zA-Z0-9]{6,32}$")

# URL 协议正则
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

# OpenWebUI file_id 格式正则 (UUID: 8-4-4-4-12 格式)
OPENWEBUI_FILE_ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class ValidationError(Exception):
    """验证错误。"""
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def detect_source_type(source: str) -> str:
    """
    自动检测 source 参数的类型。

    Args:
        source: 输入的 source 值

    Returns:
        str: "url" | "croc_code" | "file_path"

    检测规则（按优先级）：
    1. 以 http:// 或 https:// 开头 → url
    2. 匹配常见 croc code 格式（数字-单词-单词-单词）→ croc_code
    3. 匹配短 croc code（6~32 位字母数字，且包含至少一个数字）→ croc_code
    3. 其他情况 → file_path
    """
    source = source.strip()

    # 1. URL 检测
    if URL_PATTERN.match(source):
        return "url"

    # 2. Croc Code 检测（数字-单词-单词-单词 格式）
    if CROC_CODE_PATTERN.match(source):
        return "croc_code"

    # 2.5 短 croc code（避免把常见英文单词误判成 code：要求至少包含一个数字）
    if SHORT_CROC_CODE_PATTERN.match(source) and any(ch.isdigit() for ch in source):
        return "croc_code"

    # 3. 默认为文件路径
    return "file_path"


def validate_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证输入参数。

    支持两种用法：
    1. 推荐用法：使用 source 参数，自动检测类型
    2. 兼容用法：使用 file_path / url / croc_code 参数

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
    # 获取所有可能的输入来源
    source = args.get("source")
    file_path = args.get("file_path")
    url = args.get("url")
    croc_code = args.get("croc_code")

    # 优先使用 source 参数（推荐用法）
    if source:
        # 如果同时指定了其他参数，给出警告但仍使用 source
        source_type = detect_source_type(source)
        source_value = source.strip()

        # 根据检测到的类型进行验证
        if source_type == "file_path":
            return validate_file_path(source_value, args)
        elif source_type == "url":
            return validate_url(source_value, args)
        elif source_type == "croc_code":
            return validate_croc_code(source_value, args)

    # 兼容旧用法：使用 file_path / url / croc_code 参数
    sources = [(k, v) for k, v in [("file_path", file_path), ("url", url), ("croc_code", croc_code)] if v]

    if len(sources) == 0:
        return {
            "valid": False,
            "error_code": "E_INPUT_MISSING",
            "error_message": "必须提供 source 参数，或 file_path/url/croc_code 其中之一"
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

    # 检查白名单
    hostname = parsed.hostname or ""
    allowed_hosts = _get_allowed_url_hosts()

    if hostname in allowed_hosts:
        return {
            "valid": True,
            "source_type": "url",
            "source_value": url,
            "allowlisted": True
        }

    # 3. SSRF 防护（基础检查，完整实现在 Todo 2.3）
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


def _get_allowed_url_hosts() -> set:
    """获取允许的 URL 主机名列表。"""
    import os
    hosts_raw = os.getenv("MCP_CONVERT_ALLOWED_URL_HOSTS", "")
    return {h.strip().lower() for h in hosts_raw.split(",") if h.strip()}


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
