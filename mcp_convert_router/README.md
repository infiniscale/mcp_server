# MCP Convert Router

统一的文件转 Markdown MCP 服务。支持多种输入方式（本地文件、URL、croc）和多引擎路由（Pandoc、MinerU、Excel）。

## 功能特性

- **统一入口**：`convert_to_markdown` 工具处理所有文件转换
- **多输入方式**：支持本地文件路径、URL 下载、croc 跨机器传输
- **智能路由**：根据文件类型自动选择最佳转换引擎
- **安全防护**：路径穿越检查、SSRF 防护、文件大小限制
- **标准化输出**：统一的返回结构，包含错误码和详细信息

## 快速开始

### 1. 安装依赖

```bash
# 基础依赖
pip install mcp httpx openpyxl

# 确保 Pandoc 已安装
pandoc --version

# 可选：安装 croc（用于跨机器文件传输）
brew install croc    # macOS
apt install croc     # Ubuntu
```

### 2. 配置 MinerU（可选）

如果需要使用 MinerU 引擎（处理 PDF、图片、PPT）：

```bash
# 方式一：使用远程 API
export MINERU_API_KEY="your_api_key"

# 方式二：使用本地 API
export USE_LOCAL_API=true
export LOCAL_MINERU_API_BASE="http://localhost:8080"
```

### 3. 运行服务

```bash
# 在仓库根目录运行（推荐）
python -m mcp_convert_router.server
```

### 4. Docker 运行（stdio）

> 说明：本服务使用 MCP 的 stdio 传输方式，容器运行时需要保持 stdin 打开（`docker run -i`）。

```bash
cd mcp_convert_router
docker build -t mcp-convert-router:latest .

# 仅 URL 模式（不需要挂载本地文件目录）
docker run --rm -i mcp-convert-router:latest

# 本地文件模式（把宿主机目录挂载到容器内，例如挂载到 /data）
docker run --rm -i -v /path/to/files:/data:ro mcp-convert-router:latest

# 需要旧格式 doc/xls/ppt 转换（体积会变大）
docker build --build-arg INSTALL_LIBREOFFICE=1 -t mcp-convert-router:latest .
```

## 使用示例

### 示例 1：转换本地文件

```json
{
  "tool": "convert_to_markdown",
  "arguments": {
    "file_path": "/path/to/document.docx"
  }
}
```

### 示例 2：从 URL 下载并转换

```json
{
  "tool": "convert_to_markdown",
  "arguments": {
    "url": "https://example.com/document.pdf",
    "enable_ocr": true
  }
}
```

### 示例 3：通过 croc 接收文件

```json
{
  "tool": "convert_to_markdown",
  "arguments": {
    "croc_code": "1234-word-word-word",
    "croc_timeout_seconds": 180
  }
}
```

### 示例 4：指定转换引擎

```json
{
  "tool": "convert_to_markdown",
  "arguments": {
    "file_path": "/path/to/document.docx",
    "route": "mineru",
    "enable_ocr": true
  }
}
```

## 返回结构

```json
{
  "ok": true,
  "markdown_text": "# 文档标题\n\n内容...",
  "engine_used": "pandoc",
  "attempts": [
    {
      "engine": "pandoc",
      "status": "success",
      "elapsed_ms": 234
    }
  ],
  "source_info": {
    "filename": "document.docx",
    "size_bytes": 12345,
    "detected_type": "docx"
  },
  "artifacts": {
    "work_dir": "/tmp/mcp-convert/20240120_123456_abc123",
    "output_dir": "/tmp/mcp-convert/20240120_123456_abc123/output",
    "files": ["media/image1.png"]
  },
  "warnings": []
}
```

## 支持的格式

| 格式 | 引擎 | 说明 |
|------|------|------|
| docx, html, txt, md, rst, epub, odt | Pandoc | 结构化文本 |
| pdf, png, jpg, pptx, ppt | MinerU | 版式文档、图片（支持 OCR） |
| xlsx, csv | Excel | 表格数据 |
| doc, xls, ppt | LibreOffice | 旧格式，自动转换为新格式后处理 |

## 路由规则

- **auto**（默认）：根据文件类型自动选择
  - docx/html/txt/md → Pandoc
  - pdf/图片/pptx → MinerU
  - xlsx/csv → Excel
- **pandoc/mineru/excel**：强制使用指定引擎

## 错误码

