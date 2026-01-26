# test_url_headers.py
import pytest
from mcp_convert_router.server import handle_list_tools

@pytest.mark.asyncio
async def test_url_headers_in_schema():
    """Verify url_headers parameter is in the tool schema."""
    tools = await handle_list_tools()
    convert_tool = next(t for t in tools if t.name == "convert_to_markdown")
    schema = convert_tool.inputSchema

    assert "url_headers" in schema["properties"]
    assert schema["properties"]["url_headers"]["type"] == "object"
    assert "additionalProperties" in schema["properties"]["url_headers"]

import httpx
from mcp_convert_router.url_downloader import download_file_from_url
from pathlib import Path
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_download_sends_custom_headers():
    """Verify custom headers are sent in the HTTP request."""

    # Mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/pdf"}
    mock_response.aiter_bytes = lambda chunk_size: iter([b"test content"])

    # Mock client
    mock_client = MagicMock()
    mock_client.__aenter__ = lambda self: mock_client
    mock_client.__aexit__ = lambda self, *args: None
    mock_client.get = MagicMock(return_value=mock_response)

    with patch('httpx.AsyncClient', return_value=mock_client) as mock_async_client:
        work_dir = Path("/tmp/test_work")
        work_dir.mkdir(exist_ok=True)

        result = await download_file_from_url(
            url="https://example.com/file.pdf",
            work_dir=work_dir,
            custom_headers={"Authorization": "Bearer test-token"}
        )

        # Verify AsyncClient was called with headers
        assert mock_async_client.called
        call_kwargs = mock_async_client.call_args.kwargs
        assert "headers" in call_kwargs
        assert call_kwargs["headers"] == {"Authorization": "Bearer test-token"}

from unittest.mock import AsyncMock
from mcp_convert_router.server import handle_convert_to_markdown

@pytest.mark.asyncio
async def test_server_passes_headers_to_downloader():
    """Verify server handler passes url_headers to downloader."""

    mock_download = AsyncMock(return_value={
        "ok": True,
        "file_path": "/tmp/test.pdf",
        "filename": "test.pdf",
        "size_bytes": 1000,
        "content_type": "application/pdf",
        "elapsed_ms": 100
    })

    with patch('mcp_convert_router.url_downloader.download_file_from_url', mock_download):
        args = {
            "source": "https://example.com/file.pdf",
            "url_headers": {"Authorization": "Bearer test-key"}
        }
        await handle_convert_to_markdown(args)

    # Verify headers were passed
    assert mock_download.called
    call_kwargs = mock_download.call_args.kwargs
    assert "custom_headers" in call_kwargs, "custom_headers not passed"
    assert call_kwargs["custom_headers"] == {"Authorization": "Bearer test-key"}
