"""
title: File to Markdown Converter
author: MCP Convert Router Team
author_url: https://github.com/infiniscale/mcp_server
version: 1.0.0
license: MIT
description: Prepare uploaded files for Markdown conversion via MCP Convert Router
requirements:
"""

from pydantic import BaseModel, Field
from typing import Optional


class Tools:
    class Valves(BaseModel):
        openwebui_base_url: str = Field(
            default="http://192.168.1.236:22030",
            description="OpenWebUI base URL for constructing file download URLs"
        )

    def __init__(self):
        self.valves = self.Valves()

    def prepare_file_for_conversion(
        self,
        file_id: str,
        enable_ocr: bool = False,
        language: str = "ch",
        __user__: Optional[dict] = None
    ) -> str:
        """
        Prepare an uploaded file for Markdown conversion.

        This tool constructs the file URL and authentication headers needed
        to call the convert_to_markdown tool from MCP Convert Router.

        Call this tool when:
        - User uploads a file (PDF, DOCX, DOC, PPTX, image, etc.)
        - User asks to convert, extract, or read the file content
        - User wants to see the file content as Markdown

        After calling this tool, follow the returned instructions to call
        the convert_to_markdown tool with the prepared parameters.

        :param file_id: The ID of the uploaded file (UUID format, e.g., "f70823a3-5be7-444d-afc5-8dc906ee8494")
        :param enable_ocr: Enable OCR for scanned documents or images (default: False)
        :param language: OCR language - "ch" for Chinese, "en" for English (default: "ch")
        :return: Instructions for calling convert_to_markdown with prepared parameters
        """

        # Validate file_id format
        if not file_id or len(file_id) < 8:
            return "错误：无效的文件 ID。请提供有效的文件 UUID。"

        # Construct file URL
        openwebui_base = self.valves.openwebui_base_url.rstrip("/")
        file_url = f"{openwebui_base}/api/v1/files/{file_id}/content"

        # Get user token for authentication
        user_token = ""
        if __user__ and isinstance(__user__, dict):
            user_token = __user__.get("token", "")

        if not user_token:
            return f"""警告：未能获取用户认证信息。

文件 URL 已准备好，但可能需要手动添加认证头：

请调用 convert_to_markdown 工具进行文件转换：

参数：
- source: {file_url}
- enable_ocr: {str(enable_ocr).lower()}
- language: {language}
- return_mode: text

注意：如果遇到 401 认证错误，请确保 MCP 服务配置了 OPENWEBUI_API_KEY 环境变量。
"""

        # Prepare the instruction for LLM to call convert_to_markdown
        instruction = f"""文件已准备好，请调用 convert_to_markdown 工具进行转换：

参数：
- source: {file_url}
- url_headers: {{"Authorization": "Bearer {user_token}"}}
- enable_ocr: {str(enable_ocr).lower()}
- language: {language}
- return_mode: text

请使用以上参数调用 mcp-convert-router 的 convert_to_markdown 工具。
"""

        return instruction
