# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

```bash
# Build the server
go build -o mcp-filesystem-server .

# Run tests with race detection
go test -race ./...

# Run a specific test
go test -race -run TestFunctionName ./filesystemserver/handler/

# Run the server (stdio mode, requires allowed directories)
./mcp-filesystem-server /path/to/allowed/directory [/another/directory ...]

# Tidy dependencies
go mod tidy
```

## Architecture

This is a Go-based MCP (Model Context Protocol) server providing secure filesystem access via stdio.

### Code Structure

```
main.go                          # Entry point, starts stdio server
filesystemserver/
├── server.go                    # Server factory, registers all MCP tools
└── handler/
    ├── handler.go               # FilesystemHandler struct, directory normalization
    ├── helper.go                # Path validation, symlink resolution, MIME detection
    ├── types.go                 # Shared types (FileNode, etc.)
    ├── resources.go             # MCP resource handlers (file:// protocol)
    ├── croc_send.go             # Cross-machine file send via croc
    ├── croc_receive.go          # Cross-machine file receive
    ├── croc_status.go           # Transfer status/cancel
    └── [tool]_[test].go         # Individual tool implementations with tests
```

### Security Model

All file operations are restricted to explicitly allowed directories:

1. **Path Validation** (`validatePath` in helper.go):
   - Converts paths to absolute
   - Resolves symlinks and verifies targets stay within allowed directories
   - Prevents directory traversal attacks

2. **Directory Normalization** (handler.go:35-40):
   - Paths stored with trailing separator to prevent prefix-matching attacks
   - `/tmp/foo` won't match `/tmp/foobar`

### Adding a New Tool

1. Create `filesystemserver/handler/[tool_name].go` with handler function:
   ```go
   func (fs *FilesystemHandler) HandleToolName(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error)
   ```

2. Register in `filesystemserver/server.go`:
   ```go
   s.AddTool(mcp.NewTool("tool_name", mcp.WithDescription("..."), ...), h.HandleToolName)
   ```

3. Use `request.RequireString("param")` for required params, `request.RequireFloat("param")` for optional numbers

### Key Patterns

- **Parameter Access**: Use `request.RequireString()`, `request.RequireFloat()`, `request.RequireBool()` - not direct map access
- **Error Results**: Return `mcp.NewToolResultError("message")` for user-facing errors
- **Success Results**: Return `mcp.NewToolResultText("message")` for text responses

## MCP Integration

The server uses **stdio mode** (stdin/stdout), not HTTP. Configure in MCP clients:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "./mcp-filesystem-server",
      "args": ["/allowed/directory"]
    }
  }
}
```

## Prerequisites

- Go 1.21+
- For croc tools: `brew install croc` (macOS) or `apt install croc` (Ubuntu)
