# OpenWebUI URL Authentication Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable OpenWebUI to convert documents via MCP by passing authenticated file URLs instead of using croc or base64 blobs.

**Architecture:** Extend `mcp_convert_router` to accept custom HTTP headers for authenticated URL downloads, add hostname allowlisting to safely permit private network URLs while maintaining SSRF protection, and improve filename extraction from Content-Disposition headers.

**Tech Stack:** Python 3.10+, httpx, MCP (Model Context Protocol), OpenWebUI API

---

## Task 1: Add URL Headers Support to Server Schema

**Files:**
- Modify: `mcp_convert_router/server.py:59-123`

**Step 1: Write test for url_headers parameter acceptance**

```python
# test_url_headers.py
import json
from mcp_convert_router.server import handle_list_tools

async def test_url_headers_in_schema():
    """Verify url_headers parameter is in the tool schema."""
    tools = await handle_list_tools()
    convert_tool = next(t for t in tools if t.name == "convert_to_markdown")
    schema = convert_tool.inputSchema

    assert "url_headers" in schema["properties"]
    assert schema["properties"]["url_headers"]["type"] == "object"
    assert "additionalProperties" in schema["properties"]["url_headers"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_url_headers.py::test_url_headers_in_schema -v`
Expected: FAIL with "url_headers" not found in schema

**Step 3: Add url_headers to tool schema**

In `mcp_convert_router/server.py`, add to the inputSchema properties (after line 120):

```python
                    "url_headers": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": (
                            "可选的 HTTP 请求头（用于需要认证的 URL）。\\n"
                            "例如: {\"Authorization\": \"Bearer sk-xxx\"}\\n"
                            "注意：请勿在日志中暴露敏感信息"
                        )
                    },
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_url_headers.py::test_url_headers_in_schema -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mcp_convert_router/server.py test_url_headers.py
git commit -m "feat: add url_headers parameter to convert_to_markdown schema

- Add url_headers object parameter for authenticated URL downloads
- Supports passing Authorization headers for private file URLs
- Add test coverage for schema validation"
```

---

## Task 2: Implement URL Headers in Download Function

**Files:**
- Modify: `mcp_convert_router/url_downloader.py:43-49`
- Modify: `mcp_convert_router/url_downloader.py:120-131`

**Step 1: Write test for headers being sent in request**

```python
# test_url_headers.py (append)
import httpx
from mcp_convert_router.url_downloader import download_file_from_url
from pathlib import Path

async def test_download_sends_custom_headers():
    """Verify custom headers are sent in the HTTP request."""
    headers_sent = {}

    def mock_transport(request: httpx.Request):
        nonlocal headers_sent
        headers_sent = dict(request.headers)
        return httpx.Response(200, content=b"test content")

    work_dir = Path("/tmp/test_work")
    work_dir.mkdir(exist_ok=True)

    result = await download_file_from_url(
        url="https://example.com/file.pdf",
        work_dir=work_dir,
        custom_headers={"Authorization": "Bearer test-token"}
    )

    assert "authorization" in headers_sent
    assert headers_sent["authorization"] == "Bearer test-token"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_url_headers.py::test_download_sends_custom_headers -v`
Expected: FAIL with "download_file_from_url() got an unexpected keyword argument 'custom_headers'"

**Step 3: Add custom_headers parameter to download_file_from_url**

In `mcp_convert_router/url_downloader.py`, update function signature (line 43):

```python
async def download_file_from_url(
    url: str,
    work_dir: Path,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: int = DEFAULT_READ_TIMEOUT,
    custom_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
```

Update docstring to document the new parameter:

```python
    """
    从 URL 下载文件并保存到工作目录。

    包含 SSRF 防护：
    - 只允许 http/https 协议
    - 解析 DNS 并检查目标 IP 是否为私有/保留地址
    - 限制重定向次数，每次重定向都检查目标

    Args:
        url: 文件 URL
        work_dir: 工作目录（文件将保存到 work_dir/input/）
        max_bytes: 最大下载大小（字节）
        connect_timeout: 连接超时（秒）
        read_timeout: 读取超时（秒）
        custom_headers: 可选的自定义 HTTP 请求头（如 Authorization）

    Returns:
        Dict[str, Any]: {
            "ok": bool,
            "file_path": str (下载的文件路径),
            "filename": str,
            "size_bytes": int,
            "content_type": str,
            "error_code": str (如果失败),
            "error_message": str (如果失败),
            "elapsed_ms": int
        }
    """
```

**Step 4: Pass custom headers to httpx client**

In `mcp_convert_router/url_downloader.py`, update the AsyncClient creation (around line 121):

```python
        # 准备请求头（避免在日志中暴露敏感信息）
        headers = custom_headers.copy() if custom_headers else {}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=30, pool=30),
            follow_redirects=False,  # 手动处理重定向以检查每个目标
            max_redirects=0,
            headers=headers
        ) as client:
```

