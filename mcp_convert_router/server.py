"""MCP Convert Router Server - 统一文件转 Markdown 服务。

提供 convert_to_markdown 工具，支持多种输入方式和多引擎路由。

推荐启动方式：
  - `python -m mcp_convert_router.server`
"""

import argparse
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
from .logging_utils import RequestContext, set_current_context, clear_current_context, logger

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
                "【服务端·转换服务工具】将文件转换为 Markdown 格式。\n\n"
                "## 智能判断流程（推荐）\n"
                "1. 先调用 health 工具检查服务端引擎状态\n"
                "2. 若有 URL → 直接 source=url\n"
                "3. 若文件在客户端本地 → 先用客户端的 croc_send 发送，再用返回的 code 调用本工具\n"
                "4. 若引擎不可用 → 本工具会返回 next_action 建议\n\n"
                "## 快速使用\n"
                "只需填写 source 参数，系统自动识别类型：\n"
                "- 服务端本地文件: source='/data/report.pdf'\n"
                "- 网络文件: source='https://example.com/doc.pdf'\n"
                "- 跨机器传输: source='78ayx1'（Croc Code，需先在客户端调用 croc_send 获取）\n\n"
                "## 跨机器传输流程\n"
                "当文件在客户端本地时：\n"
                "1. 客户端调用 croc_send(path='/local/file.pdf') → 获取 code\n"
                "2. 本工具调用 convert_to_markdown(source=code) → 服务端接收并转换\n\n"
                "## 支持的格式\n"
                "pdf, docx, pptx, xlsx, csv, txt, md, html, png, jpg 等"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    # === 推荐用法：统一输入 ===
                    "source": {
                        "type": "string",
                        "description": (
                            "【推荐】文件来源，自动识别类型。支持三种格式：\n"
                            "- 本地路径: /path/to/file.pdf\n"
                            "- URL: https://example.com/file.pdf\n"
                            "- Croc Code: 7928-alpha-bravo（需先在远程机器调用 croc_send 获取）"
                        )
                    },
                    # === 兼容旧参数（仍可使用）===
                    "file_path": {
                        "type": "string",
                        "description": "服务端本地文件路径（可用 source 代替）"
                    },
                    "url": {
                        "type": "string",
                        "description": "远端文件 URL（可用 source 代替）"
                    },
                    "croc_code": {
                        "type": "string",
                        "description": "Croc 传输码（可用 source 代替）。需先在远程机器调用 croc_send 获取"
                    },
                    # === 常用参数 ===
                    "enable_ocr": {
                        "type": "boolean",
                        "default": False,
                        "description": "启用 OCR（扫描件/图片需要）"
                    },
                    # === 高级参数（通常无需设置）===
                    "language": {
                        "type": "string",
                        "default": "ch",
                        "description": "OCR 语言（ch=中文, en=英文）"
                    },
                    "page_ranges": {
                        "type": "string",
                        "description": "页码范围（仅 MinerU）。例如: '2,4-6'"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "自定义输出目录"
                    },
                    "return_mode": {
                        "type": "string",
                        "enum": ["text", "path", "both"],
                        "default": "text",
                        "description": "返回模式"
                    },
                    "max_file_mb": {
                        "type": "number",
                        "default": 50,
                        "description": "最大文件大小（MB）"
                    },
                    "croc_timeout_seconds": {
                        "type": "number",
                        "default": 300,
                        "description": "Croc 接收超时（秒）"
                    },
                    "url_headers": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": (
                            "可选的 HTTP 请求头（用于需要认证的 URL）。\n"
                            "例如: {\"Authorization\": \"Bearer sk-xxx\"}\n"
                            "注意：请勿在日志中暴露敏感信息"
                        )
                    },
                    # === OpenWebUI 文件上传支持 ===
                    "__files__": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "filename": {"type": "string"},
                                "url": {"type": "string"},
                                "type": {"type": "string"}
                            }
                        },
                        "description": (
                            "OpenWebUI 上传的文件列表（由 OpenWebUI 自动填充）。\n"
                            "每个文件包含 id、filename、url、type 字段。\n"
                            "工具会自动从第一个文件的 URL 下载文件。"
                        )
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
            description=(
                "【服务端·状态检查工具】检查服务端引擎可用性。\n\n"
                "## 推荐使用场景\n"
                "在调用 convert_to_markdown 前先调用此工具，了解服务端能力：\n"
                "- 若 MinerU 可用 → 可处理 PDF/图片/PPT\n"
                "- 若 MinerU 不可用 → PDF 等文件需通过 croc 传输到其他服务器\n"
                "- 若 Pandoc 可用 → 可处理 docx/html/txt 等\n\n"
                "## 返回信息\n"
                "- engines: 各引擎状态\n"
                "- capabilities: 当前可处理的文件类型\n"
                "- suggestions: 根据状态给出的操作建议"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "probe": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否对 MinerU 的 api_base 做一次网络连通性探测（best-effort，不上传文件）"
                    },
                    "probe_timeout_seconds": {
                        "type": "number",
                        "default": 5,
                        "description": "探测超时（秒）"
                    }
                },
                "additionalProperties": False
            }
        )
    ]


