"""MCP Convert Router Server - 统一文件转 Markdown 服务。

提供 convert_to_markdown 工具，支持多种输入方式和多引擎路由。

推荐启动方式：
  - `python -m mcp_convert_router.server`
"""

import asyncio
import os
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from .routing import choose_engine, SUPPORTED_EXTENSIONS
from .validators import validate_input, ValidationError
from .storage import StorageManager
from .file_detector import detect_file_type, detect_file_type_with_security
from .logging_utils import RequestContext, set_current_context, clear_current_context

# 初始化服务器
server = Server("mcp-convert-router")

# 存储管理器
storage = StorageManager()


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """列出可用工具。"""
    return [
        types.Tool(
            name="convert_to_markdown",
            description=(
                "将文件转换为 Markdown 格式。支持多种输入方式和文件格式。\n\n"
                "支持的输入方式：\n"
                "- file_path: 服务端本地文件路径\n"
                "- url: 远端文件 URL（http/https）\n"
                "- croc_code: 跨机器传文件的 croc code\n\n"
                "支持的文件格式：\n"
                "- 文档: pdf, docx, doc, pptx, ppt, xlsx, xls, csv\n"
                "- 文本: txt, md, html, rst, latex, epub, odt\n"
                "- 图片: png, jpg, jpeg（需要 OCR）\n\n"
                "路由引擎：\n"
                "- pandoc: 适合 docx/html/txt/markdown 等结构化文本\n"
                "- mineru: 适合 pdf/图片/pptx（支持 OCR）\n"
                "- excel: 适合 xlsx/csv 表格"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    # === 输入来源（三选一）===
                    "file_path": {
                        "type": "string",
                        "description": "服务端本地文件路径。例如: /path/to/document.pdf"
                    },
                    "url": {
                        "type": "string",
                        "description": "远端文件 URL（仅支持 http/https）。例如: https://example.com/document.pdf"
                    },
                    "croc_code": {
                        "type": "string",
                        "description": "croc 传输码，用于跨机器接收文件。格式: 数字-单词-单词-单词"
                    },
                    # === 路由控制 ===
                    "route": {
                        "type": "string",
                        "enum": ["auto", "pandoc", "mineru", "excel"],
                        "default": "auto",
                        "description": "选择转换引擎。auto 会根据文件类型自动选择最佳引擎"
                    },
                    # === OCR 相关（仅 MinerU 生效）===
                    "enable_ocr": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否启用 OCR 识别（仅对 MinerU 引擎生效，适用于扫描件/图片）"
                    },
                    "language": {
                        "type": "string",
                        "default": "ch",
                        "description": "OCR 语言。ch=中文, en=英文"
                    },
                    # === 页面范围（仅 MinerU 远程 API）===
                    "page_ranges": {
                        "type": "string",
                        "description": "指定页码范围（仅 MinerU 远程 API）。例如: '2,4-6' 或 '2--2'（到倒数第2页）"
                    },
                    # === 输出控制 ===
                    "output_dir": {
                        "type": "string",
                        "description": "自定义输出目录（可选，不传则使用服务端临时目录）"
                    },
                    "return_mode": {
                        "type": "string",
                        "enum": ["text", "path", "both"],
                        "default": "text",
                        "description": "返回模式。text=仅返回文本, path=仅返回路径, both=两者都返回"
                    },
                    # === 安全限制 ===
                    "max_file_mb": {
                        "type": "number",
                        "default": 50,
                        "description": "最大文件大小（MB），默认 50MB"
                    },
                    "croc_timeout_seconds": {
                        "type": "number",
                        "default": 120,
                        "description": "croc 接收超时时间（秒），默认 120 秒"
                    }
                },
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="get_supported_formats",
            description="获取当前支持的文件格式和路由策略",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="health",
            description="检查服务健康状态，包括各引擎是否可用",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """处理工具调用。"""

    if name == "convert_to_markdown":
        return await handle_convert_to_markdown(arguments or {})
    elif name == "get_supported_formats":
        return await handle_get_supported_formats()
    elif name == "health":
        return await handle_health()
    else:
        raise ValueError(f"Unknown tool: {name}")


async def handle_convert_to_markdown(args: Dict[str, Any]) -> list[types.TextContent]:
    """处理 convert_to_markdown 工具调用。"""
    import json

    # 创建请求上下文
    ctx = RequestContext()
    set_current_context(ctx)

    # 初始化返回结构
    result = {
        "ok": False,
        "markdown_text": "",
        "engine_used": "unknown",
        "attempts": [],
        "source_info": {},
        "artifacts": {},
        "warnings": [],
        "request_id": ctx.request_id  # 在返回结构中包含 request_id
    }

    try:
        # 1. 验证输入
        validation = validate_input(args)
        if not validation["valid"]:
            result["error_code"] = validation.get("error_code", "E_VALIDATION_FAILED")
            result["error_message"] = validation.get("error_message", "输入验证失败")
            ctx.log_error(result["error_code"], result["error_message"])
            ctx.log_complete(success=False)
            clear_current_context()
            return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        source_type = validation["source_type"]
        source_value = validation["source_value"]
        ctx.log_start(source_type, source_value)

        # 2. 获取/下载/接收文件
        file_path = None
        work_dir = storage.create_work_dir()
        result["artifacts"]["work_dir"] = str(work_dir)

        if source_type == "file_path":
            file_path = Path(source_value)
            if not file_path.exists():
                result["error_code"] = "E_FILE_NOT_FOUND"
                result["error_message"] = f"文件不存在: {source_value}"
                ctx.log_error(result["error_code"], result["error_message"])
                ctx.log_complete(success=False)
                clear_current_context()
                return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
            ctx.log_file_received(file_path.name, file_path.stat().st_size)

        elif source_type == "url":
            # URL 下载
            from .url_downloader import download_file_from_url
            max_file_mb = args.get("max_file_mb", 50)
            # 支持通过 .env 统一配置默认值
            if "max_file_mb" not in args:
                try:
                    max_file_mb = float(os.getenv("MCP_CONVERT_MAX_FILE_MB", str(max_file_mb)))
                except Exception:
                    pass
            download_result = await download_file_from_url(
                url=source_value,
                work_dir=work_dir,
                max_bytes=max_file_mb * 1024 * 1024
            )

            # 将“下载阶段”纳入 attempts（可观测）
            download_attempt = {
                "engine": "url_download",
                "status": "success" if download_result.get("ok") else "error",
                "error_code": download_result.get("error_code"),
                "error_message": download_result.get("error_message"),
                "elapsed_ms": download_result.get("elapsed_ms", 0),
                "timed_out": download_result.get("error_code") == "E_TIMEOUT",
                "exit_code": None,
                "stderr_tail": None,
            }
            result["attempts"].append(download_attempt)

            if not download_result["ok"]:
                result["error_code"] = download_result.get("error_code", "E_URL_DOWNLOAD_FAILED")
                result["error_message"] = download_result.get("error_message", "URL 下载失败")
                ctx.log_error(result["error_code"], result["error_message"])
                ctx.log_complete(success=False)
                clear_current_context()
                return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            file_path = Path(download_result["file_path"])
            ctx.log_file_received(download_result.get("filename", "unknown"), download_result.get("size_bytes", 0))

        elif source_type == "croc_code":
            # croc 接收
            from .croc_receiver import receive_file_via_croc
            timeout_seconds = args.get("croc_timeout_seconds", 120)
            max_file_mb = args.get("max_file_mb", 50)
            if "croc_timeout_seconds" not in args:
                try:
                    timeout_seconds = int(os.getenv("MCP_CONVERT_CROC_TIMEOUT_SECONDS", str(timeout_seconds)))
                except Exception:
                    pass
            if "max_file_mb" not in args:
                try:
                    max_file_mb = float(os.getenv("MCP_CONVERT_MAX_FILE_MB", str(max_file_mb)))
                except Exception:
                    pass
            croc_result = await receive_file_via_croc(
                croc_code=source_value,
                work_dir=work_dir,
                timeout_seconds=timeout_seconds,
                max_file_bytes=max_file_mb * 1024 * 1024
            )

            # 将“接收阶段”纳入 attempts（可观测）
            croc_attempt = {
                "engine": "croc_receive",
                "status": "success" if croc_result.get("ok") else "error",
                "error_code": croc_result.get("error_code"),
                "error_message": croc_result.get("error_message"),
                "elapsed_ms": croc_result.get("elapsed_ms", 0),
                "timed_out": bool(croc_result.get("timed_out")),
                "exit_code": croc_result.get("exit_code"),
                "stderr_tail": croc_result.get("stderr_tail"),
            }
            result["attempts"].append(croc_attempt)

            if croc_result.get("warnings"):
                result["warnings"].extend(croc_result["warnings"])

            if not croc_result["ok"]:
                result["error_code"] = croc_result.get("error_code", "E_CROC_FAILED")
                result["error_message"] = croc_result.get("error_message", "croc 接收失败")
                ctx.log_error(result["error_code"], result["error_message"])
                ctx.log_complete(success=False)
                clear_current_context()
                return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            file_path = Path(croc_result["file_path"])
            ctx.log_file_received(croc_result.get("filename", "unknown"), croc_result.get("size_bytes", 0))

        # 3. 文件类型识别（带 ZIP 安全检查）
        detected_type, security_error = detect_file_type_with_security(file_path)
        result["source_info"] = {
            "filename": file_path.name,
            "size_bytes": file_path.stat().st_size,
            "detected_type": detected_type
        }

        # 检查 ZIP 安全性
        if security_error:
            result["error_code"] = security_error.get("error_code", "E_ZIP_SECURITY_FAILED")
            result["error_message"] = security_error.get("error_message", "ZIP 安全检查失败")
            if "security_stats" in security_error:
                result["source_info"]["security_stats"] = security_error["security_stats"]
            ctx.log_error(result["error_code"], result["error_message"])
            ctx.log_complete(success=False)
            clear_current_context()
            return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        ctx.log_type_detected(detected_type, file_path.suffix.lower())

        # 3.5. 检查是否需要旧格式转换（doc/xls/ppt -> docx/xlsx/pptx）
        from .engines.legacy_office_engine import is_legacy_format, convert_legacy_format

        if is_legacy_format(detected_type):
            ctx.log_event("legacy_convert_start", f"检测到旧格式 {detected_type}，尝试转换")
            legacy_result = await convert_legacy_format(
                file_path=str(file_path),
                detected_type=detected_type,
                work_dir=work_dir
            )

            # 记录旧格式转换尝试
            result["attempts"].append(legacy_result.get("attempt", {}))

            if legacy_result.get("ok"):
                # 转换成功，使用转换后的文件继续
                file_path = Path(legacy_result["converted_path"])
                detected_type = legacy_result["converted_type"]
                result["source_info"]["original_type"] = result["source_info"]["detected_type"]
                result["source_info"]["detected_type"] = detected_type
                result["source_info"]["legacy_converted"] = True
                ctx.log_event("legacy_convert_complete", f"旧格式转换成功: {detected_type}")
            else:
                # 转换失败，根据错误类型决定是否继续
                error_code = legacy_result.get("error_code", "E_LEGACY_CONVERT_FAILED")
                if error_code == "E_SOFFICE_NOT_FOUND":
                    # LibreOffice 未安装，给出明确提示
                    result["error_code"] = error_code
                    result["error_message"] = legacy_result.get("error_message", "LibreOffice 未安装")
                    result["warnings"].append(
                        f"文件格式 {detected_type} 需要 LibreOffice 转换。"
                        "建议安装 LibreOffice 或将文件另存为新格式（docx/xlsx/pptx）。"
                    )
                    ctx.log_error(error_code, result["error_message"])
                    ctx.log_complete(success=False)
                    clear_current_context()
                    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
                else:
                    # 其他转换错误，尝试继续使用 MinerU（MinerU 可能支持部分旧格式）
                    result["warnings"].append(
                        f"旧格式转换失败 ({error_code})，将尝试使用 MinerU 直接处理"
                    )
                    ctx.log_warning(f"旧格式转换失败: {error_code}")

        # 4. 选择引擎
        route = args.get("route", "auto")
        engine = choose_engine(detected_type, file_path.suffix.lower(), route)
        result["engine_used"] = engine
        ctx.log_engine_selected(engine, route)

        # 5. 执行转换
        enable_ocr = args.get("enable_ocr", False)
        language = args.get("language", "ch")
        ctx.log_conversion_start(engine)

        if engine == "pandoc":
            from .engines.pandoc_engine import convert_with_pandoc
            convert_result = await convert_with_pandoc(
                file_path=str(file_path),
                detected_type=detected_type,
                work_dir=work_dir
            )
        elif engine == "mineru":
            from .engines.mineru_engine import convert_with_mineru
            convert_result = await convert_with_mineru(
                file_path=str(file_path),
                enable_ocr=enable_ocr,
                language=language,
                work_dir=work_dir
            )
        elif engine == "excel":
            from .engines.excel_engine import convert_with_excel
            convert_result = await convert_with_excel(
                file_path=str(file_path),
                work_dir=work_dir
            )
        else:
            result["error_code"] = "E_ENGINE_NOT_FOUND"
            result["error_message"] = f"未知引擎: {engine}"
            ctx.log_error(result["error_code"], result["error_message"])
            ctx.log_complete(success=False)
            clear_current_context()
            return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        # 6. 处理转换结果
        result["attempts"].append(convert_result.get("attempt", {}))

        if convert_result.get("ok"):
            result["ok"] = True
            result["markdown_text"] = convert_result.get("markdown_text", "")
            if convert_result.get("output_dir"):
                result["artifacts"]["output_dir"] = convert_result["output_dir"]
            if convert_result.get("files"):
                result["artifacts"]["files"] = convert_result["files"]
            ctx.log_conversion_complete(engine, success=True, markdown_length=len(result["markdown_text"]))
        else:
            result["error_code"] = convert_result.get("error_code", "E_CONVERT_FAILED")
            result["error_message"] = convert_result.get("error_message", "转换失败")
            ctx.log_conversion_complete(engine, success=False)
            ctx.log_error(result["error_code"], result["error_message"])

        # 添加警告
        if convert_result.get("warnings"):
            result["warnings"].extend(convert_result["warnings"])
            for warning in convert_result["warnings"]:
                ctx.log_warning(warning)

        # 记录请求完成
        ctx.log_complete(success=result["ok"])

    except Exception as e:
        result["error_code"] = "E_INTERNAL_ERROR"
        result["error_message"] = str(e)
        result["attempts"].append({
            "engine": "unknown",
            "status": "error",
            "error_message": traceback.format_exc()
        })
        ctx.log_error(result["error_code"], str(e))
        ctx.log_complete(success=False)
    finally:
        clear_current_context()

    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def handle_get_supported_formats() -> list[types.TextContent]:
    """返回支持的格式和路由策略。"""
    import json

    formats = {
        "pandoc": {
            "description": "Pandoc 引擎 - 适合结构化文本转换",
            "extensions": ["docx", "html", "txt", "md", "rst", "latex", "epub", "odt"],
            "features": ["高质量文本转换", "保留格式结构", "支持图片提取"]
        },
        "mineru": {
            "description": "MinerU 引擎 - 适合 PDF/图片/PPT 解析",
            "extensions": ["pdf", "png", "jpg", "jpeg", "pptx", "ppt", "doc", "docx"],
            "features": ["OCR 识别", "版式文档解析", "扫描件处理"]
        },
        "excel": {
            "description": "Excel 引擎 - 适合表格转换",
            "extensions": ["xlsx", "csv", "xls"],
            "features": ["多 Sheet 支持", "表格转 Markdown"]
        }
    }

    routing_rules = {
        "auto": "根据文件类型自动选择最佳引擎",
        "pdf": "MinerU (OCR 支持)",
        "docx": "Pandoc 优先，复杂排版可选 MinerU",
        "xlsx/csv": "Excel 引擎",
        "png/jpg": "MinerU (需要 OCR)",
        "pptx": "MinerU",
        "html/txt/md": "Pandoc"
    }

    return [types.TextContent(
        type="text",
        text=json.dumps({
            "formats": formats,
            "routing_rules": routing_rules,
            "supported_extensions": SUPPORTED_EXTENSIONS
        }, ensure_ascii=False, indent=2)
    )]


async def handle_health() -> list[types.TextContent]:
    """检查服务健康状态。"""
    import json
    import subprocess

    health = {
        "status": "ok",
        "engines": {}
    }

    # 检查 Pandoc
    try:
        result = subprocess.run(
            ["pandoc", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.split("\n")[0]
            health["engines"]["pandoc"] = {"available": True, "version": version}
        else:
            health["engines"]["pandoc"] = {"available": False, "error": "返回码非零"}
    except FileNotFoundError:
        health["engines"]["pandoc"] = {"available": False, "error": "未安装"}
    except Exception as e:
        health["engines"]["pandoc"] = {"available": False, "error": str(e)}

    # 检查 MinerU 配置
    mineru_api_key = os.getenv("MINERU_API_KEY", "")
    use_local_api = os.getenv("USE_LOCAL_API", "").lower() in ["true", "1", "yes"]
    local_api_base = os.getenv("LOCAL_MINERU_API_BASE", "http://localhost:8080")

    if mineru_api_key:
        health["engines"]["mineru"] = {
            "available": True,
            "mode": "remote",
            "api_key_set": True
        }
    elif use_local_api:
        health["engines"]["mineru"] = {
            "available": True,
            "mode": "local",
            "api_base": local_api_base
        }
    else:
        health["engines"]["mineru"] = {
            "available": False,
            "error": "未配置 API Key 或本地 API"
        }

    # 检查 Excel 依赖
    try:
        import openpyxl
        health["engines"]["excel"] = {"available": True, "library": "openpyxl"}
    except ImportError:
        health["engines"]["excel"] = {"available": False, "error": "openpyxl 未安装"}

    # 检查 croc
    try:
        result = subprocess.run(
            ["croc", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            health["croc"] = {"available": True, "version": result.stdout.strip()}
        else:
            health["croc"] = {"available": False, "error": "返回码非零"}
    except FileNotFoundError:
        health["croc"] = {"available": False, "error": "未安装"}
    except Exception as e:
        health["croc"] = {"available": False, "error": str(e)}

    # 总体状态
    if not any(e.get("available") for e in health["engines"].values()):
        health["status"] = "degraded"

    return [types.TextContent(
        type="text",
        text=json.dumps(health, ensure_ascii=False, indent=2)
    )]


async def main():
    """运行 MCP Server。"""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcp-convert-router",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
