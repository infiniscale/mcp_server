# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository hosts MCP (Model Context Protocol) server implementations. Currently contains the `mcp-file-system` submodule, a Go-based filesystem MCP server providing secure file operations.

## Build and Development Commands

All commands should be run from the `mcp-file-system/` directory:

```bash
# Build the server
go build -o mcp-filesystem-server .

# Run tests with race detection
go test -race ./...

# Run a specific test
go test -race -run TestFunctionName ./filesystemserver/handler/

# Run the server (requires allowed directories as args)
./mcp-filesystem-server /path/to/allowed/directory

# Install globally
go install github.com/mark3labs/mcp-filesystem-server@latest

# Tidy dependencies
go mod tidy
```

## Architecture

### mcp-file-system (Go Submodule)

The filesystem MCP server implements the Model Context Protocol using the `mcp-go` library.

**Core Components:**

- `main.go` - Entry point, parses CLI args and starts the stdio server
- `filesystemserver/server.go` - Server factory that registers all tools and resources with the MCP server
- `filesystemserver/handler/` - Contains all tool implementations:
  - `handler.go` - `FilesystemHandler` struct managing allowed directories
  - `helper.go` - Path validation, symlink resolution, MIME type detection
  - Individual tool files: `read_file.go`, `write_file.go`, `list_directory.go`, `search_files.go`, etc.
  - Croc tools: `croc_send.go`, `croc_receive.go`, `croc_status.go` - Cross-machine file transfer via croc

**Security Model:**

The server restricts access to explicitly allowed directories. Key validation logic:
- `isPathInAllowedDirs()` validates paths against whitelist
- `validatePath()` resolves symlinks and verifies real paths stay within allowed directories
- Paths are normalized with trailing separators to prevent prefix-matching attacks (e.g., `/tmp/foo` won't match `/tmp/foobar`)

**Dependencies:**
- `github.com/mark3labs/mcp-go` - MCP protocol implementation
- `github.com/gabriel-vasile/mimetype` - File type detection
- `github.com/gobwas/glob` - Glob pattern matching

## MCP Integration

Configure in MCP-supporting apps:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-filesystem-server",
      "args": ["/path/to/allowed/directory"]
    }
  }
}
```

## Testing

Tests are colocated with source files (`*_test.go`). The CI runs tests across Linux, Windows, and macOS.

## Prerequisites for Croc

For cross-machine file transfer functionality, croc must be installed:
```bash
brew install croc    # macOS
apt install croc     # Ubuntu
```
