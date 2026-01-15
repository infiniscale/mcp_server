# Pandoc MCP Resource Support Design

**Date**: 2026-01-15
**Status**: Design Complete - Ready for Implementation
**Author**: AI-Assisted Design Session
**Version**: 1.0

---

## Executive Summary

This design addresses the file access challenge when using Pandoc MCP service with GUI clients like Cherry Studio. The current implementation requires clients to manually base64-encode files, which is not user-friendly for GUI-based workflows.

**Solution**: Implement MCP Resource protocol support, allowing the server to request file content from clients that expose uploaded files as MCP Resources.

**Impact**: Enables seamless file conversion in Cherry Studio and other GUI MCP clients while maintaining backward compatibility with existing tools.

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Current Architecture](#current-architecture)
3. [Proposed Solution](#proposed-solution)
4. [Technical Implementation](#technical-implementation)
5. [Integration Strategy](#integration-strategy)
6. [Testing Strategy](#testing-strategy)
7. [Risk Analysis](#risk-analysis)
8. [Implementation Plan](#implementation-plan)

---

## Problem Statement

### Current Situation

The Pandoc MCP service provides two tools:

1. **`convert-contents`** - Accepts local file paths (stdio mode only)
2. **`convert-contents-base64`** - Accepts base64-encoded file content (HTTP mode)

### The Challenge

When testing with Cherry Studio (a GUI MCP client):

- Users can attach files through the UI
- But Cherry Studio does not automatically encode files to base64
- The service cannot access client-side files
- Users must manually encode files, breaking the workflow

### Test Results

From actual Cherry Studio testing:
```
Tool: convert-contents-base64
Input: Manually base64-encoded text (not a real DOCX file)
Result: ERROR - "couldn't unpack docx container"
```

**Root Cause**: Cherry Studio has file attachment UI but doesn't automatically provide file content to MCP tools.

---

## Current Architecture

### Project Structure

```
pandoc-mcp/pandoc/
├── src/mcp_pandoc/
│   ├── __init__.py
│   ├── server.py          # MCP server (uses official mcp SDK)
│   ├── cli.py             # Command-line interface
│   └── config.py          # Configuration management
├── pyproject.toml         # Dependencies: mcp>=1.2.1
└── tests/
```

### Current Dependencies

```toml
dependencies = [
    "mcp>=1.2.1",           # Official MCP SDK (NOT FastMCP)
    "pypandoc>=1.14",
    "python-dotenv>=1.0.0",
    "starlette>=0.27.0",
    "uvicorn>=0.23.0",
]
```

### Key Finding

The project uses **official MCP SDK**, not FastMCP. This affects the implementation approach.

---

## Proposed Solution

### Three-Tool Strategy

Support three file access patterns:

```
┌─────────────────────────────────────────────────┐
│        Pandoc MCP Server (Enhanced)             │
├─────────────────────────────────────────────────┤
│                                                  │
│  Tool 1: convert-contents                       │
│  └─ Local file paths (stdio mode)               │
│                                                  │
│  Tool 2: convert-contents-base64                │
│  └─ Base64 upload (programmatic clients)        │
│                                                  │
│  Tool 3: convert-document-resource (NEW)        │
│  └─ MCP Resource URIs (GUI clients)             │
│                                                  │
└─────────────────────────────────────────────────┘
```

### How MCP Resources Work

```
┌─────────────┐                    ┌──────────────┐
│ Cherry      │                    │  Pandoc MCP  │
│ Studio      │                    │  Server      │
└─────────────┘                    └──────────────┘
      │                                     │
      │ 1. User attaches doc.pdf            │
      │                                     │
      │ 2. Client exposes as Resource       │
      │    URI: file:///uploads/doc.pdf     │
      │                                     │
      │ 3. User calls:                      │
      │    convert-document-resource(       │
      │      resource_uri="file:///..."     │
      │    )                                │
      ├────────────────────────────────────>│
      │                                     │
      │ 4. Server requests Resource         │
      │<────────────────────────────────────┤
      │    ReadResourceRequest(uri)         │
      │                                     │
      │ 5. Client sends file content        │
      ├────────────────────────────────────>│
      │    (binary data)                    │
      │                                     │
      │                                  6. Convert
      │                                     with
      │                                     Pandoc
      │                                     │
      │ 7. Return converted result          │
      │<────────────────────────────────────┤
```

### Key Insight

MCP protocol supports **bidirectional communication**:
- Clients can call server tools (standard)
- **Servers can request resources from clients** (less common, but supported)

---

## Technical Implementation

### Section 1: Core Mechanism - Accessing Request Context

The official MCP SDK provides `request_ctx` via `contextvars`:

```python
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext

# In any tool function:
ctx = request_ctx.get()           # Get current request context
session = ctx.session              # Get ServerSession
# session can send requests to CLIENT
```

### Section 2: Implementation Code

#### 2.1 Add New Tool Registration

```python
# In server.py - Modify handle_list_tools()

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""

    tools = [
        # Existing tools...

        # NEW: Resource-based conversion
        types.Tool(
            name="convert-document-resource",
            description=(
                "Convert documents from MCP Resource URIs (for GUI clients). "
                "The client must expose uploaded files as MCP Resources. "
                "Example: file:///uploads/document.pdf"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_uri": {
                        "type": "string",
                        "description": "MCP Resource URI (e.g., file:///uploads/doc.pdf)"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Target format: markdown, html, docx, pdf, etc.",
                        "default": "markdown"
                    },
                    "input_format": {
                        "type": "string",
                        "description": "Source format (optional, auto-detected)"
                    }
                },
                "required": ["resource_uri"]
            }
        ),
    ]

    return tools
```

#### 2.2 Add Tool Handler

```python
# In server.py - Modify handle_call_tool()

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""

    if arguments is None:
        arguments = {}

    try:
        if name == "convert-contents":
            return await _handle_convert_contents(arguments)

        elif name == "convert-contents-base64":
            return await _handle_convert_contents_base64(arguments)

        elif name == "convert-document-resource":
            # NEW: Resource-based conversion
            return await _handle_convert_document_resource(arguments)

        else:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "error": f"Unknown tool: {name}"
                })
            )]

    except Exception as e:
        config.logger.error(f"Tool execution error [{name}]: {str(e)}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": f"Tool execution failed: {str(e)}"
            })
        )]
```

#### 2.3 Implement Resource Reading Logic

```python
# In server.py - Add new function

import json
import base64
import secrets
import shutil
from pathlib import Path

async def _handle_convert_document_resource(
    arguments: dict[str, Any]
) -> list[types.TextContent]:
    """
    Handle convert-document-resource tool.

    This function requests file content from the MCP client via Resource protocol.
    """
    resource_uri = arguments.get("resource_uri")
    output_format = arguments.get("output_format", "markdown")
    input_format = arguments.get("input_format")

    if not resource_uri:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": "resource_uri is required"
            })
        )]

    try:
        # STEP 1: Get current request context
        # The MCP SDK automatically sets this for each tool call
        ctx = request_ctx.get()
        session = ctx.session

        config.logger.info(f"Requesting resource from client: {resource_uri}")

        # STEP 2: Send ReadResourceRequest to CLIENT
        # This is the key innovation - server requests from client
        read_result = await session.send_request(
            types.ReadResourceRequest(
                params=types.ReadResourceRequestParams(uri=resource_uri)
            ),
            types.ReadResourceResult
        )

        # STEP 3: Extract file content from response
        file_bytes = None
        for content in read_result.contents:
            if isinstance(content, types.BlobResourceContents):
                # Binary content (PDF, DOCX, images, etc.)
                file_bytes = base64.b64decode(content.blob)
                break
            elif isinstance(content, types.TextResourceContents):
                # Text content (markdown, plain text, etc.)
                file_bytes = content.text.encode('utf-8')
                break

        if file_bytes is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "error": "No content found in resource"
                })
            )]

        # STEP 4: Security validation
        if len(file_bytes) > config.MAX_UPLOAD_BYTES:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "error": f"File too large: {len(file_bytes)} bytes (limit: {config.MAX_UPLOAD_BYTES})"
                })
            )]

        # STEP 5: Save to temporary file
        upload_dir = Path(config.TEMP_DIR) / "_uploads" / secrets.token_hex(12)
        upload_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Extract filename from URI
            filename = Path(resource_uri).name or "document.bin"
            temp_path = upload_dir / _sanitize_filename(filename)
            temp_path.write_bytes(file_bytes)

            # STEP 6: Convert using existing Pandoc logic
            result = _convert_file_sync(
                temp_path,
                output_format,
                input_format
            )

            return [types.TextContent(
                type="text",
                text=json.dumps(result)
            )]

        finally:
            # STEP 7: Cleanup temporary files
            shutil.rmtree(upload_dir, ignore_errors=True)

    except LookupError:
        # request_ctx.get() raised LookupError - context not available
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": "Request context unavailable (internal error)"
            })
        )]

    except Exception as e:
        config.logger.error(f"Resource conversion error: {str(e)}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": str(e)
            })
        )]


def _convert_file_sync(
    input_path: Path,
    output_format: str,
    input_format: Optional[str] = None
) -> dict[str, Any]:
    """
    Synchronous file conversion using pypandoc.
    Reuses existing conversion logic.
    """
    try:
        # Detect input format if not provided
        if not input_format:
            suffix = input_path.suffix.lower().lstrip('.')
            input_format = INPUT_FORMAT_ALIASES.get(suffix, suffix)

        # Get Pandoc-compatible format names
        pandoc_output_format = FORMAT_ALIASES.get(output_format, output_format)

        # Convert using pypandoc
        converted_content = pypandoc.convert_file(
            str(input_path),
            pandoc_output_format
        )

        # Return result
        is_binary = output_format in BINARY_FORMATS

        return {
            "status": "success",
            "filename": input_path.name,
            "output_format": output_format,
            "content": None if is_binary else converted_content,
            "content_base64": base64.b64encode(
                converted_content.encode()
            ).decode() if is_binary else None
        }

    except Exception as e:
        config.logger.error(f"Conversion error: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "filename": input_path.name,
            "error_message": str(e)
        }
```

#### 2.4 Required Imports

```python
# Add to top of server.py

import json
import base64
import secrets
import shutil
from pathlib import Path
from typing import Any, Optional

from mcp.server.lowlevel.server import request_ctx
import mcp.types as types
```

---

## Integration Strategy

### Compatibility Matrix

| Tool Name | File Source | Transport Mode | Client Type |
|-----------|-------------|----------------|-------------|
| `convert-contents` | Local file path | stdio | CLI, Desktop Apps |
| `convert-contents-base64` | Base64 content | stdio/HTTP | Programmatic |
| `convert-document-resource` | MCP Resource URI | stdio/HTTP | GUI Apps |

### Backward Compatibility

**Critical Requirement**: All existing functionality must continue working.

- ✅ `convert-contents` unchanged
- ✅ `convert-contents-base64` unchanged
- ✅ Existing CLI usage preserved
- ✅ All existing tests pass

### Migration Path for Users

**No migration required**. This is a pure addition:

```bash
# Existing usage - still works
mcp-pandoc --transport stdio

# Existing HTTP usage - still works
mcp-pandoc --transport streamable-http --port 8001

# New feature automatically available
# (no config changes needed)
```

---

## Testing Strategy

### Test Pyramid

```
     ┌─────────────────┐
     │  E2E Tests      │  Cherry Studio manual testing
     │  (Manual)       │
     ├─────────────────┤
     │  Integration    │  Mock MCP client
     │  Tests          │
     ├─────────────────┤
     │  Unit Tests     │  Individual functions
     └─────────────────┘
```

### Phase 1: Unit Tests

**Coverage**: Utility functions, validation, error handling

```python
# tests/test_resource_utils.py

def test_sanitize_filename_path_traversal():
    """Prevent directory traversal attacks"""
    assert _sanitize_filename("../../../etc/passwd") == "passwd"

def test_decode_base64_with_data_url():
    """Handle data:application/pdf;base64,... format"""
    # Test implementation...

def test_file_size_validation():
    """Reject files exceeding MAX_UPLOAD_BYTES"""
    # Test implementation...
```

**Run**: `pytest -m unit`

### Phase 2: Integration Tests

**Coverage**: Full tool execution with mocked MCP session

```python
# tests/test_resource_integration.py

@pytest.mark.asyncio
async def test_resource_conversion_success():
    """Test successful resource-based conversion"""

    # Mock MCP session
    mock_session = AsyncMock()
    mock_session.send_request.return_value = types.ReadResourceResult(
        contents=[types.BlobResourceContents(...)]
    )

    # Patch request context
    with patch('mcp_pandoc.server.request_ctx.get', ...):
        result = await _handle_convert_document_resource({
            "resource_uri": "file:///test.md",
            "output_format": "html"
        })

    # Verify success
    assert result["status"] == "success"
```

**Run**: `pytest -m integration`

### Phase 3: End-to-End Tests

**Coverage**: Real MCP client interaction

#### Automated E2E Test

```python
# tests/test_e2e_client.py

@pytest.mark.e2e
async def test_e2e_with_mcp_client():
    """Test with real MCP client connection"""

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Call new tool
            result = await session.call_tool(
                "convert-document-resource",
                arguments={...}
            )

            assert result.content[0].type == "text"
```

**Run**: `pytest -m e2e`

#### Manual Cherry Studio Test

**Test Document**: `tests/manual_testing.md`

**Steps**:

1. Start server: `mcp-pandoc --transport streamable-http --port 8001`
2. Configure Cherry Studio to connect to `http://127.0.0.1:8001/mcp`
3. Upload `test.md` in Cherry Studio
4. Ask: "Use convert-document-resource to convert the uploaded file to HTML"
5. **Observe**:
   - ✅ Success → Cherry Studio supports MCP Resources
   - ❌ "Resource not found" → Cherry Studio doesn't expose files as Resources

### Phase 4: Backward Compatibility Tests

```python
# tests/test_backward_compatibility.py

@pytest.mark.asyncio
async def test_original_tools_still_work():
    """Ensure no regression in existing tools"""

    # Test convert-contents
    result1 = await handle_call_tool("convert-contents", {...})
    assert result1["status"] == "success"

    # Test convert-contents-base64
    result2 = await handle_call_tool("convert-contents-base64", {...})
    assert result2["status"] == "success"
```

### Test Execution Plan

```bash
# Daily development: fast tests only
pytest -m "not e2e and not performance"

# Before PR: all tests
pytest --run-all

# Generate coverage report
pytest --cov=mcp_pandoc --cov-report=html
```

---

## Risk Analysis

### Risk 1: Cherry Studio May Not Support MCP Resources

**Probability**: Medium
**Impact**: High

**Mitigation**:
- Test early with actual Cherry Studio client
- If not supported, implement fallback: HTTP file upload endpoint
- Document workaround: manual base64 encoding

**Fallback Plan**:
```python
# Add separate HTTP endpoint for file upload
@app.post("/upload")
async def upload_file():
    # Return file_id
    # User passes file_id to MCP tool
```

### Risk 2: Performance with Large Files

**Probability**: Low
**Impact**: Medium

**Mitigation**:
- `MAX_UPLOAD_BYTES` limit (default 50MB)
- Streaming for future enhancement
- Proper cleanup of temp files

### Risk 3: Security Vulnerabilities

**Probability**: Low
**Impact**: High

**Mitigation**:
- Path traversal protection (`_sanitize_filename`)
- File size validation
- Temporary file isolation (random directory names)
- Auto-cleanup in `finally` blocks

### Risk 4: Breaking Changes in MCP SDK

**Probability**: Low
**Impact**: Medium

**Mitigation**:
- Pin MCP SDK version: `mcp>=1.2.1,<2.0.0`
- Monitor MCP SDK changelog
- Integration tests catch API changes

---

## Implementation Plan

### Phase 1: Core Implementation (Day 1-2)

**Tasks**:
- [ ] Add `convert-document-resource` tool registration
- [ ] Implement `_handle_convert_document_resource()`
- [ ] Add required imports and helper functions
- [ ] Write unit tests for new functions

**Validation**: Unit tests pass

### Phase 2: Integration Testing (Day 2-3)

**Tasks**:
- [ ] Write integration tests with mocked MCP session
- [ ] Test error scenarios (file not found, too large, etc.)
- [ ] Run backward compatibility tests
- [ ] Fix any issues discovered

**Validation**: All tests pass (unit + integration)

### Phase 3: E2E Testing (Day 3-4)

**Tasks**:
- [ ] Deploy to test environment
- [ ] Test with Cherry Studio (manual)
- [ ] Document actual Cherry Studio behavior
- [ ] Implement workarounds if needed

**Validation**: Works in real-world scenario or fallback documented

### Phase 4: Documentation & Deployment (Day 4-5)

**Tasks**:
- [ ] Update README with new tool usage
- [ ] Create user guide for GUI clients
- [ ] Update API documentation
- [ ] Create deployment guide
- [ ] Merge to main branch

**Validation**: Documentation complete, production-ready

---

## Success Criteria

### Must Have

- ✅ New `convert-document-resource` tool implemented
- ✅ Can read Resources from MCP clients (if supported)
- ✅ All existing tools continue working (backward compatible)
- ✅ Unit tests: >80% coverage for new code
- ✅ Integration tests: Pass all scenarios
- ✅ Security: Path traversal protection, size limits
- ✅ Documentation: Complete usage guide

### Should Have

- ✅ E2E test with actual MCP client
- ✅ Performance: Handle 10MB files efficiently
- ✅ Error handling: Clear error messages
- ✅ Logging: Detailed logs for debugging

### Nice to Have

- ⭐ Cherry Studio native support works
- ⭐ Example client implementation
- ⭐ Video tutorial

---

## Alternatives Considered

### Alternative 1: HTTP File Upload Endpoint

**Approach**: Add `/upload` endpoint outside MCP protocol

**Pros**:
- Works with any HTTP client
- No dependency on MCP Resource support
- Simple to implement

**Cons**:
- Not part of MCP protocol
- Requires two steps (upload, then call tool)
- Session management complexity

**Decision**: Keep as fallback option

### Alternative 2: Client-Side Bridge/Extension

**Approach**: Browser extension reads files, injects base64 into tool calls

**Pros**:
- No server changes needed
- Works with current implementation

**Cons**:
- Requires user to install extension
- Limited to browser-based clients
- Maintenance burden

**Decision**: Rejected - too much client-side complexity

### Alternative 3: Migrate to FastMCP

**Approach**: Rewrite using FastMCP for simpler Resource handling

**Pros**:
- FastMCP has `ctx.read_resource()` - very simple
- Less boilerplate code
- Active community

**Cons**:
- Complete rewrite (1-2 days work)
- Not official Anthropic SDK
- Breaking change for current codebase

**Decision**: Rejected - stay with official MCP SDK

---

## Appendix A: Key Code Locations

| Component | File | Line Range |
|-----------|------|------------|
| Tool registration | `src/mcp_pandoc/server.py` | `handle_list_tools()` |
| Tool routing | `src/mcp_pandoc/server.py` | `handle_call_tool()` |
| Resource handler | `src/mcp_pandoc/server.py` | `_handle_convert_document_resource()` |
| Config | `src/mcp_pandoc/config.py` | `MAX_UPLOAD_BYTES` |
| Tests | `tests/test_resource_*.py` | All |

---

## Appendix B: Testing Cherry Studio

### Setup

1. Install Cherry Studio from: https://cherry-ai.com/
2. Start Pandoc MCP server:
   ```bash
   cd pandoc-mcp/pandoc
   uv run mcp-pandoc --transport streamable-http --host 127.0.0.1 --port 8001
   ```
3. In Cherry Studio settings:
   - Add MCP Server
   - URL: `http://127.0.0.1:8001/mcp`
   - Transport: `streamable-http`

### Test Case 1: Basic Markdown Conversion

1. Create `test.md`:
   ```markdown
   # Hello World

   This is a test document.
   ```
2. In Cherry Studio:
   - Attach `test.md`
   - Message: "Use convert-document-resource to convert this to HTML"
3. Expected outcomes:
   - **Success**: Returns HTML content
   - **Failure**: Error message about Resource not found

### Test Case 2: DOCX Conversion

1. Upload actual `sample.docx`
2. Request conversion to markdown
3. Observe behavior

### Results Logging

Document what actually happens:
- Does Cherry Studio provide Resource URIs?
- What format are the URIs?
- Does the server successfully read them?
- Any errors encountered?

---

## Appendix C: Fallback Implementation

If Cherry Studio doesn't support MCP Resources:

### Option 1: Separate Upload Endpoint

```python
# Add to server.py

from starlette.responses import JSONResponse
from starlette.requests import Request

@app.post("/upload")
async def upload_file(request: Request):
    """Handle file uploads outside MCP protocol"""
    form = await request.form()
    file = form["file"]

    # Save with unique ID
    file_id = secrets.token_hex(16)
    save_path = Path(config.TEMP_DIR) / file_id

    content = await file.read()
    save_path.write_bytes(content)

    return JSONResponse({
        "file_id": file_id,
        "filename": file.filename
    })

# Then in MCP tool:
# User passes file_id instead of resource_uri
```

### Option 2: Enhance base64 Tool with Helper Script

```python
# utils/encode_file.py

import sys
import base64

def encode_file(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()
    encoded = base64.b64encode(content).decode()
    print(f'{{"filename": "{filepath}", "content_base64": "{encoded}"}}')

if __name__ == "__main__":
    encode_file(sys.argv[1])
```

User workflow:
```bash
python utils/encode_file.py document.pdf | pbcopy
# Then paste into Cherry Studio
```

---

## Revision History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-01-15 | Initial design complete | AI-Assisted |

---

## References

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [MCP Python SDK Documentation](https://github.com/anthropics/python-sdk)
- [Pandoc User Guide](https://pandoc.org/MANUAL.html)
- [Cherry Studio Project](https://cherry-ai.com/)
- [Original Pandoc MCP Development Guide](../pandoc-mcp-development-guide.md)

---

**End of Design Document**