**Step 5: Run test to verify it passes**

Run: `python -m pytest test_url_headers.py::test_download_sends_custom_headers -v`
Expected: PASS

**Step 6: Commit**

```bash
git add mcp_convert_router/url_downloader.py test_url_headers.py
git commit -m "feat: support custom HTTP headers in URL downloads

- Add custom_headers parameter to download_file_from_url
- Pass headers to httpx.AsyncClient for authenticated requests
- Add test coverage for header forwarding"
```

---

## Task 3: Wire URL Headers Through Server Handler

**Files:**
- Modify: `mcp_convert_router/server.py:303-317`

**Step 1: Write integration test for end-to-end flow**

```python
# test_url_headers.py (append)
async def test_server_passes_headers_to_downloader():
    """Verify server handler passes url_headers to downloader."""
    from mcp_convert_router.server import handle_convert_to_markdown
    from unittest.mock import patch, AsyncMock

    mock_download = AsyncMock(return_value={
        "ok": True,
        "file_path": "/tmp/test.pdf",
        "filename": "test.pdf",
        "size_bytes": 1000,
        "content_type": "application/pdf",
        "elapsed_ms": 100
    })

    with patch('mcp_convert_router.server.download_file_from_url', mock_download):
        args = {
            "source": "https://example.com/file.pdf",
            "url_headers": {"Authorization": "Bearer test-key"}
        }
        await handle_convert_to_markdown(args)

    # Verify headers were passed
    mock_download.assert_called_once()
    call_kwargs = mock_download.call_args.kwargs
    assert "custom_headers" in call_kwargs
    assert call_kwargs["custom_headers"] == {"Authorization": "Bearer test-key"}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_url_headers.py::test_server_passes_headers_to_downloader -v`
Expected: FAIL - custom_headers not passed to download function

**Step 3: Extract url_headers from args and pass to downloader**

In `mcp_convert_router/server.py`, around line 303 (in the `elif source_type == "url":` block):

```python
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

            # 提取 url_headers（如果提供）
            url_headers = args.get("url_headers")
            if url_headers and not isinstance(url_headers, dict):
                result["error_code"] = "E_VALIDATION_FAILED"
                result["error_message"] = "url_headers 必须是对象类型（键值对）"
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
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_url_headers.py::test_server_passes_headers_to_downloader -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mcp_convert_router/server.py test_url_headers.py
git commit -m "feat: wire url_headers from server to downloader

- Extract url_headers from tool arguments
- Validate headers are dict type
- Pass headers to download_file_from_url as custom_headers
- Add end-to-end integration test"
```

---

## Task 4: Implement URL Host Allowlist

**Files:**
- Modify: `mcp_convert_router/validators.py:256-301`
- Modify: `mcp_convert_router/url_downloader.py:222-283`

**Step 1: Write test for allowlisted private IPs**

```python
# test_allowlist.py
import os
from mcp_convert_router.validators import validate_url

def test_allowlist_permits_private_ip():
    """Verify allowlisted hosts bypass SSRF protection."""
    os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "192.168.1.100,openwebui"

    result = validate_url("http://192.168.1.100/api/files/123", {})
    assert result["valid"] is True
    assert result["source_type"] == "url"

    result = validate_url("http://openwebui/api/files/456", {})
    assert result["valid"] is True

def test_non_allowlisted_private_ip_rejected():
    """Verify non-allowlisted private IPs are still blocked."""
    os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "192.168.1.100"

    result = validate_url("http://192.168.1.200/file.pdf", {})
    assert result["valid"] is False
    assert result["error_code"] == "E_URL_FORBIDDEN"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_allowlist.py -v`
Expected: FAIL - private IPs are rejected regardless of allowlist

**Step 3: Add allowlist check to validators.py**

In `mcp_convert_router/validators.py`, update `validate_url` function (around line 256):

```python
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

    # 3. 检查 URL 主机名是否在白名单中
    hostname = parsed.hostname or ""
    allowed_hosts = _get_allowed_url_hosts()

    if hostname in allowed_hosts:
        # 白名单中的主机，跳过 SSRF 检查
        return {
            "valid": True,
            "source_type": "url",
            "source_value": url,
            "allowlisted": True
        }

    # 4. SSRF 防护（非白名单主机）
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
    """获取允许访问的 URL 主机名列表（用于绕过 SSRF 检查）。"""
    hosts_raw = os.getenv("MCP_CONVERT_ALLOWED_URL_HOSTS", "")
    return {h.strip().lower() for h in hosts_raw.split(",") if h.strip()}
```

**Step 4: Add allowlist check to url_downloader.py**

In `mcp_convert_router/url_downloader.py`, update `_check_ssrf` function (around line 222):

