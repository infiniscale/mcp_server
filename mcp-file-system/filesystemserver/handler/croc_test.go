package handler

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestCrocSendPathValidation(t *testing.T) {
	// Create a temporary directory as the allowed directory
	tmpDir, err := os.MkdirTemp("", "croc-test-*")
	require.NoError(t, err)
	defer os.RemoveAll(tmpDir)

	// Create a test file in the allowed directory
	testFile := filepath.Join(tmpDir, "test.txt")
	err = os.WriteFile(testFile, []byte("test content"), 0644)
	require.NoError(t, err)

	// Create handler with only tmpDir as allowed
	handler, err := NewFilesystemHandler([]string{tmpDir})
	require.NoError(t, err)

	ctx := context.Background()

	// Test 1: Should reject path outside allowed directory
	t.Run("reject path outside allowed directory", func(t *testing.T) {
		request := mcp.CallToolRequest{}
		request.Params.Arguments = map[string]any{
			"path": "/etc/passwd",
		}

		result, err := handler.HandleCrocSend(ctx, request)
		require.NoError(t, err)
		assert.True(t, result.IsError)
	})

	// Test 2: Should reject path traversal attempts
	t.Run("reject path traversal", func(t *testing.T) {
		request := mcp.CallToolRequest{}
		request.Params.Arguments = map[string]any{
			"path": filepath.Join(tmpDir, "..", "etc", "passwd"),
		}

		result, err := handler.HandleCrocSend(ctx, request)
		require.NoError(t, err)
		assert.True(t, result.IsError)
	})
}

func TestCrocReceivePathValidation(t *testing.T) {
	// Create a temporary directory as the allowed directory
	tmpDir, err := os.MkdirTemp("", "croc-test-*")
	require.NoError(t, err)
	defer os.RemoveAll(tmpDir)

	// Create handler with only tmpDir as allowed
	handler, err := NewFilesystemHandler([]string{tmpDir})
	require.NoError(t, err)

	ctx := context.Background()

	// Test: Should reject output directory outside allowed directory
	t.Run("reject output dir outside allowed directory", func(t *testing.T) {
		request := mcp.CallToolRequest{}
		request.Params.Arguments = map[string]any{
			"code":       "test-code",
			"output_dir": "/tmp/unauthorized",
		}

		result, err := handler.HandleCrocReceive(ctx, request)
		require.NoError(t, err)
		assert.True(t, result.IsError)
	})
}

func TestCrocProcessManager(t *testing.T) {
	manager := &CrocProcessManager{
		processes: make(map[int]*crocProcess),
	}

	// Test AddProcess and GetProcess
	t.Run("add and get process", func(t *testing.T) {
		proc := &crocProcess{
			status:   "waiting",
			filePath: "/test/path",
		}
		manager.AddProcess(12345, proc)

		retrieved, exists := manager.GetProcess(12345)
		assert.True(t, exists)
		assert.Equal(t, "waiting", retrieved.status)
	})

	// Test ListProcesses
	t.Run("list processes", func(t *testing.T) {
		processes := manager.ListProcesses()
		assert.Len(t, processes, 1)
	})

	// Test RemoveProcess
	t.Run("remove process", func(t *testing.T) {
		manager.RemoveProcess(12345)
		_, exists := manager.GetProcess(12345)
		assert.False(t, exists)
	})
}

func TestCrocStatus(t *testing.T) {
	// Create a temporary directory as the allowed directory
	tmpDir, err := os.MkdirTemp("", "croc-test-*")
	require.NoError(t, err)
	defer os.RemoveAll(tmpDir)

	// Create handler
	handler, err := NewFilesystemHandler([]string{tmpDir})
	require.NoError(t, err)

	ctx := context.Background()

	// Test: Should return empty status when no processes
	t.Run("empty status", func(t *testing.T) {
		// Clear any existing processes
		crocManager.CleanupAllProcesses()

		request := mcp.CallToolRequest{}
		result, err := handler.HandleCrocStatus(ctx, request)
		require.NoError(t, err)
		assert.False(t, result.IsError)
		// Should contain "No active" message
		assert.Contains(t, result.Content[0].(mcp.TextContent).Text, "No active")
	})
}
