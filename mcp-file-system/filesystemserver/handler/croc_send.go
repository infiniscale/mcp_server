package handler

import (
	"bufio"
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
)

// CrocSendResult contains the result of a croc send operation
type CrocSendResult struct {
	Code    string `json:"code"`
	Status  string `json:"status"`
	Message string `json:"message"`
	PID     int    `json:"pid"`
}

// crocProcess tracks a running croc process
type crocProcess struct {
	cmd       *exec.Cmd
	cancel    context.CancelFunc
	code      string
	startTime time.Time
	filePath  string
	status    string // "waiting", "transferring", "completed", "failed"
}

// CrocProcessManager manages croc processes
type CrocProcessManager struct {
	mu        sync.RWMutex
	processes map[int]*crocProcess
}

var crocManager = &CrocProcessManager{
	processes: make(map[int]*crocProcess),
}

// CleanupAllProcesses terminates all active croc processes
// Call this when the MCP server is shutting down
func (m *CrocProcessManager) CleanupAllProcesses() {
	m.mu.Lock()
	defer m.mu.Unlock()

	for pid, proc := range m.processes {
		if proc.cancel != nil {
			proc.cancel()
		}
		if proc.cmd != nil && proc.cmd.Process != nil {
			proc.cmd.Process.Kill()
		}
		delete(m.processes, pid)
	}
}

// GetCrocManager returns the global croc process manager
func GetCrocManager() *CrocProcessManager {
	return crocManager
}

// AddProcess adds a process to the manager
func (m *CrocProcessManager) AddProcess(pid int, proc *crocProcess) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.processes[pid] = proc
}

// GetProcess gets a process by PID
func (m *CrocProcessManager) GetProcess(pid int) (*crocProcess, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	proc, ok := m.processes[pid]
	return proc, ok
}

// RemoveProcess removes a process from the manager
func (m *CrocProcessManager) RemoveProcess(pid int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.processes, pid)
}

// ListProcesses returns all active processes
func (m *CrocProcessManager) ListProcesses() map[int]*crocProcess {
	m.mu.RLock()
	defer m.mu.RUnlock()
	result := make(map[int]*crocProcess)
	for k, v := range m.processes {
		result[k] = v
	}
	return result
}

// HandleCrocSend handles the croc_send tool
func (fs *FilesystemHandler) HandleCrocSend(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	path, err := request.RequireString("path")
	if err != nil {
		return mcp.NewToolResultError("path is required"), nil
	}

	// Validate path is within allowed directories
	validPath, err := fs.validatePath(path)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("path validation failed: %v", err)), nil
	}

	// Create context with cancel for process management
	procCtx, cancel := context.WithCancel(context.Background())

	// Start croc send process
	cmd := exec.CommandContext(procCtx, "croc", "send", validPath)

	// Get stdout pipe to capture the code
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
		filePath:  validPath,
		status:    "waiting",
	}
	crocManager.AddProcess(pid, proc)

	// Channel to receive the code
	codeChan := make(chan string, 1)
	errChan := make(chan error, 1)

	// Parse stdout for the code in a goroutine
	go func() {
		scanner := bufio.NewScanner(stdout)
		// Pattern to match croc code: "Code is: xxx-xxx-xxx" or similar
		codePattern := regexp.MustCompile(`Code is:\s*(\S+)`)

		for scanner.Scan() {
			line := scanner.Text()
			if matches := codePattern.FindStringSubmatch(line); len(matches) > 1 {
				codeChan <- matches[1]
				return
			}
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
			errChan <- fmt.Errorf(strings.Join(errLines, "\n"))
		}
	}()

	// Wait for code with timeout
	select {
	case code := <-codeChan:
		proc.code = code
		proc.status = "waiting"

		// Start goroutine to monitor process completion
		go func() {
			err := cmd.Wait()
			if err != nil {
				proc.status = "failed"
			} else {
				proc.status = "completed"
			}
			// Clean up after some time
			time.AfterFunc(5*time.Minute, func() {
				crocManager.RemoveProcess(pid)
			})
		}()

		return mcp.NewToolResultText(fmt.Sprintf(
			"Croc send started successfully.\nCode: %s\nPID: %d\nFile: %s\n\nShare this code with the recipient to receive the file.",
			code, pid, validPath,
		)), nil

	case err := <-errChan:
		cancel()
		crocManager.RemoveProcess(pid)
		return mcp.NewToolResultError(fmt.Sprintf("croc error: %v", err)), nil

	case <-time.After(30 * time.Second):
		cancel()
		crocManager.RemoveProcess(pid)
		return mcp.NewToolResultError("timeout waiting for croc code"), nil

	case <-ctx.Done():
		cancel()
		crocManager.RemoveProcess(pid)
		return mcp.NewToolResultError("operation cancelled"), nil
	}
}