| 错误码 | 说明 |
|--------|------|
| E_INPUT_MISSING | 未提供输入（file_path/url/croc_code） |
| E_INPUT_TOO_LARGE | 文件超过大小限制 |
| E_FILE_NOT_FOUND | 文件不存在 |
| E_PATH_TRAVERSAL | 路径穿越攻击 |
| E_URL_FORBIDDEN | URL 不安全（SSRF 防护） |
| E_CROC_FAILED | croc 接收失败 |
| E_PANDOC_FAILED | Pandoc 转换失败 |
| E_MINERU_FAILED | MinerU 转换失败 |
| E_EXCEL_FAILED | Excel 解析失败 |
| E_TIMEOUT | 操作超时 |
| E_ZIP_BOMB_DETECTED | 检测到可疑 ZIP 压缩比 |
| E_ZIP_TOO_MANY_ENTRIES | ZIP 条目数过多 |
| E_ZIP_TOO_LARGE | ZIP 解压后总大小过大 |
| E_ZIP_ENTRY_TOO_LARGE | ZIP 单个条目过大 |
| E_SOFFICE_NOT_FOUND | LibreOffice 未安装 |
| E_LEGACY_CONVERT_FAILED | 旧格式转换失败 |

## 安全特性

### ZIP/OOXML 安全防护

对 docx/xlsx/pptx 等 ZIP 容器格式进行安全检查，防止 zip bomb 攻击：

- **最大条目数**：2000 个
- **最大解压后总大小**：200MB
- **单个条目最大大小**：50MB
- **最大压缩比**：100:1

### SSRF 防护

URL 下载功能包含完整的 SSRF 防护：

- 只允许 http/https 协议
- DNS 解析检查，拒绝内网/保留 IP
- 重定向次数限制，每次重定向都检查目标
- 下载大小限制

### 路径安全

- 路径穿越检查，防止 `../../etc/passwd` 等攻击
- croc 接收文件限制在指定目录

## 日志与追踪

每个请求都有唯一的 `request_id`，便于问题追踪：

```json
{
  "request_id": "20240120_123456_abc123",
  "ok": true,
  "markdown_text": "..."
}
```

日志输出格式：
```
2024-01-20 12:34:56 [INFO] [20240120_123456_abc123] [request_start] 开始处理请求
2024-01-20 12:34:56 [INFO] [20240120_123456_abc123] [file_received] 文件已接收: doc.docx
2024-01-20 12:34:56 [INFO] [20240120_123456_abc123] [type_detected] 文件类型识别: docx
2024-01-20 12:34:56 [INFO] [20240120_123456_abc123] [engine_selected] 选择引擎: pandoc
2024-01-20 12:34:57 [INFO] [20240120_123456_abc123] [conversion_complete] 转换成功
2024-01-20 12:34:57 [INFO] [20240120_123456_abc123] [request_complete] 请求处理成功
```

## MCP 配置

在 MCP 客户端中添加配置：

```json
{
  "mcpServers": {
    "convert-router": {
      "command": "python",
      "args": ["/path/to/mcp_convert_router/server.py"],
      "env": {
        "MINERU_API_KEY": "your_api_key"
      }
    }
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| MINERU_API_KEY | - | MinerU 远程 API Key |
| USE_LOCAL_API | false | 使用本地 MinerU API |
| LOCAL_MINERU_API_BASE | http://localhost:8080 | 本地 API 地址 |
| MCP_CONVERT_TEMP_DIR | /tmp/mcp-convert | 临时目录 |
| MCP_CONVERT_RETENTION_HOURS | 24 | 临时文件保留时间 |
| PANDOC_TIMEOUT | 60 | Pandoc 超时（秒） |
| MINERU_TIMEOUT | 300 | MinerU 超时（秒） |
| SOFFICE_TIMEOUT | 120 | LibreOffice 转换超时（秒） |

## 目录结构

```
mcp_convert_router/
├── server.py              # MCP Server 主入口
├── routing.py             # 路由逻辑
├── validators.py          # 输入验证
├── storage.py             # 临时存储管理
├── file_detector.py       # 文件类型识别（magic bytes）
├── zip_security.py        # ZIP 安全检查（防 zip bomb）
├── logging_utils.py       # 日志工具（request_id 追踪）
├── croc_receiver.py       # croc 接收
├── url_downloader.py      # URL 下载（含 SSRF 防护）
└── engines/
    ├── pandoc_engine.py
    ├── mineru_engine.py
    ├── excel_engine.py
    └── legacy_office_engine.py  # 旧格式转换（doc/xls/ppt）
```

## 测试

```bash
# 运行测试套件
python test_convert_router.py
```
