"""
title: File to Markdown Converter
author: MCP Convert Router Team
author_url: https://github.com/infiniscale/mcp_server
version: 2.1.1
license: MIT
description: Convert files to Markdown using MCP Convert Router service (via URL)
requirements: httpx
"""

from pydantic import BaseModel, Field
from typing import Optional
import json
import uuid
import httpx


class Tools:
    class Valves(BaseModel):
        mcp_url: str = Field(
            default="http://211.93.0.206:10029/mcp/",
            description="MCP Convert Router server URL (JSON-RPC endpoint)"
        )
        openwebui_base_url: str = Field(
            default="http://192.168.1.236:22030",
            description="OpenWebUI base URL for constructing file download URLs"
        )
        openwebui_api_key: str = Field(
            default="",
            description="Optional OpenWebUI API key (used if __user__.token is missing)"
        )
        timeout_seconds: int = Field(
            default=600,
            description="Timeout for MCP processing in seconds"
        )

    def __init__(self):
        self.valves = self.Valves()
        print("[FileToMD-URL] Tool initialized")

    async def convert_file(
        self,
        file_id: str,
        enable_ocr: bool = False,
        language: str = "ch",
        __user__: Optional[dict] = None
    ) -> str:
        """
        Convert uploaded files to Markdown format via URL download.

        Call this tool when:
        - User uploads a file (PDF, DOCX, DOC, image, etc.)
        - User asks to convert, extract, or read the file
        - User wants to see the file content

        IMPORTANT: The file_id is the UUID of the uploaded file.
        You can find it in the file metadata. For example:
        - If user uploaded a file, look for the file's id/uuid in the conversation context
        - The file_id looks like: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        - DO NOT pass Chinese text or descriptions as file_id

        :param file_id: The UUID of the uploaded file (e.g., "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        :param enable_ocr: Enable OCR for scanned documents or images (default: False)
        :param language: OCR language - "ch" for Chinese, "en" for English (default: "ch")
        :return: The file content in Markdown format
        """

        try:
            print(f"[FileToMD-URL] Converting file {file_id}")

            # Validate file_id
            file_id = (file_id or "").strip()
            try:
                file_id = str(uuid.UUID(file_id))
            except Exception:
                return "错误：无效的 file_id。请从当前对话的附件信息中复制文件 UUID（形如 xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx）。"

            # Construct file URL
            openwebui_base = self.valves.openwebui_base_url.rstrip("/")
            file_url = f"{openwebui_base}/api/v1/files/{file_id}/content"
            print(f"[FileToMD-URL] File URL: {file_url}")

            # Get user token for authentication
            user_token = ""
            if __user__ and isinstance(__user__, dict):
                user_token = __user__.get("token", "")
            print(f"[FileToMD-URL] User token available: {bool(user_token)}")

            # Build url_headers
            url_headers = {}
            if user_token:
                url_headers["Authorization"] = f"Bearer {user_token}"
            elif self.valves.openwebui_api_key:
                url_headers["Authorization"] = f"Bearer {self.valves.openwebui_api_key}"

            # Call MCP
            print(f"[FileToMD-URL] Calling MCP at {self.valves.mcp_url}...")
            markdown = await self._call_mcp(file_url, url_headers, enable_ocr, language)
            print(f"[FileToMD-URL] Success, got {len(markdown)} chars")

            return markdown

        except Exception as e:
            error_msg = f"转换失败: {str(e)}"
            print(f"[FileToMD-URL] Error: {error_msg}")
            import traceback
            traceback.print_exc()
            return error_msg

    async def _call_mcp(self, file_url: str, url_headers: dict, enable_ocr: bool, language: str) -> str:
        """Call MCP Convert Router service via JSON-RPC with URL source"""
        # Build arguments
        arguments = {
            "source": file_url,
            "enable_ocr": enable_ocr,
            "language": language,
            "return_mode": "text"
        }

        # Add url_headers if available
        if url_headers:
            arguments["url_headers"] = url_headers

        timeout = httpx.Timeout(self.valves.timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            payload = {
                "jsonrpc": "2.0",
                "id": "tool-call",
                "method": "tools/call",
                "params": {
                    "name": "convert_to_markdown",
                    "arguments": arguments,
                },
            }

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }

            async with client.stream("POST", self.valves.mcp_url, json=payload, headers=headers) as response:
                print(f"[FileToMD-URL] MCP response status: {response.status_code}")

                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise Exception(f"MCP 错误 (HTTP {response.status_code}): {body[:200]}")

                content_type = (response.headers.get("Content-Type") or "").lower()
                if "text/event-stream" not in content_type:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    try:
                        json_data = json.loads(body)
                    except Exception:
                        raise Exception(f"无法解析 MCP 响应: {body[:200]}")
                    return self._extract_markdown(json_data)

                last_data = None
                async for line in response.aiter_lines():
                    line = (line or "").strip()
                    if not line.startswith("data:"):
                        continue

                    json_str = line[5:].strip()
                    if not json_str or json_str == "[DONE]":
                        continue

                    last_data = json_str
                    try:
                        json_data = json.loads(json_str)
                    except Exception:
                        continue

                    if isinstance(json_data, dict) and "error" in json_data:
                        error_msg = json_data["error"].get("message", "未知错误")
                        raise Exception(f"MCP 错误: {error_msg}")

                    if isinstance(json_data, dict) and "result" in json_data:
                        return self._extract_markdown(json_data)

                raise Exception(f"MCP 未返回结果（最后一条 data: {str(last_data)[:120]}）")

    @staticmethod
    def _extract_markdown(json_data: dict) -> str:
        if "error" in json_data:
            error_msg = json_data["error"].get("message", "未知错误")
            raise Exception(f"MCP 错误: {error_msg}")

        result = json_data.get("result", {})
        content = result.get("content", [])
        if not content:
            raise Exception("MCP 返回空内容")

        text = content[0].get("text", "")
        if not text:
            raise Exception("MCP 返回的 text 为空")

        return text
