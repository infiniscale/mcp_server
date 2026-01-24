"""路由模块 - 根据文件类型选择最佳转换引擎。"""

from typing import List, Optional, Tuple

# 支持的扩展名列表
SUPPORTED_EXTENSIONS = [
    # Pandoc 擅长
    "docx", "html", "htm", "txt", "md", "markdown", "rst", "latex", "tex", "epub", "odt",
    # MinerU 擅长
    "pdf", "png", "jpg", "jpeg", "pptx", "ppt", "doc",
    # Excel 引擎
    "xlsx", "xls", "csv",
    # 其他图片
    "gif", "bmp", "tiff", "webp"
]

# 引擎支持的类型
ENGINE_SUPPORT = {
    "pandoc": {
        "primary": ["docx", "html", "htm", "txt", "markdown", "md", "rst", "latex", "tex", "epub", "odt", "rtf"],
        "secondary": [],  # Pandoc 不做回退引擎
    },
    "mineru": {
        "primary": ["pdf", "png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp", "pptx", "ppt", "doc"],
        "secondary": ["docx"],  # 复杂 docx 可以用 MinerU
    },
    "excel": {
        "primary": ["xlsx", "csv"],
        "secondary": ["xls"],  # xls 需要先转换
    }
}

# 默认路由规则（文件类型 -> 首选引擎）
DEFAULT_ROUTING = {
    # 文档格式 - Pandoc 优先
    "docx": "pandoc",
    "html": "pandoc",
    "htm": "pandoc",
    "txt": "pandoc",
    "markdown": "pandoc",
    "md": "pandoc",
    "rst": "pandoc",
    "latex": "pandoc",
    "tex": "pandoc",
    "epub": "pandoc",
    "odt": "pandoc",
    "rtf": "pandoc",

    # PDF 和图片 - MinerU
    "pdf": "mineru",
    "png": "mineru",
    "jpg": "mineru",
    "jpeg": "mineru",
    "gif": "mineru",
    "bmp": "mineru",
    "tiff": "mineru",
    "webp": "mineru",

    # PPT - MinerU
    "pptx": "mineru",
    "ppt": "mineru",

    # 老格式 Word - MinerU（或提示转换）
    "doc": "mineru",

    # 表格 - Excel 引擎
    "xlsx": "excel",
    "xls": "excel",
    "csv": "excel",
}

# 回退规则（首选引擎失败时的备选）
FALLBACK_ROUTING = {
    "docx": ["mineru"],  # docx Pandoc 失败可以尝试 MinerU
    "doc": [],  # doc 只有 MinerU 能处理
    "pdf": [],  # pdf 只有 MinerU
}


def choose_engine(detected_type: str, file_ext: str, route: str = "auto") -> str:
    """
    根据文件类型和路由参数选择转换引擎。

    Args:
        detected_type: 通过 magic bytes 识别的文件类型
        file_ext: 文件扩展名（不含点，小写）
        route: 路由参数 ("auto", "pandoc", "mineru", "excel")

    Returns:
        str: 选择的引擎名称
    """
    # 统一处理扩展名格式
    file_ext = file_ext.lstrip(".").lower()

    # 如果指定了具体引擎，验证是否支持该类型
    if route != "auto":
        if route in ENGINE_SUPPORT:
            supported = ENGINE_SUPPORT[route]["primary"] + ENGINE_SUPPORT[route]["secondary"]
            # 检查 detected_type 或 file_ext 是否支持
            if detected_type in supported or file_ext in supported:
                return route
            # 不支持时仍然返回指定的引擎，让引擎自己报错
            return route
        else:
            # 未知引擎，返回 auto 选择
            pass

    # Auto 模式：根据识别的类型选择
    # 优先使用 detected_type（更准确），其次使用扩展名
    type_to_check = detected_type if detected_type != "unknown" else file_ext

    if type_to_check in DEFAULT_ROUTING:
        return DEFAULT_ROUTING[type_to_check]

    # 如果无法识别，尝试根据扩展名
    if file_ext in DEFAULT_ROUTING:
        return DEFAULT_ROUTING[file_ext]

    # 完全无法识别，默认使用 Pandoc（它会报错如果不支持）
    return "pandoc"


def get_fallback_engines(detected_type: str, file_ext: str, failed_engine: str) -> List[str]:
    """
    获取回退引擎列表。

    Args:
        detected_type: 识别的文件类型
        file_ext: 文件扩展名
        failed_engine: 失败的引擎

    Returns:
        List[str]: 可以尝试的回退引擎列表
    """
    type_to_check = detected_type if detected_type != "unknown" else file_ext.lstrip(".").lower()

    fallbacks = FALLBACK_ROUTING.get(type_to_check, [])

    # 移除已经失败的引擎
    return [e for e in fallbacks if e != failed_engine]


def get_engine_for_type(file_type: str) -> Tuple[str, List[str]]:
    """
    获取文件类型对应的首选引擎和回退引擎。

    Args:
        file_type: 文件类型

    Returns:
        Tuple[str, List[str]]: (首选引擎, 回退引擎列表)
    """
    primary = DEFAULT_ROUTING.get(file_type, "pandoc")
    fallbacks = FALLBACK_ROUTING.get(file_type, [])
    return primary, fallbacks


def is_type_supported(file_type: str) -> bool:
    """检查文件类型是否支持。"""
    return file_type.lstrip(".").lower() in SUPPORTED_EXTENSIONS


def get_supported_types_for_engine(engine: str) -> List[str]:
    """获取引擎支持的文件类型列表。"""
    if engine not in ENGINE_SUPPORT:
        return []
    return ENGINE_SUPPORT[engine]["primary"] + ENGINE_SUPPORT[engine]["secondary"]