def _generate_next_action(error_code: str, engine: str, source_type: str) -> Optional[Dict[str, Any]]:
    """根据错误类型生成下一步行动建议。

    Args:
        error_code: 错误码
        engine: 当前使用的引擎
        source_type: 输入来源类型 (file_path, url, croc_code)

    Returns:
        dict: 下一步行动建议，包含 tool, reason, instruction 等字段
    """
    # MinerU 未配置：建议使用 croc 传输到配置了 MinerU 的服务器
    if error_code == "E_MINERU_NOT_CONFIGURED":
        return {
            "tool": "croc_send",
            "mcp": "filesystem（客户端）",
            "reason": "当前服务端 MinerU 未配置，无法处理 PDF/图片等文件",
            "instruction": (
                "请在客户端执行以下步骤：\n"
                "1. 调用 croc_send(path='文件路径') 发送文件\n"
                "2. 获取返回的 code\n"
                "3. 使用 code 调用配置了 MinerU 的服务端 convert_to_markdown(source=code)"
            ),
            "alternative": "或者提供文件的公网 URL，使用 source=url 方式转换"
        }

    # MinerU 超时
    if error_code == "E_TIMEOUT" and engine == "mineru":
        return {
            "tool": "convert_to_markdown",
            "reason": "MinerU 处理超时，可能是文件过大或服务繁忙",
            "instruction": (
                "建议：\n"
                "1. 使用 page_ranges 参数指定部分页面（如 '1-10'）\n"
                "2. 稍后重试\n"
                "3. 检查文件大小是否超过限制"
            )
        }

    # MinerU API 错误
    if error_code in ("E_MINERU_API_ERROR", "E_MINERU_FAILED"):
        return {
            "tool": "health",
            "reason": "MinerU 服务返回错误",
            "instruction": (
                "请先调用 health 工具检查服务状态，确认：\n"
                "1. MinerU API Key 是否有效\n"
                "2. 服务是否可用\n"
                "3. 文件格式是否支持"
            )
        }

    # 文件不存在（本地路径模式）
    if error_code == "E_FILE_NOT_FOUND" and source_type == "file_path":
        return {
            "tool": "croc_send",
            "mcp": "filesystem（客户端）",
            "reason": "服务端未找到指定文件，文件可能在客户端本地",
            "instruction": (
                "如果文件在客户端本地：\n"
                "1. 调用客户端的 croc_send(path='本地文件路径')\n"
                "2. 将返回的 code 传给 convert_to_markdown(source=code)"
            )
        }

    return None


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
        return await handle_health(arguments or {})
    else:
        raise ValueError(f"Unknown tool: {name}")


