package handler

import (
	"context"
	"fmt"
	"strings"
	"syscall"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
)

// HandleCrocStatus handles the croc_status tool - lists active croc processes
func (fs *FilesystemHandler) HandleCrocStatus(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	processes := crocManager.ListProcesses()

	if len(processes) == 0 {
		return mcp.NewToolResultText("No active croc transfers."), nil
	}

	var sb strings.Builder
	sb.WriteString("Active Croc Transfers:\n")
	sb.WriteString("======================\n\n")

	for pid, proc := range processes {
		sb.WriteString(fmt.Sprintf("PID: %d\n", pid))
		sb.WriteString(fmt.Sprintf("  Status: %s\n", proc.status))
		sb.WriteString(fmt.Sprintf("  File/Dir: %s\n", proc.filePath))
		if proc.code != "" {
			sb.WriteString(fmt.Sprintf("  Code: %s\n", proc.code))
		}
		sb.WriteString(fmt.Sprintf("  Started: %s\n", proc.startTime.Format(time.RFC3339)))
		sb.WriteString(fmt.Sprintf("  Duration: %s\n", time.Since(proc.startTime).Round(time.Second)))
		sb.WriteString("\n")
	}

	return mcp.NewToolResultText(sb.String()), nil
}

// HandleCrocCancel handles the croc_cancel tool - cancels a croc transfer
func (fs *FilesystemHandler) HandleCrocCancel(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	pidFloat, err := request.RequireFloat("pid")
	if err != nil {
		return mcp.NewToolResultError("pid is required and must be a number"), nil
	}
	pid := int(pidFloat)

	proc, exists := crocManager.GetProcess(pid)
	if !exists {
		return mcp.NewToolResultError(fmt.Sprintf("no croc process found with PID %d", pid)), nil
	}

	// Cancel the process
	if proc.cancel != nil {
		proc.cancel()
	}

	// Also try to kill the process directly
	if proc.cmd != nil && proc.cmd.Process != nil {
		proc.cmd.Process.Signal(syscall.SIGTERM)
	}

	proc.status = "cancelled"
	crocManager.RemoveProcess(pid)

	return mcp.NewToolResultText(fmt.Sprintf("Croc transfer with PID %d has been cancelled.", pid)), nil
}
