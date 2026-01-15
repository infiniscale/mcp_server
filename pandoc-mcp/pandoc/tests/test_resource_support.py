"""Unit tests for MCP Resource support functionality.

Tests the new convert-document-resource tool and related utilities.
"""

import base64
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as types
from mcp_pandoc.server import (
    _sanitize_filename,
    _decode_base64_payload,
    _estimate_base64_decoded_size,
    _handle_convert_document_resource,
)


class TestFilenamesanitization:
    """Test filename sanitization for security."""

    def test_sanitize_basic_filename(self):
        """Test basic filename sanitization."""
        assert _sanitize_filename("document.pdf") == "document.pdf"
        assert _sanitize_filename("my_file.docx") == "my_file.docx"
        assert _sanitize_filename("test123.txt") == "test123.txt"

    def test_sanitize_spaces_and_special_chars(self):
        """Test replacement of spaces and special characters."""
        assert _sanitize_filename("my file.docx") == "my_file.docx"
        assert _sanitize_filename("test,doc.txt") == "test_doc.txt"
        assert _sanitize_filename("file  with   spaces.md") == "file_with_spaces.md"

    def test_sanitize_path_traversal(self):
        """Test protection against path traversal attacks."""
        assert _sanitize_filename("../../../etc/passwd") == "passwd"
        assert _sanitize_filename("..\\..\\windows\\system32") == "system32"
        assert _sanitize_filename("/etc/shadow") == "shadow"
        assert _sanitize_filename("C:\\Windows\\System32\\config") == "config"

    def test_sanitize_empty_or_invalid(self):
        """Test handling of empty or invalid filenames."""
        assert _sanitize_filename("") == "upload.bin"
        assert _sanitize_filename("   ") == "upload.bin"
        assert _sanitize_filename("...") == "upload.bin"


class TestBase64Handling:
    """Test base64 encoding/decoding utilities."""

    def test_decode_plain_base64(self):
        """Test plain base64 decoding."""
        content = b"Hello World"
        encoded = base64.b64encode(content).decode()
        result = _decode_base64_payload(encoded)
        assert result == content

    def test_decode_data_url_prefix(self):
        """Test base64 with data URL prefix."""
        content = b"PDF content"
        encoded = base64.b64encode(content).decode()
        data_url = f"data:application/pdf;base64,{encoded}"
        result = _decode_base64_payload(data_url)
        assert result == content

    def test_decode_with_whitespace(self):
        """Test base64 decoding with whitespace."""
        content = b"Test content"
        encoded = base64.b64encode(content).decode()
        # Add whitespace
        with_spaces = f"{encoded[:20]} \n {encoded[20:]}"
        result = _decode_base64_payload(with_spaces)
        assert result == content

    def test_decode_invalid_base64(self):
        """Test error handling for invalid base64."""
        with pytest.raises(ValueError, match="Base64 decode failed"):
            _decode_base64_payload("not-valid-base64!@#$%")

    def test_decode_empty_payload(self):
        """Test error handling for empty payload."""
        with pytest.raises(ValueError, match="content_base64 is empty"):
            _decode_base64_payload("")

        with pytest.raises(ValueError, match="content_base64 is empty"):
            _decode_base64_payload("   ")

    def test_estimate_base64_size(self):
        """Test base64 size estimation."""
        content = b"x" * 1000
        encoded = base64.b64encode(content).decode()
        estimated = _estimate_base64_decoded_size(encoded)
        # Should be close to actual size (within a few bytes due to padding)
        assert abs(estimated - 1000) <= 3

    def test_estimate_empty_size(self):
        """Test size estimation for empty string."""
        assert _estimate_base64_decoded_size("") == 0
        assert _estimate_base64_decoded_size("   ") == 0


