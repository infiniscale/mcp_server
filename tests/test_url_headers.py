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
