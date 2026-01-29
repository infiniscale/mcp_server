# MCP Server 工具集

把各种文件（PDF、Word、Excel、图片等）转换成 Markdown，让 AI 能够读取和理解文件内容。

## 这是什么？

MCP（Model Context Protocol）是一种让 AI 助手调用外部工具的协议。本项目的核心功能是**文件转换**：把 AI 无法直接读取的文件格式转换成 Markdown 纯文本。

## 项目结构

| 目录 | 说明 |
|------|------|
| `mcp_convert_router/` | 文件转换服务（支持 PDF、Word、Excel 等） |
| `mcp-file-system/` | 文件系统操作服务（读写、搜索文件） |
| `open-webui-tools/` | OpenWebUI Tool 脚本 |

## 支持的文件格式

| 格式 | 后缀 | 说明 |
|------|------|------|
| Word | .docx, .doc | .doc 需要 LibreOffice |
| PDF | .pdf | 支持 OCR 识别扫描件 |
| Excel | .xlsx, .csv | 转换为 Markdown 表格 |
| PPT | .pptx, .ppt | 需要 MinerU |
| 图片 | .png, .jpg | OCR 识别文字 |
| 网页 | .html | 直接转换 |
| 纯文本 | .md, .txt | 直接返回 |

---

## 一、服务部署

### 1.1 mcp-file-system（本地文件操作）

用于文件系统操作（读写文件、搜索等），通过 Docker 在本地运行。

```bash
# 构建镜像
cd mcp-file-system
docker build -t mcp/filesystem:dev .
```

### 1.2 mcp-convert-router（文件格式转换）

用于文件格式转换，通过 Docker 部署在服务器上，Cherry Studio 和 OpenWebUI 共用此服务。

```bash
# 构建镜像
cd mcp_convert_router
docker build -t mcp-convert-router:latest .

# 复制并编辑环境变量配置
cp .env.template .env
# 编辑 .env 文件，配置必要的参数（见下方说明）

# 运行服务
docker run -d -p 8000:8000 --env-file .env --name mcp-convert mcp-convert-router:latest
```

> **必须配置的环境变量（编辑 `.env` 文件）：**
> - `MCP_TRANSPORT=streamable_http` - 启用 HTTP 模式
> - `MCP_PORT=8000` - 服务端口
> - `MINERU_API_KEY` - MinerU API 密钥（OCR 需要，可选）
> - `MCP_CONVERT_ALLOWED_URL_HOSTS` - 如果使用 OpenWebUI，填入 OpenWebUI 的主机名或 IP

---

## 二、Cherry Studio 配置

在 Cherry Studio 的 MCP 设置中添加以下配置：

### mcp-file-system（本地 stdio）

```json
{
  "command": "docker",
  "args": [
    "run", "-i", "--rm",
    "--name", "mcp-filesystem",
    "-v", "<本地目录>:/data",
    "mcp/filesystem:dev",
    "/data"
  ]
}
```

> `<本地目录>` - 你要让 AI 访问的文件夹路径（如 `D:\Work\Document`）

### mcp-convert-router（远程 HTTP）

```json
{
  "url": "http://<服务器IP>:<端口>",
  "transport": "streamable_http"
}
```

> `<服务器IP>:<端口>` - 部署 mcp-convert-router 的服务器地址

### 使用示例

```
用户：请把 /data/报告.docx 转换成 Markdown
AI：[调用 convert_to_markdown]
    # 年度工作报告
    ## 一、工作总结
    ...
```

```
用户：帮我读取 /data/config.json 的内容
AI：[调用 read_file]
    {
      "name": "example",
      ...
    }
```

---

## 三、OpenWebUI 配置

OpenWebUI 通过 **Tool 脚本** 调用 mcp-convert-router 服务。

### 架构说明

```
用户上传文件 → OpenWebUI → Tool 脚本 → MCP 服务 → 返回 Markdown
                              ↓
                    从 OpenWebUI 下载文件
```

### 第一步：确保 MCP 服务已部署

参考上面「1.2 mcp-convert-router」部署服务。

**注意**：`MCP_CONVERT_ALLOWED_URL_HOSTS` 必须包含 OpenWebUI 的主机名或 IP，否则文件下载会被 SSRF 防护拦截。

### 第二步：安装 Tool 脚本

1. 登录 OpenWebUI（管理员账户）
2. 进入 **Workspace → Tools → + Create a new tool**
3. 复制 `open-webui-tools/file_to_markdown.py` 的内容到编辑器
4. 保存

### 第三步：配置 Tool Valves

在 Tool 设置中配置以下参数：

