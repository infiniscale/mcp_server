"""Integration tests for MCP Resource support.

Tests the full integration with mocked MCP client sessions.
"""

import asyncio
import base64
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as types
from mcp_pandoc.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
class TestToolRegistration:
    """Test that the new tool is properly registered."""

    async def test_tool_listed(self):
        """Test that convert-document-resource appears in tool list."""
        tools = await handle_list_tools()

        tool_names = [t.name for t in tools]
        assert "convert-document-resource" in tool_names

        # Find the tool
        resource_tool = next(t for t in tools if t.name == "convert-document-resource")

        # Verify schema
        assert "resource_uri" in resource_tool.inputSchema["properties"]
        assert "output_format" in resource_tool.inputSchema["properties"]
        assert resource_tool.inputSchema["required"] == ["resource_uri"]

    async def test_existing_tools_still_present(self):
        """Test backward compatibility - existing tools unchanged."""
        tools = await handle_list_tools()
        tool_names = [t.name for t in tools]

        # Original tools must still exist
        assert "convert-contents" in tool_names
        assert "convert-contents-base64" in tool_names
        assert "convert-contents-text" in tool_names

    async def test_text_tool_schema(self):
        """Test schema for convert-contents-text tool."""
        tools = await handle_list_tools()
        text_tool = next(t for t in tools if t.name == "convert-contents-text")

        properties = text_tool.inputSchema["properties"]
        assert "content" in properties
        assert "filename" in properties
        assert "output_format" in properties
        assert text_tool.inputSchema["required"] == ["content", "filename", "output_format"]


@pytest.mark.asyncio
class TestToolRouting:
    """Test tool routing and execution."""

    @patch('mcp_pandoc.server.request_ctx')
    @patch('mcp_pandoc.server._convert_file_sync')
    async def test_tool_execution_via_handler(self, mock_convert, mock_ctx_var):
        """Test calling convert-document-resource through handle_call_tool."""
        # Setup mocks
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        # Mock resource response
        test_content = "# Test Document\n\nContent here."
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

        # Mock conversion
        mock_convert.return_value = {
            "status": "success",
            "filename": "test.md",
            "output_format": "html",
            "content": "<h1>Test Document</h1>\n<p>Content here.</p>"
        }

        # Execute through main handler
        result = await handle_call_tool(
            name="convert-document-resource",
            arguments={
                "resource_uri": "file:///test.md",
                "output_format": "html"
            }
        )

        # Verify
        assert len(result) == 1
        assert result[0].type == "text"
        assert "successfully converted" in result[0].text.lower()

    async def test_unknown_tool_rejected(self):
        """Test that unknown tools are rejected."""
        with pytest.raises(ValueError, match="Unknown tool"):
            await handle_call_tool(
                name="nonexistent-tool",
                arguments={}
            )


@pytest.mark.asyncio
class TestBackwardCompatibility:
    """Test that existing tools still work correctly."""

    async def test_convert_contents_still_works(self, tmp_path):
        """Test that convert-contents tool is unaffected."""
        # Create test file
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test\n\nContent here.")

        # Call original tool
        result = await handle_call_tool(
            name="convert-contents",
            arguments={
                "input_file": str(test_file),
                "output_format": "html"
            }
        )

        # Verify it still works
        assert len(result) == 1
        assert result[0].type == "text"
        # Should contain converted HTML (check for h1 tag which appears in output)
        assert "h1" in result[0].text.lower() and "content here" in result[0].text.lower()

    async def test_convert_contents_base64_still_works(self):
        """Test that convert-contents-base64 tool is unaffected."""
        # Create test content
        content = "# Test\n\nBase64 test content."
        encoded = base64.b64encode(content.encode()).decode()

        # Call base64 tool
        result = await handle_call_tool(
            name="convert-contents-base64",
            arguments={
                "files": [{
                    "filename": "test.md",
                    "content_base64": encoded
                }],
                "output_format": "html"
            }
        )

        # Verify it still works
        assert len(result) == 1
        assert result[0].type == "text"
        assert "successfully converted" in result[0].text.lower() or "<h1>" in result[0].text

    async def test_convert_contents_text_still_works(self):
        """Test that convert-contents-text tool works."""
        content = "# Test\n\nPlain text payload."

        result = await handle_call_tool(
            name="convert-contents-text",
            arguments={
                "content": content,
                "filename": "test.md",
                "output_format": "html"
            }
        )

        assert len(result) == 1
        assert result[0].type == "text"
        assert "successfully converted" in result[0].text.lower() or "<h1>" in result[0].text

    @patch("mcp_pandoc.server.storage.get_storage")
    async def test_convert_contents_text_minio_upload(self, mock_get_storage):
        """Test convert-contents-text tool with MinIO upload."""
        minio_client = MagicMock()
        minio_client.upload_file.return_value = {
            "download_url": "https://minio.example.com/download",
            "object_name": "test.html",
            "size": 123,
            "bucket": "pandoc-conversions",
        }
        mock_get_storage.return_value = minio_client

        result = await handle_call_tool(
            name="convert-contents-text",
            arguments={
                "content": "# Test\n\nMinIO upload.",
                "filename": "test.md",
                "output_format": "html"
            }
        )

        assert len(result) == 1
        assert result[0].type == "text"
        assert minio_client.upload_file.called
        assert "Download URL" in result[0].text


