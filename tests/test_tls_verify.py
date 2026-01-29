"""Tests for TLS verification control in URL downloader."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_convert_router.url_downloader import download_file_from_url


@pytest.mark.asyncio
async def test_tls_verify_disabled(tmp_path):
    """Verify TLS verification can be disabled via env var."""
    # Set environment variable to disable TLS verification
    os.environ["MCP_CONVERT_URL_TLS_VERIFY"] = "false"
    os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "example.com"

    try:
        with patch("mcp_convert_router.url_downloader.httpx.AsyncClient") as mock_client_class:
            # Create mock client instance
            mock_client = AsyncMock()
            mock_client.aclose = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}

            # Mock async iteration for response body
            async def mock_aiter_bytes(chunk_size=8192):
                yield b"test content"

            mock_response.aiter_bytes = mock_aiter_bytes
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            # Attempt download
            url = "https://example.com/test.pdf"
            work_dir = Path(tmp_path)
            result = await download_file_from_url(url, work_dir)

            # Verify AsyncClient was called with verify=False
            mock_client_class.assert_called_once()
            call_kwargs = mock_client_class.call_args[1]
            assert "verify" in call_kwargs, "verify parameter not passed to AsyncClient"
            assert call_kwargs["verify"] is False, f"Expected verify=False, got {call_kwargs['verify']}"

            # Verify download succeeded
            assert result["ok"] is True
    finally:
        # Clean up environment variables
        if "MCP_CONVERT_URL_TLS_VERIFY" in os.environ:
            del os.environ["MCP_CONVERT_URL_TLS_VERIFY"]
        if "MCP_CONVERT_ALLOWED_URL_HOSTS" in os.environ:
            del os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"]