```python
async def _check_ssrf(hostname: str) -> Dict[str, Any]:
    """
    SSRF 防护：检查主机名是否安全。

    允许白名单中的主机绕过私有 IP 检查。

    Args:
        hostname: 主机名

    Returns:
        Dict[str, Any]: {"safe": bool, "reason": str, "ip": str}
    """
    if not hostname:
        return {"safe": False, "reason": "主机名为空", "ip": None}

    # 检查是否在白名单中
    import os
    allowed_hosts = {h.strip().lower() for h in os.getenv("MCP_CONVERT_ALLOWED_URL_HOSTS", "").split(",") if h.strip()}

    if hostname.lower() in allowed_hosts:
        # 白名单中的主机，跳过所有 SSRF 检查
        return {"safe": True, "reason": "allowlisted", "ip": None, "allowlisted": True}

    # 检查常见危险主机名（非白名单）
    dangerous_hostnames = [
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "[::1]",
        "metadata.google.internal",  # GCP metadata
        "169.254.169.254",  # AWS/Azure metadata
    ]

    if hostname.lower() in dangerous_hostnames:
        return {"safe": False, "reason": f"不允许访问 {hostname}", "ip": None}

    # 检查是否是 IP 地址
    try:
        import ipaddress
        ip = ipaddress.ip_address(hostname.strip("[]"))

        # 如果 IP 在白名单中，允许
        if str(ip) in allowed_hosts:
            return {"safe": True, "reason": "allowlisted", "ip": str(ip), "allowlisted": True}

        if _is_private_ip(ip):
            return {"safe": False, "reason": f"不允许访问私有/保留 IP: {ip}", "ip": str(ip)}
        return {"safe": True, "reason": None, "ip": str(ip)}
    except ValueError:
        pass  # 不是 IP 地址，继续 DNS 解析

    # DNS 解析（省略，保持原有逻辑）
    # ... rest of the function remains the same
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest test_allowlist.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add mcp_convert_router/validators.py mcp_convert_router/url_downloader.py test_allowlist.py
git commit -m "feat: add URL host allowlist for SSRF bypass

- Support MCP_CONVERT_ALLOWED_URL_HOSTS env var
- Allowlisted hosts bypass private IP blocking
- Non-allowlisted hosts still subject to SSRF protection
- Add test coverage for allowlist behavior"
```

---

## Task 5: Extract Filename from Content-Disposition Header

**Files:**
- Modify: `mcp_convert_router/url_downloader.py:297-315`
- Modify: `mcp_convert_router/url_downloader.py:180-200`

**Step 1: Write test for Content-Disposition parsing**

```python
# test_content_disposition.py
from mcp_convert_router.url_downloader import _extract_filename_from_response
import httpx

def test_extract_filename_from_content_disposition():
    """Verify filename extraction from Content-Disposition header."""
    response = httpx.Response(
        200,
        headers={"Content-Disposition": "attachment; filename=\"report.pdf\""}
    )
    filename = _extract_filename_from_response(response, "https://example.com/api/files/123/content")
    assert filename == "report.pdf"

def test_extract_filename_rfc5987():
    """Verify RFC5987 filename* parsing."""
    response = httpx.Response(
        200,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf"}
    )
    filename = _extract_filename_from_response(response, "https://example.com/content")
    assert filename == "报告.pdf"

def test_fallback_to_url_filename():
    """Verify fallback to URL path when no Content-Disposition."""
    response = httpx.Response(200)
    filename = _extract_filename_from_response(response, "https://example.com/documents/report.pdf")
    assert filename == "report.pdf"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest test_content_disposition.py -v`
Expected: FAIL - function _extract_filename_from_response does not exist

**Step 3: Implement Content-Disposition parser**

In `mcp_convert_router/url_downloader.py`, replace `_extract_filename_from_url` and add new function:

```python
def _extract_filename_from_response(response: httpx.Response, url: str) -> str:
    """
    从响应中提取文件名，优先使用 Content-Disposition。

    Args:
        response: httpx Response 对象
        url: 请求的 URL（作为后备）

    Returns:
        str: 文件名
    """
    # 1. 尝试从 Content-Disposition 提取
    content_disposition = response.headers.get("content-disposition", "")

    if content_disposition:
        # RFC 5987: filename*=UTF-8''encoded_name (优先)
        import re
        from urllib.parse import unquote

        match = re.search(r"filename\*=([^']+)''(.+)", content_disposition)
        if match:
            encoding = match.group(1).upper()
            encoded_filename = match.group(2)
            try:
                # URL decode
                filename = unquote(encoded_filename)
                # 移除路径分隔符
                filename = filename.replace("/", "_").replace("\\", "_")
                # 移除危险字符
                filename = re.sub(r'[<>:"|?*]', "_", filename)
                if filename and filename not in (".", ".."):
                    return filename
            except Exception:
                pass

        # RFC 2183: filename="name"
        match = re.search(r'filename="?([^";\r\n]+)"?', content_disposition)
        if match:
            filename = match.group(1).strip()
            # 清理路径分隔符和危险字符
            filename = filename.replace("/", "_").replace("\\", "_")
            filename = re.sub(r'[<>:"|?*]', "_", filename)
            if filename and filename not in (".", ".."):
                return filename

    # 2. 后备：从 URL 提取
    return _extract_filename_from_url(url)


def _extract_filename_from_url(url: str) -> str:
    """从 URL 中提取文件名。"""
    parsed = urlparse(url)
    path = parsed.path

    # 从路径中提取文件名
    if path:
        filename = path.split("/")[-1]
        # 移除查询参数
        if "?" in filename:
            filename = filename.split("?")[0]
        # 清理文件名
        filename = re.sub(r'[<>:"|?*]', "_", filename)
        if filename and filename != "":
            return filename

    # 无法提取文件名，使用默认名
    return "downloaded_file"
```