@pytest.mark.asyncio
class TestResourceContentTypes:
    """Test handling of different content types."""

    @patch('mcp_pandoc.server.request_ctx')
    @patch('mcp_pandoc.server._convert_file_sync')
    async def test_text_content_type(self, mock_convert, mock_ctx_var):
        """Test TextResourceContents handling."""
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        mock_result = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri="file:///doc.txt",
                    mimeType="text/plain",
                    text="Plain text content"
                )
            ]
        )
        mock_session.send_request.return_value = mock_result

        mock_convert.return_value = {
            "status": "success",
            "filename": "doc.txt",
            "content": "Converted content"
        }

        result = await handle_call_tool(
            name="convert-document-resource",
            arguments={"resource_uri": "file:///doc.txt"}
        )

        assert len(result) == 1
        assert "successfully converted" in result[0].text.lower()

    @patch('mcp_pandoc.server.request_ctx')
    @patch('mcp_pandoc.server._convert_file_sync')
    async def test_blob_content_type(self, mock_convert, mock_ctx_var):
        """Test BlobResourceContents handling."""
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        blob_data = b"Binary PDF data"
        mock_result = types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri="file:///doc.pdf",
                    mimeType="application/pdf",
                    blob=base64.b64encode(blob_data).decode()
                )
            ]
        )
        mock_session.send_request.return_value = mock_result

        mock_convert.return_value = {
            "status": "success",
            "filename": "doc.pdf",
            "content": "# Converted\n\nFrom PDF"
        }

        result = await handle_call_tool(
            name="convert-document-resource",
            arguments={
                "resource_uri": "file:///doc.pdf",
                "output_format": "markdown"
            }
        )

        assert len(result) == 1
        assert "successfully converted" in result[0].text.lower()


@pytest.mark.asyncio
class TestErrorScenarios:
    """Test various error scenarios."""

    @patch('mcp_pandoc.server.request_ctx')
    async def test_empty_resource_contents(self, mock_ctx_var):
        """Test error when resource has no contents."""
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        # Empty contents list
        mock_result = types.ReadResourceResult(contents=[])
        mock_session.send_request.return_value = mock_result

        result = await handle_call_tool(
            name="convert-document-resource",
            arguments={"resource_uri": "file:///empty.md"}
        )

        assert len(result) == 1
        response_text = result[0].text
        assert "error" in response_text.lower()

    @patch('mcp_pandoc.server.request_ctx')
    @patch('mcp_pandoc.server._convert_file_sync')
    async def test_conversion_failure(self, mock_convert, mock_ctx_var):
        """Test handling of conversion failures."""
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.session = mock_session
        mock_ctx_var.get.return_value = mock_ctx

        mock_result = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri="file:///bad.md",
                    mimeType="text/markdown",
                    text="# Test"
                )
            ]
        )
        mock_session.send_request.return_value = mock_result

        # Mock conversion failure
        mock_convert.return_value = {
            "status": "error",
            "filename": "bad.md",
            "error_message": "Pandoc conversion failed"
        }

        result = await handle_call_tool(
            name="convert-document-resource",
            arguments={
                "resource_uri": "file:///bad.md",
                "output_format": "pdf"
            }
        )

        assert len(result) == 1
        assert "failed" in result[0].text.lower() or "error" in result[0].text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
