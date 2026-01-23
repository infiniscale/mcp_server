"""文件类型识别模块 - 使用 magic bytes 识别文件真实类型。

不仅依赖扩展名，而是通过文件头（magic bytes）和容器特征来识别文件类型。
"""

import zipfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from .zip_security import check_zip_security, ZipSecurityConfig, ZipSecurityResult

# Magic bytes 定义
MAGIC_BYTES = {
    # PDF: %PDF-
    "pdf": [b"%PDF-"],
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    "png": [b"\x89PNG\r\n\x1a\n"],
    # JPEG: FF D8 FF
    "jpeg": [b"\xff\xd8\xff"],
    # GIF: GIF87a 或 GIF89a
    "gif": [b"GIF87a", b"GIF89a"],
    # BMP: BM
    "bmp": [b"BM"],
    # TIFF: 49 49 2A 00 (little-endian) 或 4D 4D 00 2A (big-endian)
    "tiff": [b"II*\x00", b"MM\x00*"],
    # WebP: RIFF....WEBP
    "webp": [b"RIFF"],  # 需要进一步检查 WEBP 标识
    # OLE2 (doc/xls/ppt 老格式): D0 CF 11 E0 A1 B1 1A E1
    "ole2": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    # ZIP (docx/xlsx/pptx/epub/odt 容器): 50 4B 03 04
    "zip": [b"PK\x03\x04"],
    # RTF: {\rtf
    "rtf": [b"{\\rtf"],
    # HTML: <!DOCTYPE 或 <html
    "html": [b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML"],
}

# ZIP 容器内的 OOXML 识别规则
OOXML_MARKERS = {
    "docx": ["word/document.xml", "word/"],
    "xlsx": ["xl/workbook.xml", "xl/"],
    "pptx": ["ppt/presentation.xml", "ppt/"],
}


def detect_file_type(file_path: Path) -> str:
    """
    识别文件真实类型。

    优先级：
    1. Magic bytes 识别
    2. ZIP 容器内容识别（OOXML）
    3. 文件扩展名（兜底）

    Args:
        file_path: 文件路径

    Returns:
        str: 文件类型标识（如 "pdf", "docx", "xlsx" 等）
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return "unknown"

    # 读取文件前 4KB 用于识别
    try:
        with open(file_path, "rb") as f:
            header = f.read(4096)
    except Exception:
        return "unknown"

    if not header:
        return "unknown"

    # 1. Magic bytes 识别
    detected = _detect_by_magic_bytes(header)

    if detected == "zip":
        # 2. ZIP 容器进一步识别 OOXML
        ooxml_type = _detect_ooxml_type(file_path)
        if ooxml_type:
            return ooxml_type
        # 检查是否是 EPUB 或 ODT
        other_type = _detect_other_zip_type(file_path)
        if other_type:
            return other_type
        return "zip"

    if detected == "ole2":
        # 3. OLE2 容器识别（doc/xls/ppt 老格式）
        return _detect_ole2_type(file_path)

    if detected:
        return detected

    # 4. 文本文件检测
    text_type = _detect_text_type(header, file_path)
    if text_type:
        return text_type

    # 5. 扩展名兜底
    ext = file_path.suffix.lower().lstrip(".")
    if ext:
        return ext

    return "unknown"


def _detect_by_magic_bytes(header: bytes) -> Optional[str]:
    """通过 magic bytes 识别文件类型。"""
    for file_type, signatures in MAGIC_BYTES.items():
        for sig in signatures:
            if header.startswith(sig):
                # WebP 需要额外检查
                if file_type == "webp":
                    if len(header) >= 12 and header[8:12] == b"WEBP":
                        return "webp"
                    continue
                return file_type
    return None


def _detect_ooxml_type(file_path: Path) -> Optional[str]:
    """识别 OOXML 类型（docx/xlsx/pptx）。"""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            names = zf.namelist()

            for ooxml_type, markers in OOXML_MARKERS.items():
                for marker in markers:
                    if any(name.startswith(marker) or name == marker for name in names):
                        return ooxml_type

            # 检查 [Content_Types].xml 进行更精确的识别
            if "[Content_Types].xml" in names:
                try:
                    content_types = zf.read("[Content_Types].xml").decode("utf-8", errors="ignore")
                    if "wordprocessingml" in content_types:
                        return "docx"
                    if "spreadsheetml" in content_types:
                        return "xlsx"
                    if "presentationml" in content_types:
                        return "pptx"
                except Exception:
                    pass

    except (zipfile.BadZipFile, Exception):
        pass

    return None


def _detect_other_zip_type(file_path: Path) -> Optional[str]:
    """识别其他 ZIP 容器类型（EPUB, ODT 等）。"""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            names = zf.namelist()

            # EPUB
            if "META-INF/container.xml" in names or "mimetype" in names:
                try:
                    mimetype = zf.read("mimetype").decode("utf-8", errors="ignore").strip()
                    if "epub" in mimetype:
                        return "epub"
                    if "opendocument.text" in mimetype:
                        return "odt"
                    if "opendocument.spreadsheet" in mimetype:
                        return "ods"
                    if "opendocument.presentation" in mimetype:
                        return "odp"
                except Exception:
                    pass

    except (zipfile.BadZipFile, Exception):
        pass

    return None


def _detect_ole2_type(file_path: Path) -> str:
    """识别 OLE2 容器类型（doc/xls/ppt 老格式）。

    注意：完整的 OLE2 解析比较复杂，这里使用简化方法。
    """
    try:
        with open(file_path, "rb") as f:
            content = f.read(8192)  # 读取更多内容用于识别

            # 简化识别：根据内部字符串特征
            if b"Word.Document" in content or b"Microsoft Word" in content:
                return "doc"
            if b"Microsoft Excel" in content or b"Workbook" in content:
                return "xls"
            if b"PowerPoint" in content or b"Microsoft PowerPoint" in content:
                return "ppt"

    except Exception:
        pass

    # 如果无法确定具体类型，根据扩展名判断
    ext = file_path.suffix.lower().lstrip(".")
    if ext in ("doc", "xls", "ppt"):
        return ext

    return "ole2"


def _detect_text_type(header: bytes, file_path: Path) -> Optional[str]:
    """检测文本文件类型。"""
    # 尝试解码为文本
    try:
        text = header.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            text = header.decode("latin-1", errors="strict")
        except Exception:
            return None

    text_lower = text.lower()

    # HTML 检测
    if text_lower.strip().startswith(("<!doctype html", "<html", "<!doctype")):
        return "html"

    # Markdown 检测（通过特征）
    if text.startswith("#") or "\n#" in text or text.startswith("---\n"):
        ext = file_path.suffix.lower().lstrip(".")
        if ext in ("md", "markdown"):
            return "markdown"

    # LaTeX 检测
    if "\\documentclass" in text or "\\begin{document}" in text:
        return "latex"

    # RST 检测
    if ".. " in text or "====" in text or "----" in text:
        ext = file_path.suffix.lower().lstrip(".")
        if ext == "rst":
            return "rst"

    # CSV 检测（简单检测，通过逗号分隔）
    ext = file_path.suffix.lower().lstrip(".")
    if ext == "csv":
        return "csv"

    # 纯文本
    if ext in ("txt", "text"):
        return "txt"

    # 根据扩展名返回
    if ext in ("md", "markdown"):
        return "markdown"

    return None


def get_mime_type(file_type: str) -> str:
    """获取文件类型对应的 MIME 类型。"""
    mime_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "png": "image/png",
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "webp": "image/webp",
        "html": "text/html",
        "txt": "text/plain",
        "markdown": "text/markdown",
        "csv": "text/csv",
        "epub": "application/epub+zip",
        "odt": "application/vnd.oasis.opendocument.text",
    }
    return mime_map.get(file_type, "application/octet-stream")


def detect_file_type_with_security(
    file_path: Path,
    security_config: Optional[ZipSecurityConfig] = None
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    识别文件类型，并对 ZIP 容器进行安全检查。

    Args:
        file_path: 文件路径
        security_config: ZIP 安全检查配置（可选）

    Returns:
        Tuple[str, Optional[Dict[str, Any]]]:
            - 文件类型标识
            - 安全检查错误信息（如果有）
              格式: {"error_code": str, "error_message": str}
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return "unknown", {"error_code": "E_FILE_NOT_FOUND", "error_message": f"文件不存在: {file_path}"}

    # 读取文件前 4KB 用于识别
    try:
        with open(file_path, "rb") as f:
            header = f.read(4096)
    except Exception as e:
        return "unknown", {"error_code": "E_FILE_READ_ERROR", "error_message": f"无法读取文件: {e}"}

    if not header:
        return "unknown", {"error_code": "E_FILE_EMPTY", "error_message": "文件为空"}

    # Magic bytes 识别
    detected = _detect_by_magic_bytes(header)

    # 如果是 ZIP 容器，先进行安全检查
    if detected == "zip":
        security_result = check_zip_security(file_path, security_config)
        if not security_result.safe:
            return "zip", {
                "error_code": security_result.error_code,
                "error_message": security_result.error_message,
                "security_stats": security_result.stats
            }

        # 安全检查通过，继续识别 OOXML 类型
        ooxml_type = _detect_ooxml_type(file_path)
        if ooxml_type:
            return ooxml_type, None

        # 检查是否是 EPUB 或 ODT
        other_type = _detect_other_zip_type(file_path)
        if other_type:
            return other_type, None

        return "zip", None

    if detected == "ole2":
        return _detect_ole2_type(file_path), None

    if detected:
        return detected, None

    # 文本文件检测
    text_type = _detect_text_type(header, file_path)
    if text_type:
        return text_type, None

    # 扩展名兜底
    ext = file_path.suffix.lower().lstrip(".")
    if ext:
        return ext, None

    return "unknown", None


def is_zip_based_format(file_type: str) -> bool:
    """检查文件类型是否是基于 ZIP 容器的格式。"""
    zip_based_types = {
        "zip", "docx", "xlsx", "pptx", "epub", "odt", "ods", "odp"
    }
    return file_type in zip_based_types
