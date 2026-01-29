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

# 注意：croc v10+ 推荐通过环境变量 `CROC_SECRET` 传入 code；本服务在接收阶段会自动设置该变量
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

> 说明：本服务默认使用 MCP 的 stdio 传输方式，容器运行时需要保持 stdin 打开（`docker run -i`），此模式**不监听端口**。

```bash
cd mcp_convert_router
docker build -t mcp-convert-router:latest .

# 仅 URL 模式（不需要挂载本地文件目录）
docker run --rm -i -e MCP_TRANSPORT=stdio mcp-convert-router:latest

# 本地文件模式（把宿主机目录挂载到容器内，例如挂载到 /data）
docker run --rm -i -e MCP_TRANSPORT=stdio -v /path/to/files:/data:ro mcp-convert-router:latest

# 需要旧格式 doc/xls/ppt 转换（体积会变大）
docker build --build-arg INSTALL_LIBREOFFICE=1 -t mcp-convert-router:latest .
```

### 5. Docker 运行（SSE，监听端口）

如果你希望服务通过 HTTP 方式对外提供（便于容器化部署/探活/端口暴露），可以用 SSE 传输：

```bash
docker run --rm -p 8000:8000 -e MCP_TRANSPORT=sse mcp-convert-router:latest
```

SSE 模式会暴露两个 HTTP 路由（两者都必须能被客户端访问到，否则容易出现 `Error POSTing to endpoint (HTTP 404)`）：

- `GET /sse`：建立 SSE 连接
- `POST /messages`（或 `/messages/`）：客户端消息投递端点（由服务在 SSE 握手里返回）

也可以显式指定参数：

```bash
docker run --rm -p 8000:8000 mcp-convert-router:latest --transport sse --host 0.0.0.0 --port 8000
```

如果你在 Nginx/网关后面以子路径暴露（例如对外是 `/mcp`），需要配置 `--root-path`（保证 SSE 返回给客户端的消息投递地址包含前缀）：

```bash
docker run --rm -p 8000:8000 mcp-convert-router:latest --transport sse --root-path /mcp
```

或者让网关在转发时设置 `X-Forwarded-Prefix: /mcp`（服务会自动识别该头部来生成正确的消息投递地址）。

### 5.1 Docker 运行（Streamable HTTP，监听端口）

更适合“HTTP 客户端直接 POST 到服务地址”的场景（现代 MCP 客户端通常优先用它）。本镜像默认就是该模式：

```bash
docker run --rm -p 8000:8000 mcp-convert-router:latest
```

如果你不想挂在根路径 `/`，可以限制到 `/mcp`（客户端也必须指向该路径）：

```bash
docker run --rm -p 8000:8000 -e MCP_HTTP_PATH=/mcp mcp-convert-router:latest
```

### 6. 启动参数自检（双重验证）

你可以用 `--dry-run` 在不真正启动服务的情况下，确认“代码解析到的最终配置”和“容器入口参数”：

```bash
python -m mcp_convert_router.server --dry-run
docker run --rm mcp-convert-router:latest --dry-run
```

### 7. 一键验证脚本（避免 404/502）

```bash
python mcp_convert_router/verify_mcp_deploy.py --base-url http://127.0.0.1:8000
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

### 示例 4：启用 OCR 转换（扫描件/图片）

```json
{
  "tool": "convert_to_markdown",
  "arguments": {
    "file_path": "/path/to/scanned.pdf",
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

## OpenWebUI Integration

### Native MCP Support (v0.6.31+)

OpenWebUI natively supports MCP via streamable_http transport.

**Quick Setup:**

1. Start MCP server:
```bash
export MCP_TRANSPORT=streamable_http
export MCP_CONVERT_ALLOWED_URL_HOSTS="openwebui,localhost"
python -m mcp_convert_router.server
```

2. Configure in OpenWebUI:
   - Admin Settings → External Tools → Add Server
   - Type: MCP (Streamable HTTP)
   - URL: http://mcp-convert-router:25081
   - Auth: None

3. Use tools directly in chat

See [docs/openwebui/README.md](../docs/openwebui/README.md) for details.

### OpenWebUI Tool Script（备选）

如果你无法使用 OpenWebUI 原生 MCP（或希望在 OpenWebUI 内用 Tool 脚本触发转换），可使用本仓库的 `open-webui-tools/file_to_markdown.py`。

- 工具会从当前消息附件（`__files__`）读取文件；在 “重新生成（Regenerate）” 场景下也会从历史消息（`__messages__`）回溯最近一次上传的文件。
- 建议 MCP 地址使用以 `/mcp/` 结尾的 URL，避免 `POST /mcp → /mcp/` 的 307 重定向。

详见：`open-webui-tools/README.md`。

## 测试

```bash
# 运行测试套件
python test_convert_router.py
```
