"""
title: File to Markdown Tool
author: MCP Convert Router Team
author_url: https://github.com/infiniscale/mcp_server
version: 1.0.0
license: MIT
description: Convert files to Markdown using MCP Convert Router service
requirements: httpx
"""

from pydantic import BaseModel, Field
from typing import Optional
import httpx
import base64
import os
import glob


class Tools:
    class Valves(BaseModel):
        mcp_url: str = Field(
            default="http://211.93.0.206:10029/mcp/",
            description="MCP Convert Router server URL (JSON-RPC endpoint)"
        )
        upload_dir: str = Field(
            default="/app/backend/data/uploads",
            description="OpenWebUI file upload directory"
        )
        timeout_seconds: int = Field(
            default=600,
            description="Timeout for MCP processing in seconds"
        )

    def __init__(self):
        self.valves = self.Valves()
        print("[FileToMD] Tool initialized")

    def convert_file(
        self,
        file_id: str,
        enable_ocr: bool = False,
        language: str = "ch",
        __user__: Optional[dict] = None
    ) -> str:
        """
        Convert uploaded files to Markdown format.

        Call this tool when:
        - User uploads a file (PDF, DOCX, DOC, image, etc.)
        - User asks to convert, extract, or read the file
        - User wants to see the file content

        IMPORTANT: The file_id is the UUID of the uploaded file.
        You can find it in the file metadata. For example:
        - If user uploaded a file, look for the file's id/uuid in the conversation context
        - The file_id looks like: "2846f51d-5ee5-4c87-8452-d52ebd70b3b4"
        - DO NOT pass Chinese text or descriptions as file_id

        :param file_id: The UUID of the uploaded file (e.g., "2846f51d-5ee5-4c87-8452-d52ebd70b3b4")
        :param enable_ocr: Enable OCR for scanned documents or images (default: False)
        :param language: OCR language - "ch" for Chinese, "en" for English (default: "ch")
        :return: The file content in Markdown format
        """

        try:
            print(f"[FileToMD] Converting file {file_id}")

            # Download file from local filesystem
            file_content, filename = self._download_file(file_id)
            print(f"[FileToMD] Downloaded {len(file_content)} bytes, filename: {filename}")

            # Convert to Base64
            file_b64 = base64.b64encode(file_content).decode()
            print(f"[FileToMD] Base64 length: {len(file_b64)}")

            # Call MCP
            print(f"[FileToMD] Calling MCP at {self.valves.mcp_url}...")
            markdown = self._call_mcp(file_b64, filename, enable_ocr, language)
            print(f"[FileToMD] Success, got {len(markdown)} chars")

            return markdown

        except Exception as e:
            error_msg = f"转换失败: {str(e)}"
            print(f"[FileToMD] Error: {error_msg}")
            import traceback
            traceback.print_exc()
            return error_msg

    def _download_file(self, file_id: str) -> tuple:
        """Download file from Open WebUI - uses local filesystem"""

        upload_dir = self.valves.upload_dir
        print(f"[FileToMD] Looking for file_id: {file_id}")

        # Use glob to find files starting with file_id
        pattern = f"{upload_dir}/{file_id}_*"
        matches = glob.glob(pattern)

        if matches:
            file_path = matches[0]
            filename = os.path.basename(file_path)
            # Extract original filename (remove file_id prefix)
            original_name = filename.split("_", 1)[1] if "_" in filename else filename
            print(f"[FileToMD] Found file: {file_path}")

            with open(file_path, 'rb') as f:
                content = f.read()
            print(f"[FileToMD] Read {len(content)} bytes from disk")
            return content, original_name

        # If no match found, list directory for debugging
        try:
            files = os.listdir(upload_dir)
            print(f"[FileToMD] No match found. Directory contains {len(files)} files:")
            for f in files[:10]:
                if file_id in f:
                    print(f"  - {f} (contains file_id!)")
                else:
                    print(f"  - {f}")
        except Exception as e:
            print(f"[FileToMD] Error listing directory: {e}")

        raise Exception(f"文件不存在。查找模式: {pattern}")

    def _call_mcp(self, file_content_b64: str, filename: str, enable_ocr: bool, language: str) -> str:
        """Call MCP Convert Router service via JSON-RPC"""
        import json

        with httpx.Client(timeout=self.valves.timeout_seconds) as client:
            # Use JSON-RPC format to call MCP
            # Important: Must include Accept header for SSE response
            response = client.post(
                self.valves.mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "tool-call",
                    "method": "tools/call",
                    "params": {
                        "name": "convert_to_markdown",
                        "arguments": {
                            "file_content_base64": file_content_b64,
                            "filename": filename,
                            "enable_ocr": enable_ocr,
                            "language": language,
                            "return_mode": "text"
                        }
                    }
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
            )

            print(f"[FileToMD] MCP response status: {response.status_code}")

            if response.status_code != 200:
                raise Exception(f"MCP 错误 (HTTP {response.status_code}): {response.text[:200]}")

            # Parse SSE response format
            # Response format: "event: message\r\ndata: {...json...}"
            response_text = response.text
            print(f"[FileToMD] Raw response length: {len(response_text)}")

            # Extract JSON from SSE data line
            json_data = None
            for line in response_text.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    json_str = line[5:].strip()  # Remove "data:" prefix
                    json_data = json.loads(json_str)
                    break

            if not json_data:
                # Try parsing as direct JSON (fallback)
                try:
                    json_data = json.loads(response_text)
                except:
                    raise Exception(f"无法解析 MCP 响应: {response_text[:200]}")

            print(f"[FileToMD] Parsed JSON-RPC response")

            # Check for JSON-RPC error
            if "error" in json_data:
                error_msg = json_data["error"].get("message", "未知错误")
                raise Exception(f"MCP 错误: {error_msg}")

            # Extract content from result
            result = json_data.get("result", {})
            content = result.get("content", [])
            if not content:
                raise Exception("MCP 返回空内容")

            # Get the text content
            text = content[0].get("text", "")
            if not text:
                raise Exception("MCP 返回的 text 为空")

            return text