@pytest.mark.asyncio
class TestResourceHandlerErrors:
    """Test error handling in convert-document-resource handler."""

    async def test_missing_resource_uri(self):
        """Test error when resource_uri is missing."""
        result = await _handle_convert_document_resource({})

        assert len(result) == 1
        assert result[0].type == "text"

        response = json.loads(result[0].text)
        assert response["status"] == "error"
        assert "resource_uri" in response["error"]

    async def test_empty_resource_uri(self):
        """Test error when resource_uri is empty."""
        result = await _handle_convert_document_resource({"resource_uri": ""})

        assert len(result) == 1
        response = json.loads(result[0].text)
        assert response["status"] == "error"

    @patch('mcp_pandoc.server.request_ctx')
    async def test_context_unavailable(self, mock_ctx_var):
        """Test error when request context is unavailable."""
        # Mock the ContextVar to raise LookupError on get()
        mock_ctx_var.get.side_effect = LookupError("Context not found")

        result = await _handle_convert_document_resource({
            "resource_uri": "file:///test.md"
        })

        assert len(result) == 1
        response = json.loads(result[0].text)
        assert response["status"] == "error"
        assert "context unavailable" in response["error"].lower()


@pytest.mark.asyncio
class TestResourceHandlerSuccess:
    """Test successful resource conversion scenarios."""

    @patch('mcp_pandoc.server.request_ctx')
    @patch('mcp_pandoc.server._convert_file_sync')
    async def test_text_resource_conversion(self, mock_convert, mock_ctx_var):
        """Test successful conversion of text resource."""
        # Mock request context and session
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        # Mock resource response with text content
        test_content = "# Hello World\n\nThis is a test."
        mock_result = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri="file:///test.md",
                    mimeType="text/markdown",
                    text=test_content
                )
            ]
        )
        mock_session.send_request.return_value = mock_result

        # Mock conversion result
        mock_convert.return_value = {
            "status": "success",
            "filename": "test.md",
            "output_format": "html",
            "content": "<h1>Hello World</h1>\n<p>This is a test.</p>"
        }

        # Execute
        result = await _handle_convert_document_resource({
            "resource_uri": "file:///test.md",
            "output_format": "html"
        })

        # Verify
        assert len(result) == 1
        assert result[0].type == "text"
        assert "successfully converted" in result[0].text.lower()
        assert "html" in result[0].text.lower()

        # Verify session was called correctly
        mock_session.send_request.assert_called_once()
        call_args = mock_session.send_request.call_args[0]
        assert isinstance(call_args[0], types.ReadResourceRequest)
        assert str(call_args[0].params.uri) == "file:///test.md"

    @patch('mcp_pandoc.server.request_ctx')
    @patch('mcp_pandoc.server._convert_file_sync')
    async def test_binary_resource_conversion(self, mock_convert, mock_ctx_var):
        """Test successful conversion of binary resource."""
        # Mock request context
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        # Mock resource response with binary content
        test_bytes = b"PDF binary content"
        encoded_bytes = base64.b64encode(test_bytes).decode()
        mock_result = types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri="file:///test.pdf",
                    mimeType="application/pdf",
                    blob=encoded_bytes
                )
            ]
        )
        mock_session.send_request.return_value = mock_result

        # Mock conversion result
        mock_convert.return_value = {
            "status": "success",
            "filename": "test.pdf",
            "output_format": "markdown",
            "content": "# Converted from PDF\n\nContent here."
        }

        # Execute
        result = await _handle_convert_document_resource({
            "resource_uri": "file:///test.pdf",
            "output_format": "markdown"
        })

        # Verify
        assert len(result) == 1
        assert "successfully converted" in result[0].text.lower()
        mock_convert.assert_called_once()

    @patch('mcp_pandoc.server.request_ctx')
    @patch('mcp_pandoc.server.config.MAX_UPLOAD_BYTES', 100)
    async def test_file_too_large(self, mock_ctx_var):
        """Test rejection of files exceeding size limit."""
        # Mock request context
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        # Mock resource with large content
        large_content = "x" * 1000  # Exceeds mocked limit of 100 bytes
        mock_result = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri="file:///large.txt",
                    mimeType="text/plain",
                    text=large_content
                )
            ]
        )
        mock_session.send_request.return_value = mock_result

        # Execute
        result = await _handle_convert_document_resource({
            "resource_uri": "file:///large.txt",
            "output_format": "html"
        })

        # Verify
        assert len(result) == 1
        response = json.loads(result[0].text)
        assert response["status"] == "error"
        assert "too large" in response["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