| 参数 | 说明 | 示例 |
|------|------|------|
| `mcp_url` | MCP 服务地址（**必须以 `/mcp/` 结尾**） | `http://<MCP_IP>:<PORT>/mcp/` |
| `openwebui_base_url` | OpenWebUI 地址（MCP 用于下载文件） | `http://<OPENWEBUI_IP>:<PORT>` |
| `timeout_seconds` | 超时时间（秒） | `600` |

> **配置说明：**
> - `<MCP_IP>` - mcp-convert-router 服务的 IP
> - `<OPENWEBUI_IP>` - OpenWebUI 的 IP（必须是 MCP 服务能访问到的地址）

### 使用示例

1. 在 OpenWebUI 对话中上传文件
2. 告诉 AI：`请把我上传的文件转换成 Markdown`

```
用户：[上传 report.pdf] 请帮我总结这份报告
AI：[调用 file_to_markdown]
    报告要点如下：
    1. 第一季度销售额增长 15%
    ...
```

### 故障排查

| 问题 | 原因 | 解决方法 |
|------|------|----------|
| `E_URL_FORBIDDEN` | OpenWebUI 主机未在白名单 | 检查 `MCP_CONVERT_ALLOWED_URL_HOSTS` |
| 401 错误 | 文件下载认证失败 | 检查用户是否已登录 |
| 连接超时 | 网络不通 | 检查防火墙和端口 |
| TLS 错误 | 自签名证书 | 设置 `MCP_CONVERT_URL_TLS_VERIFY=false` |

---

## 五、常见问题

### 服务启动失败

| 问题 | 原因 | 解决方法 |
|------|------|----------|
| `docker: command not found` | Docker 未安装 | 安装 Docker Desktop |
| `port is already allocated` | 端口被占用 | 换一个端口或停止占用该端口的服务 |
| `pandoc: command not found` | Pandoc 未安装（非 Docker 模式） | `apt install pandoc` 或 `brew install pandoc` |
| 容器启动后立即退出 | 环境变量配置错误 | 用 `docker logs mcp-convert` 查看错误日志 |

### 连接失败

| 问题 | 原因 | 解决方法 |
|------|------|----------|
| `Connection refused` | 服务未启动或端口不对 | 确认服务运行中：`docker ps` |
| 防火墙拦截 | 端口未开放 | 开放对应端口：`ufw allow 8000` |
| Cherry Studio 连不上远程服务 | URL 格式错误 | 确认格式：`http://IP:端口`（不带路径） |
| OpenWebUI Tool 报 404 | URL 缺少 `/mcp/` | mcp_url 必须以 `/mcp/` 结尾 |

### OpenWebUI 特有问题

| 问题 | 原因 | 解决方法 |
|------|------|----------|
| `E_URL_FORBIDDEN` | SSRF 白名单未配置 | 在 `.env` 中添加 `MCP_CONVERT_ALLOWED_URL_HOSTS=你的OpenWebUI地址` |
| 401 Unauthorized | 用户未登录或 token 失效 | 重新登录 OpenWebUI |

### Cherry Studio 特有问题

| 问题 | 原因 | 解决方法 |
|------|------|----------|
| mcp-file-system 无响应 | Docker 参数缺少 `-i` | args 中必须包含 `-i` 参数 |
| 读取文件报权限错误 | 目录未挂载或路径错误 | 检查 `-v` 挂载路径，容器内使用 `/data` 开头的路径 |
| Windows 路径问题 | 路径格式不对 | 使用 `D:/Work/Document` 或 `D:\\Work\\Document` |

---

## 六、环境变量

完整配置见 `.env.template`，以下是关键变量：

### MCP 服务端（mcp-convert-router）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_TRANSPORT` | stdio | 传输模式：`stdio` / `sse` / `streamable_http` |
| `MCP_HOST` | 0.0.0.0 | HTTP 监听地址 |
| `MCP_PORT` | 8000 | HTTP 监听端口 |
| `MINERU_API_KEY` | - | MinerU API 密钥（OCR 需要） |
| `MCP_CONVERT_ALLOWED_URL_HOSTS` | - | URL 白名单（逗号分隔） |
| `MCP_CONVERT_URL_TLS_VERIFY` | true | 是否验证 TLS 证书 |
| `MCP_CONVERT_MAX_FILE_MB` | 50 | 最大文件大小（MB） |

### OpenWebUI Tool Valves

| 参数 | 说明 |
|------|------|
| `mcp_url` | MCP 服务的 JSON-RPC 地址 |
| `openwebui_base_url` | OpenWebUI 基础 URL |
| `openwebui_api_key` | （可选）OpenWebUI API Key |
| `timeout_seconds` | 超时时间 |

---

## 七、详细文档

- [MCP Convert Router 详细说明](mcp_convert_router/README.md)
- [MCP File System 说明](mcp-file-system/README.md)
- [OpenWebUI Tool 脚本说明](open-webui-tools/README.md)
