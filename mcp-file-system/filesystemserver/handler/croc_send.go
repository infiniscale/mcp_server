package handler

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"os/exec"
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

// Default timeout for waiting for recipient (seconds)
const DefaultCrocSendTimeout = 300

// CrocSendResponse is the JSON response for croc_send
type CrocSendResponse struct {
	Code     string `json:"code"`
	Status   string `json:"status"`
	FileName string `json:"file_name"`
	FileSize int64  `json:"file_size"`
	PID      int    `json:"pid"`
}

// generateRandomCode generates a random 6-character alphanumeric code
func generateRandomCode() string {
	const charset = "abcdefghijklmnopqrstuvwxyz0123456789"
	code := make([]byte, 6)
	for i := range code {
		n, _ := rand.Int(rand.Reader, big.NewInt(int64(len(charset))))
		code[i] = charset[n.Int64()]
	}
	return string(code)
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

	// Get file info for the response
	fileInfo, err := os.Stat(validPath)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("failed to get file info: %v", err)), nil
	}
	fileName := fileInfo.Name()
	fileSize := fileInfo.Size()

	// Generate random 6-character code
	code := generateRandomCode()

	// Create context with cancel for process management
	procCtx, cancel := context.WithCancel(context.Background())

	// Build croc send command with generated code
	args := []string{"send", "--code", code, validPath}

	// Start croc send process
	cmd := exec.CommandContext(procCtx, "croc", args...)

	// Get stdout and stderr pipes for monitoring
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
		code:      code,
		startTime: time.Now(),
		filePath:  validPath,
		status:    "waiting_for_receiver",
	}
	crocManager.AddProcess(pid, proc)

	// Monitor process in background
	go func() {
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()
			if strings.Contains(line, "Sending") {
				proc.status = "transferring"
			}
		}
	}()

	go func() {
		scanner := bufio.NewScanner(stderr)
		var errLines []string
		for scanner.Scan() {
			errLines = append(errLines, scanner.Text())
		}
		if len(errLines) > 0 {
			proc.status = "failed"
		}
	}()

	// Monitor process completion in background
	go func() {
		err := cmd.Wait()
		if err != nil {
			proc.status = "failed"
		} else {
			proc.status = "completed"
		}
		// Clean up after 5 minutes
		time.AfterFunc(5*time.Minute, func() {
			crocManager.RemoveProcess(pid)
		})
	}()

	// Return immediately with the generated code (async pattern)
	response := CrocSendResponse{
		Code:     code,
		Status:   "waiting_for_receiver",
		FileName: fileName,
		FileSize: fileSize,
		PID:      pid,
	}

	jsonBytes, err := json.Marshal(response)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("failed to marshal response: %v", err)), nil
	}

	return mcp.NewToolResultText(string(jsonBytes)), nil
}

// formatFileSize formats a file size in bytes to a human-readable string
func formatFileSize(size int64) string {
	const (
		KB = 1024
		MB = 1024 * KB
		GB = 1024 * MB
	)
	switch {
	case size >= GB:
		return fmt.Sprintf("%.2f GB", float64(size)/float64(GB))
	case size >= MB:
		return fmt.Sprintf("%.2f MB", float64(size)/float64(MB))
	case size >= KB:
		return fmt.Sprintf("%.2f KB", float64(size)/float64(KB))
	default:
		return fmt.Sprintf("%d bytes", size)
	}
}
