# Pandoc MCP Server Docker 部署指南

## 快速开始

```bash
# 1. 上传代码到服务器
scp -r mcp-pandoc user@server:/path/to/

# 2. 启动服务（端口 20000）
cd /path/to/mcp-pandoc
MCP_PORT=20000 docker-compose up -d

# 3. 验证服务
curl -X POST http://localhost:20000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

---

## 常用命令

| 操作 | 命令 |
|------|------|
| 启动服务 | `MCP_PORT=20000 docker-compose up -d` |
| 停止服务 | `docker-compose down` |
| 查看日志 | `docker-compose logs -f` |
| 重启服务 | `docker-compose restart` |
| 查看状态 | `docker-compose ps` |
| 重新构建 | `docker-compose build --no-cache && docker-compose up -d` |

---

## 镜像版本选择

| 版本 | 命令 | 镜像大小 | PDF 支持 |
|------|------|----------|----------|
| 标准版 | `docker-compose up -d` | ~500MB | ❌ |
| PDF 版 | `docker-compose --profile pdf up -d` | ~2GB | ✅ |

---

## 配置说明

### 方法 1：命令行设置

```bash
MCP_PORT=20000 docker-compose up -d
```

### 方法 2：使用 .env 文件

```bash
cp .env.example .env
# 编辑 .env 文件设置 MCP_PORT=20000
docker-compose up -d
```

### 可用配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_PORT` | 20000 | 服务端口 |
| `PANDOC_LOG_LEVEL` | INFO | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `PANDOC_MCP_MAX_UPLOAD_BYTES` | 50MB | 单文件上传限制 |
| `PANDOC_MCP_MAX_UPLOAD_FILES` | 10 | 批量上传文件数量限制 |

---

## 故障排除

### 端口被占用

```bash
# 查找占用端口的进程
netstat -tlnp | grep 20000

# 使用其他端口
MCP_PORT=30000 docker-compose up -d
```

### 查看容器日志

```bash
docker-compose logs -f
```

### 进入容器调试

```bash
docker exec -it mcp-pandoc bash
pandoc --version
```

### 健康检查失败

```bash
# 手动测试
curl http://localhost:20000/mcp
```
