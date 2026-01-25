# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository hosts MCP (Model Context Protocol) server implementations for secure filesystem access and document-to-Markdown conversion.

**Components:**

| Component | Language | Purpose |
|-----------|----------|---------|
| `mcp-file-system/` | Go | Secure filesystem MCP server with croc file transfer |
| `mcp_convert_router/` | Python | Unified document conversion with multi-engine routing |
| `mcp_mineru/` | Python | MinerU API wrapper (FastMCP-based) |
| `mcp_pandoc/` | Python | Lightweight Pandoc wrapper |

## Build and Development Commands

### mcp-file-system (Go)

```bash
cd mcp-file-system

go build -o mcp-filesystem-server .          # Build
go test -race ./...                           # Run all tests with race detection
go test -race -run TestFunctionName ./filesystemserver/handler/  # Run specific test
./mcp-filesystem-server /allowed/dir          # Run (stdio mode)
go mod tidy                                   # Tidy dependencies
```

### mcp_convert_router (Python)

```bash
# Run server (from repo root)
python -m mcp_convert_router.server

# Run tests
python test_convert_router.py

# Docker build
cd mcp_convert_router
docker build -t mcp-convert-router:latest .
docker build --build-arg INSTALL_LIBREOFFICE=1 -t mcp-convert-router:latest .  # With LibreOffice

# Dry-run config validation
python -m mcp_convert_router.server --dry-run
```

### mcp_mineru (Python)

```bash
cd mcp_mineru

uv pip install -e .                           # Install in dev mode
uv run mineru-mcp                             # Run server
uv run mineru-mcp --transport sse             # SSE mode
uv run mineru-mcp --transport streamable-http # HTTP mode

# Docker
docker-compose up -d
```

## Architecture

### mcp-file-system

Go MCP server using `mcp-go` library with stdio transport.

**Structure:**
- `main.go` - Entry point, parses allowed directories from CLI args
- `filesystemserver/server.go` - Server factory, registers all MCP tools
- `filesystemserver/handler/` - Tool implementations:
  - `handler.go` - `FilesystemHandler` struct, directory normalization
  - `helper.go` - Path validation, symlink resolution, MIME detection
  - `croc_*.go` - Cross-machine file transfer via croc

**Security Model:**
- All operations restricted to explicitly allowed directories
- `validatePath()` resolves symlinks and verifies containment
- Trailing separator normalization prevents prefix-matching attacks (`/tmp/foo` won't match `/tmp/foobar`)

**Adding a Tool:**
1. Create `filesystemserver/handler/[tool_name].go` with handler function
2. Register in `filesystemserver/server.go` via `s.AddTool(...)`
3. Use `request.RequireString("param")` for required parameters

### mcp_convert_router

Python MCP server with multi-engine document conversion.

**Structure:**
- `server.py` - MCP server main entry (stdio/SSE/HTTP transport)
- `routing.py` - Engine selection logic (auto/pandoc/mineru/excel)
- `validators.py` - Input validation, path/URL/croc code detection
- `file_detector.py` - Magic bytes + OOXML detection
- `zip_security.py` - ZIP bomb protection
- `url_downloader.py` - SSRF-protected URL download
- `croc_receiver.py` - Croc file receive
- `engines/` - Conversion engines (pandoc, mineru, excel, legacy_office)

**Flow:** Input normalization → Type detection → Engine selection → Execution → Structured response

**Error Codes:** `E_INPUT_MISSING`, `E_PATH_TRAVERSAL`, `E_URL_FORBIDDEN`, `E_PANDOC_FAILED`, `E_MINERU_FAILED`, `E_ZIP_BOMB_DETECTED`, etc.

### mcp_mineru

FastMCP-based MinerU API wrapper.

**Structure:**
- `src/mineru/server.py` - FastMCP server
- `src/mineru/api.py` - MinerU API client
- `src/mineru/cli.py` - CLI entry point
- `src/mineru/config.py` - Configuration from env vars

**Tools:** `parse_documents`, `get_ocr_languages`, `parse_documents_base64`

## MCP Integration

### mcp-file-system
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-filesystem-server",
      "args": ["/allowed/directory"]
    }
  }
}
```

### mcp_convert_router
```json
{
  "mcpServers": {
    "convert-router": {
      "command": "python",
      "args": ["-m", "mcp_convert_router.server"],
      "env": { "MINERU_API_KEY": "your_key" }
    }
  }
}
```

### mcp_mineru
```json
{
  "mcpServers": {
    "mineru-mcp": {
      "command": "uvx",
      "args": ["mineru-mcp"],
      "env": {
        "MINERU_API_KEY": "your_key",
        "USE_LOCAL_API": "false"
      }
    }
  }
}
```

## Environment Variables

### mcp_convert_router

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_CONVERT_TEMP_DIR` | `/tmp/mcp-convert` | Temp directory |
| `MCP_CONVERT_MAX_FILE_MB` | `50` | Max file size |
| `MCP_CONVERT_ALLOWED_INPUT_ROOTS` | - | Whitelist for local paths (comma-separated) |
| `MINERU_API_KEY` | - | MinerU API key |
| `USE_LOCAL_API` | `false` | Use local MinerU instead of cloud |
| `MCP_TRANSPORT` | `stdio` | Transport mode (stdio/sse/streamable-http) |

### mcp_mineru

| Variable | Default | Description |
|----------|---------|-------------|
| `MINERU_API_KEY` | - | MinerU API key |
| `USE_LOCAL_API` | `false` | Use local MinerU API |
| `LOCAL_MINERU_API_BASE` | `http://localhost:8080` | Local API URL |
| `OUTPUT_DIR` | `./downloads` | Output directory |

## Testing

- **Go tests** are colocated (`*_test.go`), run with `go test -race ./...`
- **Python tests** are in root: `test_convert_router.py`, `test_mineru.py`, `test_pandoc.py`
- Test fixtures are in `test_fixtures/`

## Prerequisites

- **Go 1.21+** for mcp-file-system
- **Python 3.10+** for Python components
- **Pandoc** for document conversion
- **croc** for cross-machine file transfer: `brew install croc` (macOS) or `apt install croc`
- **LibreOffice** (optional) for legacy doc/xls/ppt formats