async def handle_convert_to_markdown(args: Dict[str, Any]) -> list[types.TextContent]:
    """处理 convert_to_markdown 工具调用。"""
    import json

    # 【诊断日志】记录完整的请求参数
    logger.info(f"[DEBUG] convert_to_markdown 收到的完整参数: {json.dumps(args, ensure_ascii=False, indent=2)}")

    # 【OpenWebUI 文件处理】自动处理 __files__ 参数
    files = args.get("__files__", [])
    if files and not args.get("source"):
        file_info = files[0]

        # OpenWebUI 的 url 字段只是 file_id，需要拼接完整 URL
        file_id = file_info.get("url") or file_info.get("id")

        if file_id:
            # 从环境变量获取 OpenWebUI 基础 URL
            import os
            openwebui_base = os.getenv("OPENWEBUI_BASE_URL", "http://192.168.1.236:22030")
            openwebui_base = openwebui_base.rstrip("/")  # 移除末尾斜杠

            # 拼接完整的文件下载 URL
            file_url = f"{openwebui_base}/api/v1/files/{file_id}/content"

            logger.info(f"[OpenWebUI] 检测到上传文件，file_id: {file_id}")
            logger.info(f"[OpenWebUI] 拼接的文件 URL: {file_url}")

            args["source"] = file_url

            # 添加认证头（如果配置了 API Key）
            openwebui_api_key = os.getenv("OPENWEBUI_API_KEY", "")
            if openwebui_api_key and not args.get("url_headers"):
                args["url_headers"] = {
                    "Authorization": f"Bearer {openwebui_api_key}"
                }
                logger.info(f"[OpenWebUI] 已添加认证头")

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

            # 提取 url_headers
            url_headers = args.get("url_headers")
            if url_headers and not isinstance(url_headers, dict):
                result["error_code"] = "E_VALIDATION_FAILED"
                result["error_message"] = "url_headers 必须是对象类型"
                ctx.log_error(result["error_code"], result["error_message"])
                ctx.log_complete(success=False)
                clear_current_context()
                return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            download_result = await download_file_from_url(
                url=source_value,
                work_dir=work_dir,
                max_bytes=max_file_mb * 1024 * 1024,
                custom_headers=url_headers
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
            timeout_seconds = args.get("croc_timeout_seconds", 300)
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

        # 4. 自动选择引擎
        engine = choose_engine(detected_type, file_path.suffix.lower())
        result["engine_used"] = engine
        ctx.log_engine_selected(engine, "auto")

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

            # 智能返回：根据错误类型提供下一步行动建议
            result["next_action"] = _generate_next_action(
                error_code=result["error_code"],
                engine=engine,
                source_type=source_type
            )

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


async def handle_health(args: Dict[str, Any]) -> list[types.TextContent]:
    """检查服务健康状态。"""
    import json
    import subprocess
    from pathlib import Path

    import httpx

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
    remote_api_base = os.getenv("MINERU_API_BASE", "https://mineru.net")

    probe = bool(args.get("probe", False))
    probe_timeout_seconds = float(args.get("probe_timeout_seconds", 5))
    running_in_docker = Path("/.dockerenv").exists()

    if mineru_api_key:
        health["engines"]["mineru"] = {
            "available": True,
            "mode": "remote",
            "api_key_set": True,
            "api_base": remote_api_base,
            "running_in_docker": running_in_docker,
        }
    elif use_local_api:
        health["engines"]["mineru"] = {
            "available": True,
            "mode": "local",
            "api_base": local_api_base,
            "running_in_docker": running_in_docker,
        }
    else:
        health["engines"]["mineru"] = {
            "available": False,
            "error": "未配置 API Key 或本地 API"
        }

    # 可选：对 MinerU api_base 做一次网络连通性探测（不上传文件）
    mineru_engine = health["engines"].get("mineru") or {}
    if probe and mineru_engine.get("available") and mineru_engine.get("api_base"):
        api_base = str(mineru_engine.get("api_base") or "").rstrip("/")
        probe_result: Dict[str, Any] = {"ok": False, "api_base": api_base, "timeout_seconds": probe_timeout_seconds}
        try:
            timeout = httpx.Timeout(connect=probe_timeout_seconds, read=probe_timeout_seconds, write=probe_timeout_seconds, pool=probe_timeout_seconds)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(api_base + "/")
            probe_result.update({"ok": True, "status_code": resp.status_code})
        except Exception as e:
            probe_result.update({"ok": False, "error_type": e.__class__.__name__, "error": str(e)})

        # 针对 Docker + localhost 的常见误配置给出提示
        if not probe_result.get("ok"):
            if mineru_engine.get("mode") == "local" and running_in_docker:
                if api_base.startswith("http://localhost") or api_base.startswith("http://127.0.0.1"):
                    probe_result["hint"] = (
                        "检测到容器内 local api_base 指向 localhost；容器内 localhost 指向容器自身。"
                        "若 MinerU 跑在宿主机，请设置 LOCAL_MINERU_API_BASE=http://host.docker.internal:8080，"
                        "或使用同一 docker network / docker-compose。"
                    )
        mineru_engine["probe"] = probe_result

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

    # 能力摘要：当前可处理的文件类型
    capabilities = {
        "can_process": [],
        "cannot_process": []
    }

    if health["engines"].get("pandoc", {}).get("available"):
        capabilities["can_process"].extend(["docx", "html", "txt", "md", "rst", "epub", "odt"])
    else:
        capabilities["cannot_process"].extend(["docx（需 Pandoc）", "html", "txt"])

    if health["engines"].get("mineru", {}).get("available"):
        capabilities["can_process"].extend(["pdf", "png", "jpg", "pptx", "ppt"])
    else:
        capabilities["cannot_process"].extend(["pdf", "png", "jpg", "pptx（需 MinerU）"])

    if health["engines"].get("excel", {}).get("available"):
        capabilities["can_process"].extend(["xlsx", "csv", "xls"])
    else:
        capabilities["cannot_process"].extend(["xlsx", "csv（需 openpyxl）"])

    health["capabilities"] = capabilities

    # 操作建议
    suggestions = []

    if not health["engines"].get("mineru", {}).get("available"):
        suggestions.append({
            "issue": "MinerU 不可用",
            "impact": "无法处理 PDF、图片、PPT 等文件",
            "solution": (
                "方案1: 配置 MINERU_API_KEY 环境变量\n"
                "方案2: 使用客户端 croc_send 将文件传输到配置了 MinerU 的服务器"
            )
        })

    if not health["engines"].get("pandoc", {}).get("available"):
        suggestions.append({
            "issue": "Pandoc 不可用",
            "impact": "无法处理 docx、html、txt 等文本格式",
            "solution": "安装 Pandoc: brew install pandoc (macOS) 或 apt install pandoc (Ubuntu)"
        })

    if not health.get("croc", {}).get("available"):
        suggestions.append({
            "issue": "Croc 不可用",
            "impact": "无法接收跨机器传输的文件",
            "solution": "安装 croc: brew install croc (macOS) 或 apt install croc (Ubuntu)"
        })

    if suggestions:
        health["suggestions"] = suggestions
    else:
        health["suggestions"] = [{"message": "所有引擎正常，可处理所有支持的文件格式"}]

    return [types.TextContent(
        type="text",
        text=json.dumps(health, ensure_ascii=False, indent=2)
    )]


async def main():
    """运行 MCP Server（stdio）。"""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            _init_options(),
        )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-convert-router")
    transport_env = (os.getenv("MCP_TRANSPORT") or "").strip().lower()
    if not transport_env:
        transport_env = "stdio"
    if transport_env in ("http", "streamable", "streamable-http"):
        transport_env = "streamable_http"
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable_http"],
        default=transport_env,
        help="MCP transport. stdio=default, sse=HTTP Server-Sent Events, streamable_http=single HTTP endpoint",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="Host to bind when using --transport sse",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Port to listen on when using --transport sse",
    )
    parser.add_argument(
        "--sse-path",
        default=os.getenv("MCP_SSE_PATH", "/sse"),
        help="SSE endpoint path (GET) when using --transport sse",
    )
    parser.add_argument(
        "--messages-path",
        default=os.getenv("MCP_MESSAGES_PATH", "/messages/"),
        help="Message endpoint path prefix (POST) when using --transport sse",
    )
    parser.add_argument(
        "--http-path",
        default=os.getenv("MCP_HTTP_PATH", "/"),
        help="HTTP endpoint path when using --transport streamable_http (default: /).",
    )
    parser.add_argument(
        "--root-path",
        default=os.getenv("MCP_ROOT_PATH", ""),
        help="External URL path prefix when behind a reverse proxy (e.g. /mcp). Used by SSE endpoint discovery.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved config and exit without starting the server",
    )
    return parser.parse_args(argv)


