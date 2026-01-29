# mcp_server

一组基于 MCP（Model Context Protocol）的服务与工具，核心用于“把各种文件转换为 Markdown”，并支持与 OpenWebUI 集成。

## 目录

- `mcp_convert_router/`：MCP Convert Router（主服务，提供 `convert_to_markdown` 工具）
- `open-webui-tools/`：OpenWebUI Tool 脚本（用于在 OpenWebUI 内更稳定地触发转换）
- `docs/openwebui/`：OpenWebUI 原生 MCP（streamable_http）集成说明

## 快速开始（本机）

1) 配置环境变量（示例见 `.env.template`）

2) 启动服务：

```bash
python -m mcp_convert_router.server
```

3) 集成 OpenWebUI：

- 原生 MCP（推荐）：见 `docs/openwebui/README.md`
- OpenWebUI Tool 脚本：见 `open-webui-tools/README.md`
