# Pandoc MCP Server 测试指南

## 目录
1. [环境准备](#1-环境准备)
2. [CLI 功能测试](#2-cli-功能测试)
3. [Stdio 模式测试](#3-stdio-模式测试)
4. [SSE 模式测试](#4-sse-模式测试)
5. [Streamable HTTP 模式测试](#5-streamable-http-模式测试)
6. [单元测试](#6-单元测试)

---

## 1. 环境准备

### 1.1 安装依赖
```bash
cd mcp-pandoc
uv sync
```

### 1.2 验证 Pandoc 安装
```bash
pandoc --version
```

### 1.3 验证 MCP 服务可用
```bash
uv run mcp-pandoc --version
```

---

## 2. CLI 功能测试

### 2.1 查看帮助信息
```bash
uv run mcp-pandoc --help
```
**预期输出**: 显示所有命令行选项和示例

### 2.2 查看当前配置
```bash
uv run mcp-pandoc --show-config
```
**预期输出**: 显示所有配置项，包括：
- Basic Settings（输出目录、临时目录、Pandoc路径）
- Security Settings（上传限制、路径控制）
- Logging（日志级别）
- Pandoc Status（版本信息）

### 2.3 Debug 模式
```bash
uv run mcp-pandoc --debug --show-config
```
**预期输出**: 日志级别显示为 DEBUG

---

## 3. Stdio 模式测试

### 3.1 启动 Stdio 服务器
```bash
# 方法1: 直接运行（会阻塞等待输入）
uv run mcp-pandoc

# 方法2: 使用 echo 测试
echo '{"jsonrpc":"2.0","method":"initialize","params":{"capabilities":{}},"id":1}' | uv run mcp-pandoc
```

---

## 4. SSE 模式测试

### 4.1 启动 SSE 服务器
```bash
# 终端 1: 启动服务器
uv run mcp-pandoc --transport sse --port 8001
```
**预期输出**:
```
Starting Pandoc MCP Server
  Transport: sse
  Address:   127.0.0.1:8001
  Output:    ./output

Press Ctrl+C to stop the server
```

### 4.2 测试 SSE 连接
```bash
# 终端 2: 测试连接
curl -N http://localhost:8001/sse
```
**预期输出**: SSE 事件流开始

---

## 5. Streamable HTTP 模式测试

### 5.1 启动 Streamable HTTP 服务器
```bash
# 终端 1: 启动服务器
uv run mcp-pandoc --transport streamable-http --port 8002
```
**预期输出**:
```
Starting Pandoc MCP Server
  Transport: streamable-http
  Address:   127.0.0.1:8002
...
INFO:     Started server process
INFO:     Uvicorn running on http://127.0.0.1:8002
```

### 5.2 测试 MCP 端点
```bash
# 终端 2: 发送初始化请求
curl -X POST http://localhost:8002/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

---

## 6. 单元测试

### 6.1 运行所有测试
```bash
uv run pytest tests/ -v
```

### 6.2 运行特定测试文件
```bash
# 高级功能测试
uv run pytest tests/test_advanced_features.py -v

# 转换测试
uv run pytest tests/test_conversions.py -v
```

### 6.3 运行带覆盖率的测试
```bash
uv run pytest tests/ -v --cov=mcp_pandoc --cov-report=html
```

---

## 快速验证清单

| 测试项 | 命令 | 预期结果 |
|--------|------|----------|
| CLI 帮助 | `uv run mcp-pandoc --help` | 显示帮助信息 |
| 配置显示 | `uv run mcp-pandoc --show-config` | 显示所有配置 |
| SSE 启动 | `uv run mcp-pandoc -t sse -p 8001` | 服务器启动 |
| HTTP 启动 | `uv run mcp-pandoc -t streamable-http -p 8002` | 服务器启动 |
| 单元测试 | `uv run pytest tests/ -v` | 测试通过 |