def _init_options() -> InitializationOptions:
    return InitializationOptions(
        server_name="mcp-convert-router",
        server_version="0.1.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


def _ensure_leading_slash(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return "/"
    return p if p.startswith("/") else f"/{p}"


def _ensure_trailing_slash(path: str) -> str:
    p = _ensure_leading_slash(path)
    return p if p.endswith("/") else f"{p}/"


def _alt_without_trailing_slash(path: str) -> str:
    p = _ensure_leading_slash(path)
    if p == "/":
        return "/"
    return p.rstrip("/")


def _infer_root_path_from_headers(request) -> str:
    # Common reverse-proxy conventions. When present, this avoids needing explicit --root-path.
    for name in ("x-forwarded-prefix", "x-script-name", "x-forwarded-path-prefix"):
        value = request.headers.get(name)
        if value:
            return _alt_without_trailing_slash(value)
    return ""


async def _run_stdio() -> None:
    await main()


async def _run_sse(*, host: str, port: int, sse_path: str, messages_path: str, root_path: str) -> None:
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route
    import uvicorn

    sse_path = _alt_without_trailing_slash(sse_path)
    sse_path_slash = _ensure_trailing_slash(sse_path)

    # The MCP SSE transport publishes an endpoint like "/messages/?session_id=...".
    # Some proxies/clients normalize away the trailing slash, so we mount both.
    messages_path_slash = _ensure_trailing_slash(messages_path)
    messages_path_noslash = _alt_without_trailing_slash(messages_path_slash)

    transport = SseServerTransport(messages_path_slash)

    async def handle_sse(request):
        effective_root_path = root_path or _infer_root_path_from_headers(request)
        scope = dict(request.scope)
        if effective_root_path:
            scope["root_path"] = effective_root_path
        async with transport.connect_sse(scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], _init_options())
        return Response()

    routes = [Route(sse_path, endpoint=handle_sse, methods=["GET"])]
    if sse_path_slash != sse_path:
        routes.append(Route(sse_path_slash, endpoint=handle_sse, methods=["GET"]))

    routes.append(Mount(messages_path_slash, app=transport.handle_post_message))
    if messages_path_noslash != messages_path_slash:
        routes.append(Mount(messages_path_noslash, app=transport.handle_post_message))

    app = Starlette(routes=routes)

    uvicorn_server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info", root_path=root_path)
    )
    await uvicorn_server.serve()


