"""
title: File to Markdown Converter
author: MCP Convert Router Team
author_url: https://github.com/infiniscale/mcp_server
version: 2.3.0
license: MIT
description: Convert files to Markdown using MCP Convert Router service (via URL)
requirements: httpx
"""

import json
import uuid
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        mcp_url: str = Field(
            default="http://<MCP_SERVER_HOST>:<MCP_SERVER_PORT>/mcp/",
            description="MCP Convert Router server URL (JSON-RPC endpoint)"
        )
        openwebui_base_url: str = Field(
            default="http://<OPENWEBUI_HOST>:<OPENWEBUI_PORT>",
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
        file_id: str = "",
        enable_ocr: bool = False,
        language: str = "ch",
        __user__: Optional[dict] = None,
        __files__: Optional[list] = None,
        __messages__: Optional[list] = None,
        __oauth_token__: Optional[dict] = None,
        __event_emitter__: Any = None,
    ) -> str:
        """
        Convert uploaded files to Markdown format via URL download.

        Call this tool when:
        - User uploads a file (PDF, DOCX, DOC, image, etc.)
        - User asks to convert, extract, or read the file
        - User wants to see the file content

        IMPORTANT:
        - You do NOT need to provide file_id manually.
        - This tool will use __files__ (the current message attachments) as the source of truth.
        - If __files__ is missing (e.g., when user clicks Regenerate), it will fall back to the
          latest message in __messages__ that contains files.
        - If multiple files are attached, it will convert all of them.

        :param file_id: (Optional) A file UUID. Ignored when __files__ is present.
        :param enable_ocr: Enable OCR for scanned documents or images (default: False)
        :param language: OCR language - "ch" for Chinese, "en" for English (default: "ch")
        :return: The file content in Markdown format
        """

        try:
            openwebui_base = self.valves.openwebui_base_url.rstrip("/")

            file_infos = self._extract_file_infos(__files__)

            if not file_infos:
                file_infos = self._extract_latest_file_infos_from_messages(__messages__)

            if not file_infos:
                # Backward compatibility: allow explicit file_id when __files__ isn't available.
                candidate = (file_id or "").strip()
                try:
                    candidate = str(uuid.UUID(candidate))
                except Exception:
                    return "错误：未检测到附件文件。请先在对话里上传文件后再调用本工具。"
                file_infos = [{"id": candidate, "name": candidate}]

            url_headers = self._build_url_headers(__user__, __oauth_token__)

            results: list[str] = []
            total = len(file_infos)
            for idx, info in enumerate(file_infos, start=1):
                current_id = info["id"]
                name = info.get("name") or current_id
                await self._emit_status(__event_emitter__, f"开始转换 ({idx}/{total}): {name}")

                file_url = f"{openwebui_base}/api/v1/files/{current_id}/content"
                print(f"[FileToMD-URL] File URL: {file_url}")

                try:
                    markdown = await self._call_mcp(file_url, url_headers, enable_ocr, language)
                    results.append(f"# {name}\n\n{markdown}\n")
                    await self._emit_status(__event_emitter__, f"转换完成 ({idx}/{total}): {name}")
                except Exception as e:
                    results.append(f"# {name}\n\n转换失败: {str(e)}\n")
                    await self._emit_status(__event_emitter__, f"转换失败 ({idx}/{total}): {name}")

            if len(results) == 1:
                return results[0]

            return "\n---\n\n".join(results)

        except Exception as e:
            error_msg = f"转换失败: {str(e)}"
            print(f"[FileToMD-URL] Error: {error_msg}")
            import traceback
            traceback.print_exc()
            return error_msg

    @staticmethod
    async def _emit_status(event_emitter: Any, message: str) -> None:
        if not callable(event_emitter):
            return
        try:
            payload = {"type": "status", "data": {"message": message}}
            maybe_awaitable = event_emitter(payload)
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable
        except Exception:
            return

    def _build_url_headers(self, user: Optional[dict], oauth_token: Optional[dict]) -> dict:
        # Prefer OAuth access token when available.
        if oauth_token and isinstance(oauth_token, dict):
            access_token = (oauth_token.get("access_token") or "").strip()
            if access_token:
                return {"Authorization": f"Bearer {access_token}"}

        # Fallback: OpenWebUI may inject a token in __user__ for some auth modes.
        if user and isinstance(user, dict):
            user_token = (user.get("token") or "").strip()
            if user_token:
                return {"Authorization": f"Bearer {user_token}"}

        # Fallback: static API key via tool valve.
        if (self.valves.openwebui_api_key or "").strip():
            return {"Authorization": f"Bearer {self.valves.openwebui_api_key.strip()}"}

        return {}

    @staticmethod
    def _normalize_mcp_url(mcp_url: str) -> str:
        """
        Ensure trailing slash to avoid 307 redirects (e.g. POST /mcp -> /mcp/).
        """
        url = (mcp_url or "").strip()
        if not url:
            return url
        return url.rstrip("/") + "/"

    @staticmethod
    def _extract_file_infos(files: Optional[list]) -> list[dict]:
        infos: list[dict] = []

        if not files or not isinstance(files, list):
            return infos

        for item in files:
            if not isinstance(item, dict):
                continue

            # Common OpenWebUI shape:
            # {"type":"file","file":{...,"id":...,"filename":...,"meta":{"name":...}},"id":...,"name":...}
            file_obj = item.get("file") if isinstance(item.get("file"), dict) else {}

            candidate_id = (
                file_obj.get("id")
                or item.get("id")
                or item.get("file_id")
            )
            candidate_name = (
                file_obj.get("filename")
                or (file_obj.get("meta") or {}).get("name")
                or item.get("name")
                or item.get("filename")
            )

            try:
                file_uuid = str(uuid.UUID(str(candidate_id).strip()))
            except Exception:
                continue

            infos.append(
                {
                    "id": file_uuid,
                    "name": str(candidate_name) if candidate_name else file_uuid,
                }
            )

        return infos

    @classmethod
    def _extract_latest_file_infos_from_messages(cls, messages: Optional[list]) -> list[dict]:
        """
        Regenerate may omit __files__. Recover by scanning __messages__ from newest to oldest
        and returning the first message that contains attached files.
        """
        if not messages or not isinstance(messages, list):
            return []

        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            files = msg.get("files")
            infos = cls._extract_file_infos(files) if isinstance(files, list) else []
            if infos:
                return infos

        return []

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
        mcp_url = self._normalize_mcp_url(self.valves.mcp_url)

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

            async with client.stream("POST", mcp_url, json=payload, headers=headers) as response:
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
