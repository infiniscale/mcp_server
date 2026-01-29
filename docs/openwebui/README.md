# OpenWebUI Native MCP Integration Guide

本文档说明如何通过 OpenWebUI 原生 MCP 支持集成 MCP Convert Router。

## 前提条件

- OpenWebUI v0.6.31+（支持原生 MCP）
- MCP Convert Router 支持 streamable_http transport

## 架构

```
OpenWebUI (原生 MCP Client)
    ↓ HTTP (streamable_http)
MCP Convert Router
    ↓ HTTP + Authorization header
OpenWebUI File API
```

## 配置步骤

### 1. 启动 MCP Server (streamable_http 模式)

```bash
export MCP_TRANSPORT=streamable_http
export MCP_PORT=25081
export MCP_HOST=0.0.0.0

# 允许 OpenWebUI 主机（必需）
export MCP_CONVERT_ALLOWED_URL_HOSTS="openwebui,192.168.1.100,localhost"

# 可选：自签名证书
export MCP_CONVERT_URL_TLS_VERIFY=false

python -m mcp_convert_router.server
```

### 2. 在 OpenWebUI 中配置 MCP Server

1. 进入 **Admin Settings → External Tools**
2. 点击 **+ Add Server**
3. 配置：
   - **Type**: `MCP (Streamable HTTP)`
   - **Server URL**: `http://mcp-convert-router:25081`
   - **Auth**: `None` (内网部署)
4. 保存

### 3. 使用工具

OpenWebUI 会自动发现以下工具：
- `convert_to_markdown` - 文件转换
- `health` - 健康检查
- `get_supported_formats` - 支持的格式

在对话中上传文件后，这些工具会自动可用。

## 文件下载认证

### 方式 1：手动传递认证头（推荐）

在调用 `convert_to_markdown` 时传递 `url_headers`:

```json
{
  "source": "http://openwebui/api/v1/files/abc123/content",
  "url_headers": {
    "Authorization": "Bearer sk-your-openwebui-api-key"
  }
}
```

### 方式 2：环境变量配置（简化）

配置默认的 OpenWebUI API Key：

```bash
export OPENWEBUI_API_KEY="sk-your-api-key"
```

MCP Server 可自动使用此 Key 下载文件。

## 故障排查

### E_URL_FORBIDDEN

**原因**: OpenWebUI 主机未在白名单
**解决**: 检查 `MCP_CONVERT_ALLOWED_URL_HOSTS`

### 连接超时

**原因**: 网络不通
**解决**:
- 检查防火墙
- 验证 DNS 解析
- Docker: 检查网络配置

### TLS 证书错误

**原因**: 自签名证书
**解决**: 设置 `MCP_CONVERT_URL_TLS_VERIFY=false`

## Docker Compose 示例

```yaml
version: '3.8'

services:
  mcp-convert-router:
    image: mcp-convert-router:latest
    ports:
      - "25081:25081"
    environment:
      - MCP_TRANSPORT=streamable_http
      - MCP_PORT=25081
      - MCP_CONVERT_ALLOWED_URL_HOSTS=openwebui
      - MINERU_API_KEY=${MINERU_API_KEY}
    networks:
      - app_network

  openwebui:
    image: ghcr.io/open-webui/open-webui:main
    ports:
      - "8080:8080"
    environment:
      - WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
    networks:
      - app_network

networks:
  app_network:
```

## 安全建议

1. **内网部署** - 使用 `auth_type: none`
2. **最小白名单** - 仅添加必需的主机
3. **生产环境** - 保持 TLS 验证启用
4. **监控日志** - 检查异常访问
