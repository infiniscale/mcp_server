package handler

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
)

// CrocReceiveResult contains the result of a croc receive operation
type CrocReceiveResult struct {
	Status    string `json:"status"`
	Message   string `json:"message"`
	PID       int    `json:"pid"`
	OutputDir string `json:"output_dir"`
}

// HandleCrocReceive handles the croc_receive tool
func (fs *FilesystemHandler) HandleCrocReceive(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	code, err := request.RequireString("code")
	if err != nil || code == "" {
		return mcp.NewToolResultError("code is required"), nil
	}

	// Get output directory (optional, defaults to first allowed directory)
	outputDir, _ := request.RequireString("output_dir")
	if outputDir == "" {
		if len(fs.allowedDirs) > 0 {
			// Remove trailing separator for display
			outputDir = strings.TrimSuffix(fs.allowedDirs[0], string(os.PathSeparator))
		} else {
			return mcp.NewToolResultError("no allowed directories configured"), nil
		}
	}

	// Validate output directory is within allowed directories
	validDir, err := fs.validatePath(outputDir)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("output directory validation failed: %v", err)), nil
	}

	// Check if output directory exists
	info, err := os.Stat(validDir)
	if err != nil {
		if os.IsNotExist(err) {
			return mcp.NewToolResultError(fmt.Sprintf("output directory does not exist: %s", validDir)), nil
		}
		return mcp.NewToolResultError(fmt.Sprintf("failed to check output directory: %v", err)), nil
	}
	if !info.IsDir() {
		return mcp.NewToolResultError(fmt.Sprintf("output path is not a directory: %s", validDir)), nil
	}

	// Create context with cancel for process management
	procCtx, cancel := context.WithCancel(context.Background())

	// Start croc receive process with --yes to auto-accept and --out for output directory.
	// croc v10+ defaults to the new mode; code must be provided via CROC_SECRET (not as a positional arg).
	cmd := exec.CommandContext(procCtx, "croc", "--yes", "--out", validDir)
	cmd.Env = append(os.Environ(), fmt.Sprintf("CROC_SECRET=%s", code))

	// Set working directory to output directory
	cmd.Dir = validDir

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return mcp.NewToolResultError(fmt.Sprintf("failed to create stdout pipe: %v", err)), nil
	}

	stderr, err := cmd.StderrPipe()
	if err != nil {
		cancel()
		return mcp.NewToolResultError(fmt.Sprintf("failed to create stderr pipe: %v", err)), nil
	}

	// Start the command
	if err := cmd.Start(); err != nil {
		cancel()
		return mcp.NewToolResultError(fmt.Sprintf("failed to start croc: %v", err)), nil
	}

	pid := cmd.Process.Pid

	// Create process tracker
	proc := &crocProcess{
		cmd:       cmd,
		cancel:    cancel,
		startTime: time.Now(),
		filePath:  validDir,
		status:    "receiving",
	}
	crocManager.AddProcess(pid, proc)

	// Channels for result
	resultChan := make(chan string, 1)
	errChan := make(chan error, 1)

	// Capture stdout
	go func() {
		scanner := bufio.NewScanner(stdout)
		var lines []string
		for scanner.Scan() {
			lines = append(lines, scanner.Text())
		}
		if len(lines) > 0 {
			resultChan <- strings.Join(lines, "\n")
		}
	}()

	// Capture stderr
	go func() {
		scanner := bufio.NewScanner(stderr)
		var errLines []string
		for scanner.Scan() {
			errLines = append(errLines, scanner.Text())
		}
		if len(errLines) > 0 {
			// Check if it contains error information
			errStr := strings.Join(errLines, "\n")
			if strings.Contains(strings.ToLower(errStr), "error") ||
				strings.Contains(strings.ToLower(errStr), "failed") {
				errChan <- fmt.Errorf(errStr)
			}
		}
	}()

	// Wait for process to complete or timeout
	doneChan := make(chan error, 1)
	go func() {
		doneChan <- cmd.Wait()
	}()

	select {
	case err := <-doneChan:
		crocManager.RemoveProcess(pid)
		if err != nil {
			proc.status = "failed"
			// Check if there's stderr output
			select {
			case stderrErr := <-errChan:
				return mcp.NewToolResultError(fmt.Sprintf("croc receive failed: %v", stderrErr)), nil
			default:
				return mcp.NewToolResultError(fmt.Sprintf("croc receive failed: %v", err)), nil
			}
		}
		proc.status = "completed"

		// Get output info
		var output string
		select {
		case output = <-resultChan:
		default:
			output = "File received"
		}

		return mcp.NewToolResultText(fmt.Sprintf(
			"Croc receive completed successfully.\nOutput directory: %s\n\nDetails:\n%s",
			validDir, output,
		)), nil

	case err := <-errChan:
		cancel()
		crocManager.RemoveProcess(pid)
		return mcp.NewToolResultError(fmt.Sprintf("croc error: %v", err)), nil

	case <-time.After(10 * time.Minute):
		cancel()
		crocManager.RemoveProcess(pid)
		return mcp.NewToolResultError("timeout waiting for croc transfer to complete"), nil

	case <-ctx.Done():
		cancel()
		crocManager.RemoveProcess(pid)
		return mcp.NewToolResultError("operation cancelled"), nil
	}
}