async def _run_streamable_http(*, host: str, port: int, http_path: str, root_path: str) -> None:
    import anyio
    import uvicorn
    from mcp.server.streamable_http import StreamableHTTPServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount

    http_path = _ensure_leading_slash(http_path)

    # Mount at "/" by default so clients posting to the base URL won't 404.
    # If you want to restrict it, set MCP_HTTP_PATH=/mcp and configure the client accordingly.
    transport = StreamableHTTPServerTransport(mcp_session_id=None)
    app = Starlette(routes=[Mount(http_path, app=transport.handle_request)])

    uvicorn_server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info", root_path=root_path)
    )

    async with transport.connect() as streams:
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.run, streams[0], streams[1], _init_options())
            await uvicorn_server.serve()
            tg.cancel_scope.cancel()


def main_cli(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)
    if args.dry_run:
        import json

        print(
            json.dumps(
                {
                    "transport": args.transport,
                    "host": args.host,
                    "port": args.port,
                    "sse_path": args.sse_path,
                    "messages_path": args.messages_path,
                    "http_path": args.http_path,
                    "root_path": args.root_path,
                },
                ensure_ascii=False,
            )
        )
        return
    if args.transport == "stdio":
        asyncio.run(_run_stdio())
        return
    if args.transport == "streamable_http":
        asyncio.run(
            _run_streamable_http(
                host=args.host,
                port=args.port,
                http_path=args.http_path,
                root_path=args.root_path,
            )
        )
        return
    asyncio.run(
        _run_sse(
            host=args.host,
            port=args.port,
            sse_path=args.sse_path,
            messages_path=args.messages_path,
            root_path=args.root_path,
        )
    )


if __name__ == "__main__":
    main_cli()