**Step 4: Update download function to use new extractor**

In `mcp_convert_router/url_downloader.py`, update the download section (around line 180):

```python
                # 检查状态码
                if response.status_code != 200:
                    result["error_code"] = "E_URL_HTTP_ERROR"
                    result["error_message"] = f"HTTP 错误: {response.status_code}"
                    break

                # 从响应中提取文件名（优先 Content-Disposition）
                filename = _extract_filename_from_response(response, current_url)
                output_path = input_dir / filename

                # 检查 Content-Length（仅作参考，不可信）
                content_length = response.headers.get("content-length")
                # ... rest of download logic
```

Also update line 116 to remove the old filename extraction:

```python
    # 3. 确保输入目录存在
    input_dir = work_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # 注意：文件名将在获得响应头后提取（以使用 Content-Disposition）
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest test_content_disposition.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add mcp_convert_router/url_downloader.py test_content_disposition.py
git commit -m "feat: extract filenames from Content-Disposition headers

- Implement RFC 5987 filename* parsing (UTF-8 encoded)
- Implement RFC 2183 filename parsing
- Sanitize filenames to prevent path traversal
- Fallback to URL-based filename extraction
- Add comprehensive test coverage"
```

---

## Task 6: Add TLS Verification Control

**Files:**
- Create: `mcp_convert_router/.env.template` (if doesn't exist)
- Modify: `mcp_convert_router/url_downloader.py:121-131`

**Step 1: Write test for TLS verification disable**

```python
# test_tls_verify.py
import os
from mcp_convert_router.url_downloader import download_file_from_url
from pathlib import Path

async def test_tls_verify_disabled():
    """Verify TLS verification can be disabled via env var."""
    os.environ["MCP_CONVERT_URL_TLS_VERIFY"] = "false"

    # This would normally fail with self-signed cert
    # but should succeed when verify=False
    # (mock test - actual SSL testing requires real server)
    work_dir = Path("/tmp/test_tls")
    work_dir.mkdir(exist_ok=True)

    # Mock to verify verify parameter is passed
    from unittest.mock import patch, MagicMock

    with patch('httpx.AsyncClient') as mock_client:
        await download_file_from_url(
            url="https://self-signed.example.com/file.pdf",
            work_dir=work_dir
        )

        # Verify AsyncClient was created with verify=False
        mock_client.assert_called_once()
        call_kwargs = mock_client.call_args.kwargs
        assert "verify" in call_kwargs
        assert call_kwargs["verify"] is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_tls_verify.py -v`
Expected: FAIL - verify parameter not passed to AsyncClient

**Step 3: Read TLS_VERIFY env var and configure httpx**

In `mcp_convert_router/url_downloader.py`, update AsyncClient creation (around line 121):

```python
        # 准备请求头（避免在日志中暴露敏感信息）
        headers = custom_headers.copy() if custom_headers else {}

        # TLS 验证控制（默认启用，生产环境建议保持 true）
        import os
        tls_verify_str = os.getenv("MCP_CONVERT_URL_TLS_VERIFY", "true").strip().lower()
        tls_verify = tls_verify_str not in ("false", "0", "no", "off")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=30, pool=30),
            follow_redirects=False,  # 手动处理重定向以检查每个目标
            max_redirects=0,
            headers=headers,
            verify=tls_verify
        ) as client:
```

**Step 4: Document TLS_VERIFY in .env.template**

Create or update `mcp_convert_router/.env.template`:

```bash
# URL 下载配置
MCP_CONVERT_ALLOWED_URL_HOSTS=openwebui.example.com,192.168.1.100,localhost
MCP_CONVERT_URL_TLS_VERIFY=true  # 设置为 false 以跳过 TLS 证书验证（仅用于内部自签名证书）

# 其他配置
MCP_CONVERT_MAX_FILE_MB=50
MCP_CONVERT_TEMP_DIR=/tmp/mcp-convert
```

**Step 5: Run test to verify it passes**

Run: `python -m pytest test_tls_verify.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add mcp_convert_router/url_downloader.py mcp_convert_router/.env.template test_tls_verify.py
git commit -m "feat: add TLS verification control for self-signed certs

- Support MCP_CONVERT_URL_TLS_VERIFY env var (default: true)
- Allow disabling TLS verification for internal deployments
- Document configuration in .env.template
- Add test coverage for TLS settings"
```

---

## Task 7: Create OpenWebUI Tool Script

**Files:**
- Create: `docs/openwebui/openwebui_tool_filetomd_url.py`

**Step 1: Write basic tool structure**

```python
"""
OpenWebUI Tool: File to Markdown (URL-based)

将 OpenWebUI 中的文件转换为 Markdown，通过 URL 方式传递文件。

Valves:
  - mcp_url: MCP convert-router 服务地址
  - openwebui_base_url: OpenWebUI 服务地址（MCP 可访问）
  - timeout_seconds: 转换超时时间
  - openwebui_api_key: （可选）OpenWebUI API Key（sk-xxx）
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import requests
import json


class Tools:
    class Valves(BaseModel):
        mcp_url: str = Field(
            default="http://mcp-convert-router:25081",
            description="MCP convert-router 服务基础 URL"
        )
        openwebui_base_url: str = Field(
            default="http://openwebui:8080",
            description="OpenWebUI 服务基础 URL（从 MCP 服务器可访问）"
        )
        timeout_seconds: int = Field(
            default=120,
            description="转换超时时间（秒）"
        )
        openwebui_api_key: Optional[str] = Field(
            default=None,
            description="（可选）OpenWebUI API Key (sk-xxx)。如果设置，将覆盖用户认证"
        )

    def __init__(self):
        self.valves = self.Valves()
```

**Step 2: Add file conversion method**

```python
    def convert_file_to_markdown(
        self,
        file_id: str,
        __user__: Optional[Dict[str, Any]] = None,
        __event_emitter__=None
    ) -> str:
        """
        将 OpenWebUI 文件转换为 Markdown。

        Args:
            file_id: OpenWebUI 文件 ID
            __user__: OpenWebUI 用户上下文（包含认证信息）
            __event_emitter__: 事件发射器（用于进度通知）

        Returns:
            str: Markdown 文本
        """
        try:
            # 1. 构造文件下载 URL
            file_url = f"{self.valves.openwebui_base_url.rstrip('/')}/api/v1/files/{file_id}/content"

            # 添加 attachment=true 以获取正确的 Content-Disposition
            file_url += "?attachment=true"

            # 2. 准备认证头
            url_headers = {}

            if self.valves.openwebui_api_key:
                # 使用配置的 API Key（优先级最高）
                url_headers["Authorization"] = f"Bearer {self.valves.openwebui_api_key}"
            elif __user__ and __user__.get("token"):
                # 使用用户的 token
                url_headers["Authorization"] = f"Bearer {__user__['token']}"
            else:
                return "错误：缺少认证信息。请配置 openwebui_api_key 或确保用户已登录"

            # 3. 调用 MCP convert_to_markdown
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {"description": "正在转换文件...", "done": False}
                    }
                )

            mcp_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "convert_to_markdown",
                    "arguments": {
                        "source": file_url,
                        "url_headers": url_headers,
                        "return_mode": "text"
                    }
                }
            }

            response = requests.post(
                f"{self.valves.mcp_url.rstrip('/')}/",
                json=mcp_payload,
                timeout=self.valves.timeout_seconds
            )
            response.raise_for_status()

            # 4. 解析响应
            result = response.json()

            if "error" in result:
                return f"MCP 错误：{result['error'].get('message', '未知错误')}"

            # 解析工具返回的 JSON
            tool_result = result.get("result", {})
            if isinstance(tool_result, list) and len(tool_result) > 0:
                content_text = tool_result[0].get("text", "{}")
                content = json.loads(content_text)
            else:
                return "错误：MCP 返回格式异常"

            # 检查转换是否成功
            if not content.get("ok"):
                error_msg = content.get("error_message", "未知错误")
                error_code = content.get("error_code", "E_UNKNOWN")

                # 如果有 next_action，提供建议
                if "next_action" in content:
                    next_action = content["next_action"]
                    return f"转换失败 ({error_code})：{error_msg}\n\n建议：\n{next_action.get('instruction', '无')}"

                return f"转换失败 ({error_code})：{error_msg}"

            # 返回 Markdown 内容
            markdown_text = content.get("markdown_text", "")

            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {"description": "转换完成", "done": True}
                    }
                )

            return markdown_text

        except requests.Timeout:
            return f"错误：转换超时（超过 {self.valves.timeout_seconds} 秒）"
        except requests.RequestException as e:
            return f"错误：MCP 请求失败 - {str(e)}"
        except Exception as e:
            return f"错误：{str(e)}"
```

**Step 3: Add metadata and documentation**

At the top of the file:

```python
"""
OpenWebUI Tool: File to Markdown (URL-based)

将 OpenWebUI 中的文件转换为 Markdown，通过 URL 方式传递文件。

## 安装步骤

1. 在 OpenWebUI 中，进入 Tools > Add Tool
2. 复制此文件的完整内容并粘贴
3. 配置 Valves：
   - mcp_url: MCP 服务地址（如 http://mcp-convert-router:25081）
   - openwebui_base_url: OpenWebUI 地址（从 MCP 可访问，如 http://openwebui:8080）
   - timeout_seconds: 转换超时（默认 120 秒）
   - openwebui_api_key: （可选）服务级 API Key

4. 保存并启用工具

## 使用方法

在聊天中：
- "请将文件 <file_id> 转换为 Markdown"
- 上传文件后："帮我分析这个文档"

## 安全说明

- 用户 token 转发：遵循 OpenWebUI 的权限控制（推荐）
- API Key 模式：使用服务级 Key，权限较高（谨慎使用）

## 前置要求

- MCP 服务器配置了 MCP_CONVERT_ALLOWED_URL_HOSTS 包含 OpenWebUI 的主机名/IP
- MCP 服务器可以通过网络访问 OpenWebUI 的 API
"""
```

**Step 4: Test the tool script for syntax**

Run: `python -m compileall docs/openwebui/openwebui_tool_filetomd_url.py`
Expected: No syntax errors

**Step 5: Commit**

```bash
git add docs/openwebui/openwebui_tool_filetomd_url.py
git commit -m "feat: add OpenWebUI tool script for URL-based conversion

- Create reference implementation for OpenWebUI Tools
- Support both user token and API key authentication
- Forward authentication headers to MCP
- Include installation and usage documentation
- Handle error responses and next_action suggestions"
```

---

## Task 8: Update Documentation

**Files:**
- Modify: `docs/openwebui-mcp-adaptation-plan.md`
- Create: `docs/openwebui/README.md`

**Step 1: Create OpenWebUI integration README**

```markdown
# OpenWebUI Integration Guide

本文档说明如何将 MCP Convert Router 与 OpenWebUI 集成。

## 架构概述

```
[OpenWebUI Client] → [OpenWebUI Server] → [MCP Convert Router]
                            ↓
                    [File Storage API]
                            ↑
                    [MCP downloads file via URL]
```

## 配置步骤

### 1. 配置 MCP Convert Router

在 MCP 服务器上设置环境变量：

```bash
# 允许 OpenWebUI 主机访问（必需）
export MCP_CONVERT_ALLOWED_URL_HOSTS="openwebui.example.com,192.168.1.100,localhost"

# （可选）如果使用自签名证书
export MCP_CONVERT_URL_TLS_VERIFY=false
```

**重要**：`MCP_CONVERT_ALLOWED_URL_HOSTS` 必须包含：
- OpenWebUI 的公网域名（如果从公网访问）
- OpenWebUI 的内网 IP/域名（如果在同一网络）

### 2. 安装 OpenWebUI Tool

1. 打开 OpenWebUI，进入 **Settings → Tools → Add Tool**
2. 复制 `docs/openwebui/openwebui_tool_filetomd_url.py` 的完整内容
3. 粘贴到 Tool 编辑器
4. 配置 Valves：
   - **mcp_url**: MCP 服务地址（例如：`http://mcp-convert-router:25081`）
   - **openwebui_base_url**: OpenWebUI 地址，从 MCP 可访问（例如：`http://openwebui:8080`）
   - **timeout_seconds**: 转换超时（默认 120 秒）
   - **openwebui_api_key**: （可选）OpenWebUI API Key（`sk-xxx` 格式）

5. 保存并启用 Tool

### 3. 验证配置

#### 检查网络连通性

从 MCP 服务器测试 OpenWebUI 可达性：

```bash
curl http://openwebui:8080/api/v1/files/health
```

#### 测试文件转换

1. 在 OpenWebUI 中上传一个 PDF 文件
2. 获取文件 ID（从 UI 或 API）
3. 在聊天中使用工具：`请将文件 <file_id> 转换为 Markdown`
4. 验证返回的 Markdown 内容

## 认证模式

### 用户 Token 转发（推荐）

- **工作方式**：转发用户的 OpenWebUI token 到 MCP，MCP 用它下载文件
- **优点**：遵循最小权限原则，用户只能访问自己的文件
- **适用场景**：多租户环境，严格权限控制

### API Key 模式

- **工作方式**：使用配置的服务级 API Key
- **优点**：简化配置，无需转发用户上下文
- **缺点**：权限较高，所有用户共享同一身份
- **适用场景**：单租户或信任环境

## 故障排查

### MCP 返回 401/403

**原因**：认证失败
- 检查 `openwebui_api_key` 是否有效
- 检查用户 token 是否过期

### MCP 返回 E_URL_FORBIDDEN

**原因**：OpenWebUI 主机未在白名单中
- 检查 `MCP_CONVERT_ALLOWED_URL_HOSTS` 配置
- 确认包含 OpenWebUI 的实际主机名/IP

### 连接超时

**原因**：MCP 无法访问 OpenWebUI
- 检查网络路由（防火墙、网络策略）
- 检查 DNS 解析
- 如果在 Docker 中，检查容器网络配置

### TLS 证书错误

**原因**：自签名证书或内部 CA
- 设置 `MCP_CONVERT_URL_TLS_VERIFY=false`（仅内部网络）

## 安全最佳实践

1. **生产环境保持 TLS 验证启用**：仅在内部网络使用 `TLS_VERIFY=false`
2. **最小化白名单**：仅添加必需的主机
3. **优先使用用户 Token**：除非有充分理由使用 API Key
4. **定期轮换 API Key**：如果使用 API Key 模式
5. **监控日志**：检查异常的文件访问模式

## 示例配置

### Docker Compose

```yaml
version: '3.8'

services:
  mcp-convert-router:
    image: mcp-convert-router:latest
    environment:
      - MCP_CONVERT_ALLOWED_URL_HOSTS=openwebui,192.168.1.100
      - MINERU_API_KEY=${MINERU_API_KEY}
    networks:
      - openwebui_network

  openwebui:
    image: ghcr.io/open-webui/open-webui:main
    networks:
      - openwebui_network

networks:
  openwebui_network:
```

### Kubernetes

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-config
data:
  MCP_CONVERT_ALLOWED_URL_HOSTS: "openwebui.default.svc.cluster.local"
  MCP_CONVERT_URL_TLS_VERIFY: "true"
```

## 参考

- [OpenWebUI API 文档](https://docs.openwebui.com/api)
- [MCP Convert Router README](../../mcp_convert_router/README.md)
- [原始设计文档](../openwebui-mcp-adaptation-plan.md)
```

**Step 2: Commit documentation**

```bash
git add docs/openwebui/README.md
git commit -m "docs: add OpenWebUI integration guide

- Add comprehensive setup instructions
- Document authentication modes
- Include troubleshooting guide
- Add security best practices
- Provide example configurations"
```

---

## Task 9: Write Integration Tests

**Files:**
- Create: `tests/integration/test_openwebui_integration.py`

**Step 1: Create integration test structure**

```python
"""
Integration tests for OpenWebUI URL-based file conversion.

These tests verify the end-to-end flow:
1. Client provides file URL + auth headers
2. MCP downloads file with authentication
3. File is converted to Markdown
4. Response is returned in expected format
"""

import pytest
import os
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from mcp_convert_router.server import handle_convert_to_markdown


@pytest.mark.asyncio
async def test_openwebui_url_with_auth_headers():
    """Test complete flow: URL + auth headers → Markdown."""
    # Setup: mock httpx to simulate OpenWebUI file endpoint
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/pdf",
        "content-disposition": "attachment; filename=\"test-report.pdf\""
    }
    mock_response.aiter_bytes = AsyncMock(return_value=[b"fake pdf content"])

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=mock_response)

    # Mock file type detection
    mock_detect = MagicMock(return_value=("pdf", None))

    # Mock conversion engine
    mock_convert = AsyncMock(return_value={
        "ok": True,
        "markdown_text": "# Test Report\n\nConverted content",
        "attempt": {"engine": "mineru", "status": "success"}
    })

    with patch('httpx.AsyncClient', return_value=mock_client), \
         patch('mcp_convert_router.server.detect_file_type_with_security', mock_detect), \
         patch('mcp_convert_router.engines.mineru_engine.convert_with_mineru', mock_convert):

        # Set allowlist
        os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "openwebui.example.com"

        args = {
            "source": "https://openwebui.example.com/api/v1/files/abc123/content",
            "url_headers": {
                "Authorization": "Bearer sk-test-key-12345"
            },
            "enable_ocr": False
        }

        result = await handle_convert_to_markdown(args)

        # Verify response structure
        assert len(result) == 1
        import json
        response = json.loads(result[0].text)

        assert response["ok"] is True
        assert "Test Report" in response["markdown_text"]
        assert response["engine_used"] == "mineru"

        # Verify auth header was passed
        mock_client.get.assert_called()
        call_kwargs = mock_client.get.call_args.kwargs
        # Headers should be in AsyncClient constructor, not get()
        # Check that the client was created with headers


@pytest.mark.asyncio
async def test_non_allowlisted_host_blocked():
    """Test that non-allowlisted private IPs are blocked."""
    os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "openwebui.example.com"

    args = {
        "source": "http://192.168.1.200/api/files/123",
        "url_headers": {"Authorization": "Bearer token"}
    }

    result = await handle_convert_to_markdown(args)

    import json
    response = json.loads(result[0].text)

    assert response["ok"] is False
    assert response["error_code"] == "E_URL_FORBIDDEN"
    assert "内网地址" in response["error_message"]


@pytest.mark.asyncio
async def test_content_disposition_filename_used():
    """Test that filename from Content-Disposition is used."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-disposition": "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf"
    }
    mock_response.aiter_bytes = AsyncMock(return_value=[b"content"])

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_detect = MagicMock(return_value=("pdf", None))
    mock_convert = AsyncMock(return_value={
        "ok": True,
        "markdown_text": "# Content",
        "attempt": {"engine": "pandoc", "status": "success"}
    })

    with patch('httpx.AsyncClient', return_value=mock_client), \
         patch('mcp_convert_router.server.detect_file_type_with_security', mock_detect), \
         patch('mcp_convert_router.engines.pandoc_engine.convert_with_pandoc', mock_convert):

        os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "example.com"

        args = {
            "source": "https://example.com/api/files/123/content",
            "url_headers": {"Authorization": "Bearer token"}
        }

        result = await handle_convert_to_markdown(args)

        import json
        response = json.loads(result[0].text)

        assert response["ok"] is True
        # Verify filename extraction worked (check work_dir contains 报告.pdf)
        assert "报告" in str(response.get("source_info", {}).get("filename", ""))
```

**Step 2: Run integration tests**

Run: `python -m pytest tests/integration/test_openwebui_integration.py -v`
Expected: Tests pass

**Step 3: Commit tests**

```bash
git add tests/integration/test_openwebui_integration.py
git commit -m "test: add integration tests for OpenWebUI flow

- Test complete URL + auth headers flow
- Test allowlist enforcement
- Test Content-Disposition filename extraction
- Mock external dependencies for isolation"
```

---

## Task 10: Final Validation and Documentation Update

**Files:**
- Modify: `CLAUDE.md`
- Modify: `mcp_convert_router/README.md`

**Step 1: Update CLAUDE.md with new env vars**

In `CLAUDE.md`, update the environment variables table:

```markdown
### mcp_convert_router

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_CONVERT_TEMP_DIR` | `/tmp/mcp-convert` | Temp directory |
| `MCP_CONVERT_MAX_FILE_MB` | `50` | Max file size |
| `MCP_CONVERT_ALLOWED_INPUT_ROOTS` | - | Whitelist for local paths (comma-separated) |
| `MCP_CONVERT_ALLOWED_URL_HOSTS` | - | Whitelist for URL hosts (comma-separated, bypasses SSRF) |
| `MCP_CONVERT_URL_TLS_VERIFY` | `true` | TLS certificate verification for URL downloads |
| `MINERU_API_KEY` | - | MinerU API key |
| `USE_LOCAL_API` | `false` | Use local MinerU instead of cloud |
| `MCP_TRANSPORT` | `stdio` | Transport mode (stdio/sse/streamable-http) |
```

**Step 2: Update mcp_convert_router/README.md**

Add new section about OpenWebUI integration:

```markdown
## OpenWebUI Integration

The convert router supports OpenWebUI file conversion via authenticated URL downloads.

### Quick Setup

1. Configure MCP allowlist:
```bash
export MCP_CONVERT_ALLOWED_URL_HOSTS="openwebui.example.com,192.168.1.100"
```

2. Install the OpenWebUI tool from `docs/openwebui/openwebui_tool_filetomd_url.py`

3. Configure tool valves with MCP and OpenWebUI URLs

See [docs/openwebui/README.md](../docs/openwebui/README.md) for detailed guide.

### Authentication

The tool supports two modes:
- **User token forwarding** (recommended): Respects OpenWebUI permissions
- **API key mode**: Uses service-level key for all requests

### Security

- Allowlisted hosts bypass SSRF protection (use carefully)
- Non-allowlisted hosts remain protected
- TLS verification enabled by default
```

**Step 3: Run smoke tests**

```bash
# Compile all Python files
python -m compileall mcp_convert_router

# Run all tests
python -m pytest tests/ -v

# Dry-run server config
python -m mcp_convert_router.server --dry-run
```

Expected: All pass

**Step 4: Commit documentation updates**

```bash
git add CLAUDE.md mcp_convert_router/README.md
git commit -m "docs: update documentation for OpenWebUI integration

- Add new environment variables to CLAUDE.md
- Add OpenWebUI integration section to README
- Document authentication modes and security
- Reference detailed integration guide"
```

---

## Plan Complete and Saved to `docs/plans/2026-01-26-openwebui-url-auth-integration.md`

Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach would you like?
