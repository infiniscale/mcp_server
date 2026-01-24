package filesystemserver

import (
	"github.com/mark3labs/mcp-filesystem-server/filesystemserver/handler"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

var Version = "dev"

func NewFilesystemServer(allowedDirs []string) (*server.MCPServer, error) {

	h, err := handler.NewFilesystemHandler(allowedDirs)
	if err != nil {
		return nil, err
	}

	s := server.NewMCPServer(
		"secure-filesystem-server",
		Version,
		server.WithResourceCapabilities(true, true),
	)

	// Register resource handlers
	s.AddResource(mcp.NewResource(
		"file://",
		"File System",
		mcp.WithResourceDescription("Access to files and directories on the local file system"),
	), h.HandleReadResource)

	// Register tool handlers
	s.AddTool(mcp.NewTool(
		"read_file",
		mcp.WithDescription("Read the complete contents of a file from the file system."),
		mcp.WithString("path",
			mcp.Description("Path to the file to read"),
			mcp.Required(),
		),
	), h.HandleReadFile)

	s.AddTool(mcp.NewTool(
		"write_file",
		mcp.WithDescription("Create a new file or overwrite an existing file with new content."),
		mcp.WithString("path",
			mcp.Description("Path where to write the file"),
			mcp.Required(),
		),
		mcp.WithString("content",
			mcp.Description("Content to write to the file"),
			mcp.Required(),
		),
	), h.HandleWriteFile)

	s.AddTool(mcp.NewTool(
		"list_directory",
		mcp.WithDescription("Get a detailed listing of all files and directories in a specified path."),
		mcp.WithString("path",
			mcp.Description("Path of the directory to list"),
			mcp.Required(),
		),
	), h.HandleListDirectory)

	s.AddTool(mcp.NewTool(
		"create_directory",
		mcp.WithDescription("Create a new directory or ensure a directory exists."),
		mcp.WithString("path",
			mcp.Description("Path of the directory to create"),
			mcp.Required(),
		),
	), h.HandleCreateDirectory)

	s.AddTool(mcp.NewTool(
		"copy_file",
		mcp.WithDescription("Copy files and directories."),
		mcp.WithString("source",
			mcp.Description("Source path of the file or directory"),
			mcp.Required(),
		),
		mcp.WithString("destination",
			mcp.Description("Destination path"),
			mcp.Required(),
		),
	), h.HandleCopyFile)

	s.AddTool(mcp.NewTool(
		"move_file",
		mcp.WithDescription("Move or rename files and directories."),
		mcp.WithString("source",
			mcp.Description("Source path of the file or directory"),
			mcp.Required(),
		),
		mcp.WithString("destination",
			mcp.Description("Destination path"),
			mcp.Required(),
		),
	), h.HandleMoveFile)

	s.AddTool(mcp.NewTool(
		"search_files",
		mcp.WithDescription("Recursively search for files and directories matching a pattern."),
		mcp.WithString("path",
			mcp.Description("Starting path for the search"),
			mcp.Required(),
		),
		mcp.WithString("pattern",
			mcp.Description("Search pattern to match against file names"),
			mcp.Required(),
		),
	), h.HandleSearchFiles)

	s.AddTool(mcp.NewTool(
		"get_file_info",
		mcp.WithDescription("Retrieve detailed metadata about a file or directory."),
		mcp.WithString("path",
			mcp.Description("Path to the file or directory"),
			mcp.Required(),
		),
	), h.HandleGetFileInfo)

	s.AddTool(mcp.NewTool(
		"list_allowed_directories",
		mcp.WithDescription("Returns the list of directories that this server is allowed to access."),
	), h.HandleListAllowedDirectories)

	s.AddTool(mcp.NewTool(
		"read_multiple_files",
		mcp.WithDescription("Read the contents of multiple files in a single operation."),
		mcp.WithArray("paths",
			mcp.Description("List of file paths to read"),
			mcp.Required(),
			mcp.Items(map[string]any{"type": "string"}),
		),
	), h.HandleReadMultipleFiles)

	s.AddTool(mcp.NewTool(
		"tree",
		mcp.WithDescription("Returns a hierarchical JSON representation of a directory structure."),
		mcp.WithString("path",
			mcp.Description("Path of the directory to traverse"),
			mcp.Required(),
		),
		mcp.WithNumber("depth",
			mcp.Description("Maximum depth to traverse (default: 3)"),
		),
		mcp.WithBoolean("follow_symlinks",
			mcp.Description("Whether to follow symbolic links (default: false)"),
		),
	), h.HandleTree)

	s.AddTool(mcp.NewTool(
		"delete_file",
		mcp.WithDescription("Delete a file or directory from the file system."),
		mcp.WithString("path",
			mcp.Description("Path to the file or directory to delete"),
			mcp.Required(),
		),
		mcp.WithBoolean("recursive",
			mcp.Description("Whether to recursively delete directories (default: false)"),
		),
	), h.HandleDeleteFile)

	s.AddTool(mcp.NewTool(
		"modify_file",
		mcp.WithDescription("Update file by finding and replacing text. Provides a simple pattern matching interface without needing exact character positions."),
		mcp.WithString("path",
			mcp.Description("Path to the file to modify"),
			mcp.Required(),
		),
		mcp.WithString("find",
			mcp.Description("Text to search for (exact match or regex pattern)"),
			mcp.Required(),
		),
		mcp.WithString("replace",
			mcp.Description("Text to replace with"),
			mcp.Required(),
		),
		mcp.WithBoolean("all_occurrences",
			mcp.Description("Replace all occurrences of the matching text (default: true)"),
		),
		mcp.WithBoolean("regex",
			mcp.Description("Treat the find pattern as a regular expression (default: false)"),
		),
	), h.HandleModifyFile)

	s.AddTool(mcp.NewTool(
		"search_within_files",
		mcp.WithDescription("Search for text within file contents. Unlike search_files which only searches file names, this tool scans the actual contents of text files for matching substrings. Binary files are automatically excluded from the search. Reports file paths and line numbers where matches are found."),
		mcp.WithString("path",
			mcp.Description("Starting path for the search (must be a directory)"),
			mcp.Required(),
		),
		mcp.WithString("substring",
			mcp.Description("Text to search for within file contents"),
			mcp.Required(),
		),
		mcp.WithNumber("depth",
			mcp.Description("Maximum directory depth to search (default: unlimited)"),
		),
		mcp.WithNumber("max_results",
			mcp.Description("Maximum number of results to return (default: 1000)"),
		),
	), h.HandleSearchWithinFiles)

	// Croc file transfer tools
	s.AddTool(mcp.NewTool(
		"croc_send",
		mcp.WithDescription(`【客户端·文件传输工具】将本地文件发送到远端服务器。

## 核心用途
将客户端本地文件传输到配置了 MinerU 转换服务的远端服务器进行处理。

## 返回值
返回随机 croc code（例如 'k3m9u2x1q8'），此 code 需传递给服务端 convert_to_markdown 工具（推荐使用 croc_code 参数，或直接用 source 传入）。

## 典型工作流
1. 客户端调用 croc_send(path='/local/file.pdf') → 获取 code
2. 将 code 传给服务端 convert_to_markdown(croc_code='k3m9u2x1q8') → 服务端接收并转换

## 注意
- 进程在后台运行，等待接收方连接
- 使用 croc_status 查看传输状态
- 使用 croc_cancel 取消传输`),
		mcp.WithString("path",
			mcp.Description("Path to the file or folder to send"),
			mcp.Required(),
		),
	), h.HandleCrocSend)

	s.AddTool(mcp.NewTool(
		"croc_receive",
		mcp.WithDescription("Receive a file from another machine using croc. Requires the code provided by the sender."),
		mcp.WithString("code",
			mcp.Description("The croc code provided by the sender"),
			mcp.Required(),
		),
		mcp.WithString("output_dir",
			mcp.Description("Directory to save the received file (defaults to first allowed directory)"),
		),
	), h.HandleCrocReceive)

	s.AddTool(mcp.NewTool(
		"croc_status",
		mcp.WithDescription("List all active croc file transfers and their status."),
	), h.HandleCrocStatus)

	s.AddTool(mcp.NewTool(
		"croc_cancel",
		mcp.WithDescription("Cancel an active croc file transfer by its process ID."),
		mcp.WithNumber("pid",
			mcp.Description("Process ID of the croc transfer to cancel"),
			mcp.Required(),
		),
	), h.HandleCrocCancel)

	return s, nil
}
