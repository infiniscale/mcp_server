# Pandoc MCP 服务增强开发指南

> 基于原作者项目（vivekVells/mcp-pandoc）的功能增强方案，参考 MinerU MCP 实践

**文档版本**: 2.0
**创建日期**: 2026-01-09
**原项目**: vivekVells/mcp-pandoc
**参考项目**: MinerU MCP Server (commit: 442f50f)

---

## 📋 目录

1. [项目背景与现状](#项目背景与现状)
2. [原项目分析](#原项目分析)
3. [核心问题：远程MCP服务如何访问用户本地文件](#核心问题远程mcp服务如何访问用户本地文件)
4. [MinerU MCP 参考实现](#mineru-mcp-参考实现)
5. [功能增强规划](#功能增强规划)
6. [关键技术方案](#关键技术方案)
7. [安全性与稳定性设计](#安全性与稳定性设计)
8. [参数化配置设计](#参数化配置设计)
9. [实施路线图](#实施路线图)
10. [代码示例](#代码示例)
11. [部署场景](#部署场景)

---

## 项目背景与现状

### 当前目标
基于 **vivekVells/mcp-pandoc** 原项目，增强以下功能：
- ✅ **保持现有功能**：stdio 模式 + 本地文件转换
- 🆕 **新增 HTTP 模式**：支持 sse 和 streamable-http 协议
- 🆕 **新增 base64 上传**：解决远程场景下的文件访问问题
- 🆕 **安全增强**：文件大小限制、路径验证、参数化配置
- 🆕 **多部署场景**：开发环境、内网服务、公网服务

### 参考项目
- **原作者项目**: https://github.com/vivekVells/mcp-pandoc（基础版）
- **参考实现**: MinerU MCP Server（增强功能参考）
- **上游技术**: https://github.com/opendatalab/MinerU

---

## 原项目分析

### 项目结构（当前状态）

```
mcp-pandoc/
├── src/mcp_pandoc/
│   ├── __init__.py
│   ├── server.py           # FastMCP 服务器（当前仅 stdio）
│   └── ...
├── pyproject.toml
└── README.md
```

### 现有功能

**单一工具**：`convert-contents`

```python
convert-contents(
    contents: str,              # 直接内容
    input_file: str,            # 输入文件路径
    input_format: str = "markdown",
    output_format: str = "markdown",
    output_file: str,           # 输出文件路径
    reference_doc: str,         # 参考文档
    defaults_file: str,         # 默认配置
    filters: array              # 过滤器
)
```

**支持格式**：
- Markdown, HTML, TXT, DOCX, PDF
- RST, LaTeX, EPUB, IPYNB, ODT

**当前限制**：
- ❌ 仅支持 stdio 模式（本地运行）
- ❌ 无法作为远程 HTTP 服务使用
- ❌ 远程场景下无法访问用户本地文件
- ❌ 缺少安全验证机制

### 现有配置方式（Claude Desktop）

```json
{
  "mcpServers": {
    "mcp-pandoc": {
      "command": "uvx",
      "args": ["mcp-pandoc"]
    }
  }
}
```

---

## 核心问题：远程MCP服务如何访问用户本地文件

### 问题描述

当 MCP 服务以 HTTP 模式对外提供服务时，会遇到一个根本性问题：

```
┌─────────────────┐                    ┌──────────────────┐
│   用户客户端    │                    │   远程MCP服务器  │
│                 │                    │                  │
│ /Users/alice/   │  HTTP Request      │  试图读取：      │
│   doc.pdf       │ ───────────────>   │  /Users/alice/   │
│                 │                    │   doc.pdf        │
└─────────────────┘                    │                  │
                                       │  ❌ 文件不存在！  │
                                       └──────────────────┘
```

**问题根源**：服务器的文件系统无法访问客户端的文件系统。

### 解决方案对比

| 方案 | 工作方式 | 适用场景 | 优点 | 缺点 |
|------|---------|---------|------|------|
| **stdio 模式** | 服务器作为子进程运行在用户本地 | 本地开发、桌面应用 | 直接访问文件系统 | 无法远程部署 |
| **base64 上传** | 客户端读取文件并编码上传 | 远程HTTP服务 | 可远程部署 | 增加传输大小 |
| **文件上传API** | 传统multipart/form-data | Web应用 | 标准HTTP方式 | 需要专门的上传接口 |

### MinerU 的解决方案

MinerU MCP 采用了**双模式支持**：

1. **本地模式（stdio）** - 直接读取文件路径
2. **远程模式（HTTP）** - 通过 base64 上传文件内容

---

## MinerU MCP 参考实现

### 项目结构

```
mineru-mcp/Mineru/projects/mcp/
├── src/mineru/
│   ├── server.py           # FastMCP 服务器实现（1061行）
│   ├── api.py              # MinerU API 客户端（729行）
│   ├── cli.py              # 命令行入口（74行）
│   ├── config.py           # 配置管理（127行）
│   ├── language.py         # 语言支持（106行）
│   └── examples.py         # 示例代码（76行）
├── .env.example            # 环境变量模板
├── .gitignore
├── Dockerfile              # Docker 部署
├── docker-compose.yml
├── pyproject.toml          # 项目配置
└── README.md               # 文档（346行）
```

### 核心依赖

```toml
dependencies = [
    "fastmcp>=2.5.2",        # MCP 框架
    "python-dotenv>=1.0.0",  # 环境变量
    "requests>=2.31.0",      # HTTP 客户端
    "aiohttp>=3.9.0",        # 异步 HTTP
    "httpx>=0.24.0",         # 现代 HTTP 客户端
    "uvicorn>=0.20.0",       # ASGI 服务器
    "starlette>=0.27.0",     # Web 框架
]
```

### MCP 工具接口

```python
@mcp.tool()
async def parse_documents(
    file_sources: str,           # 文件路径或URL
    enable_ocr: bool = False,    # OCR开关
    language: str = "ch",        # 语言
    page_ranges: str = None      # 页码范围
) -> Dict[str, Any]:
    """统一接口：处理本地文件和URL"""

@mcp.tool()
async def parse_documents_base64(
    files: List[Dict[str, Any]],  # [{filename, content_base64}, ...]
    enable_ocr: bool = False,
    language: str = "ch",
    keep_uploaded_files: bool = False
) -> Dict[str, Any]:
    """Base64上传接口：远程场景专用"""

@mcp.tool()
async def get_ocr_languages() -> Dict[str, Any]:
    """获取支持的语言列表"""
```

---

## 功能增强规划

### 对比分析：原项目 vs 增强版

| 功能模块 | 原项目状态 | 增强目标 | 优先级 |
|---------|----------|---------|-------|
| **通信协议** | stdio only | stdio + sse + streamable-http | ⭐⭐⭐ |
| **工具接口** | convert-contents | convert-contents + convert-contents-base64 | ⭐⭐⭐ |
| **文件访问** | 本地路径直接访问 | 本地路径 + base64上传 | ⭐⭐⭐ |
| **安全验证** | 无 | 文件大小限制 + 路径白名单 + 文件名清理 | ⭐⭐ |
| **配置管理** | 命令行参数 | 环境变量 + CLI参数 + .env文件 | ⭐⭐ |
| **部署支持** | 本地运行 | 本地 + 内网 + 公网 | ⭐ |

### 核心增强点

#### 1. 新增工具：convert-contents-base64

**目的**：解决远程 HTTP 场景下的文件访问问题

**接口设计**：
```python
@mcp.tool()
async def convert_contents_base64(
    files: Annotated[
        List[Dict[str, Any]],
        Field(description='[{"filename": "doc.md", "content_base64": "..."}]')
    ],
    output_format: Annotated[str, Field(description="目标格式")],
    input_format: Annotated[str | None, Field(description="源格式")] = None,
    keep_uploaded_files: Annotated[bool, Field(description="保留临时文件")] = False,
) -> Dict[str, Any]:
    """
    通过 base64 上传文件内容并转换（适用于远程 HTTP 服务）。
    """
```

**与现有工具的关系**：
- `convert-contents`：保持不变，继续服务 stdio 模式
- `convert-contents-base64`：新增工具，服务 HTTP 模式

#### 2. HTTP 模式支持

**修改位置**：`src/mcp_pandoc/server.py` 和新增 `src/mcp_pandoc/cli.py`

**增加的功能**：
- SSE 传输支持
- Streamable HTTP 传输支持
- 端口和主机配置

**CLI 增强**：
```bash
# stdio 模式（原有）
mcp-pandoc

# HTTP 模式（新增）
mcp-pandoc --transport sse --host 0.0.0.0 --port 8001
mcp-pandoc --transport streamable-http --host 127.0.0.1 --port 8001
```

#### 3. 配置管理增强

**新增文件**：`src/mcp_pandoc/config.py`

**配置内容**：
- 输出目录配置
- 临时文件目录配置
- 文件大小限制
- 路径白名单
- 日志级别配置

#### 4. 安全验证机制

**新增函数**（在 `server.py` 中）：
- `_decode_base64_payload()`: base64 解码和验证
- `_sanitize_filename()`: 文件名清理，防止路径穿越
- `_validate_file_size()`: 文件大小验证
- `_validate_local_path()`: 路径白名单验证（可选）

### 保持兼容性

**重要原则**：所有增强都是**增量式**的，不破坏现有功能

- ✅ 现有 `convert-contents` 工具保持不变
- ✅ stdio 模式继续作为默认模式
- ✅ 现有 Claude Desktop 配置继续有效
- ✅ 命令 `uvx mcp-pandoc` 继续有效（等同于 `mcp-pandoc --transport stdio`）

---

## 关键技术方案

### 方案1：本地路径访问（stdio模式）

#### 工作流程

```python
# 1. 用户调用 MCP 工具
parse_documents(file_sources="/Users/alice/document.pdf")

# 2. 服务器读取本地文件
file_path = Path("/Users/alice/document.pdf")
if not file_path.exists():
    raise FileNotFoundError(f"文件不存在: {file_path}")

# 3. 读取文件为二进制
with open(file_path, "rb") as f:
    file_data = f.read()

# 4. 处理文件
result = process_document(file_data)
```

#### 适用场景

- ✅ Claude Desktop 本地配置
- ✅ 开发环境调试
- ✅ 个人用户使用

#### 配置示例

```json
{
  "mcpServers": {
    "pandoc-mcp": {
      "command": "uv",
      "args": ["run", "-m", "pandoc.cli"],
      "env": {
        "OUTPUT_DIR": "./output"
      }
    }
  }
}
```

---

### 方案2：Base64 上传（HTTP模式）⭐

#### 核心实现

```python
@mcp.tool()
async def convert_documents_base64(
    files: List[Dict[str, Any]],
    output_format: str = "markdown",
    keep_uploaded_files: bool = False,
) -> Dict[str, Any]:
    """
    通过 base64 上传文件内容并转换。

    Args:
        files: [{"filename": "doc.pdf", "content_base64": "JVBERi0x..."}]
        output_format: 目标格式（markdown/docx/pdf/html）
        keep_uploaded_files: 是否保留服务端临时文件

    Returns:
        {"status": "success", "results": [...]}
    """
    if not files:
        return {"status": "error", "error": "files 不能为空"}

    # 创建临时上传目录
    upload_dir = Path(output_dir) / "_uploads" / secrets.token_hex(12)
    upload_dir.mkdir(parents=True, exist_ok=True)

    results = []
    saved_files = []

    try:
        # 处理每个上传的文件
        for item in files:
            # 1. 验证和清理文件名
            filename = _sanitize_filename(item.get("filename", ""))

            # 2. 解码 base64
            content_b64 = item.get("content_base64")
            file_bytes = _decode_base64_payload(content_b64)

            # 3. 检查文件大小
            if len(file_bytes) > MAX_UPLOAD_BYTES:
                raise ValueError(f"文件过大: {len(file_bytes)} bytes")

            # 4. 保存到临时文件
            temp_path = upload_dir / filename
            temp_path.write_bytes(file_bytes)
            saved_files.append(str(temp_path))

            # 5. 调用 pandoc 处理
            result = await _convert_file(temp_path, output_format)
            results.append(result)

    finally:
        # 清理临时文件（如果不保留）
        if not keep_uploaded_files and upload_dir.exists():
            shutil.rmtree(upload_dir)

    return _build_results_response(results)
```

#### 关键辅助函数

```python
def _decode_base64_payload(base64_payload: str) -> bytes:
    """解码 base64（支持 data URL 前缀）"""
    if not base64_payload:
        raise ValueError("content_base64 为空")

    payload = base64_payload.strip()

    # 移除 data URL 前缀（如 data:application/pdf;base64,）
    if payload.startswith("data:") and "base64," in payload:
        payload = payload.split("base64,", 1)[1]

    # 移除所有空白字符
    payload = re.sub(r"\s+", "", payload)

    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"base64 解码失败: {str(e)}") from e


def _sanitize_filename(filename: str) -> str:
    """清理文件名，防止路径穿越攻击"""
    # 只取文件名部分，去除路径
    name = Path(filename or "").name
    if not name:
        return "upload.bin"

    # 替换危险字符
    name = re.sub(r"[\s,]+", "_", name).strip("_")
    return name or "upload.bin"


def _estimate_base64_decoded_size(base64_payload: str) -> int:
    """估算 base64 解码后的大小（不实际解码）"""
    if not base64_payload:
        return 0

    payload = base64_payload.strip()
    if payload.startswith("data:") and "base64," in payload:
        payload = payload.split("base64,", 1)[1]

    payload = re.sub(r"\s+", "", payload)
    padding = payload.count("=")

    return max(0, (len(payload) * 3) // 4 - padding)
```

#### 客户端示例

```javascript
// 客户端读取文件并上传
async function convertDocument(filePath) {
  // 1. 读取文件
  const fileBuffer = await fs.readFile(filePath);

  // 2. 转为 base64
  const base64Content = fileBuffer.toString('base64');

  // 3. 调用 MCP 工具
  const result = await mcpClient.callTool('convert_documents_base64', {
    files: [{
      filename: path.basename(filePath),
      content_base64: base64Content
    }],
    output_format: 'markdown'
  });

  return result;
}
```

---

## 安全性与稳定性设计

### 1. 文件大小限制

```python
# config.py
MAX_UPLOAD_BYTES = int(os.getenv("PANDOC_MCP_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MAX_FILE_BYTES = int(os.getenv("PANDOC_MCP_MAX_FILE_BYTES", str(50 * 1024 * 1024)))

# 使用
def _validate_file_size(file_bytes: bytes) -> None:
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"文件过大: {len(file_bytes)} bytes，"
            f"超过限制 {MAX_UPLOAD_BYTES} bytes"
        )
```

### 2. 路径安全控制

```python
# config.py
MCP_DISABLE_PATH_INPUT = os.getenv("PANDOC_MCP_DISABLE_PATH_INPUT", "").lower() in ["true", "1", "yes"]
MCP_REQUIRE_PATH_ALLOWLIST = os.getenv("PANDOC_MCP_REQUIRE_ALLOWLIST", "").lower() in ["true", "1", "yes"]
MCP_ALLOWED_INPUT_ROOTS = _parse_allowed_roots(os.getenv("PANDOC_MCP_ALLOWED_INPUT_ROOTS", ""))

# 验证函数
def _validate_local_path(path: Path) -> Optional[str]:
    """验证本地路径是否允许访问"""

    # 检查是否禁用路径输入
    if MCP_DISABLE_PATH_INPUT:
        return "当前服务已禁用本地路径输入"

    # 检查是否需要白名单
    if MCP_REQUIRE_PATH_ALLOWLIST and not MCP_ALLOWED_INPUT_ROOTS:
        return "当前服务要求设置允许目录"

    # 检查路径是否在白名单内
    if not _is_path_allowed(path):
        return "文件路径不在允许目录内"

    # 检查文件大小
    if MAX_FILE_BYTES > 0:
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                return f"文件过大: {size} bytes，超过限制 {MAX_FILE_BYTES} bytes"
        except Exception as e:
            return f"无法读取文件大小: {str(e)}"

    return None  # 验证通过


def _is_path_allowed(path: Path) -> bool:
    """检查路径是否在允许列表中"""
    if not MCP_ALLOWED_INPUT_ROOTS:
        return not MCP_REQUIRE_PATH_ALLOWLIST

    try:
        resolved_path = path.resolve()
    except Exception:
        return False

    for root in MCP_ALLOWED_INPUT_ROOTS:
        try:
            resolved_root = root.expanduser().resolve()
            if resolved_path.is_relative_to(resolved_root):
                return True
        except Exception:
            continue

    return False
```

### 3. 文件名清理

```python
def _sanitize_filename(filename: str) -> str:
    """清理上传文件名，防止路径穿越"""
    # 只保留文件名部分
    name = Path(filename or "").name
    if not name:
        return "upload.bin"

    # 移除危险字符：空格、逗号、特殊符号
    name = re.sub(r"[\s,;|&$<>()]+", "_", name)
    name = name.strip("_.")

    # 防止隐藏文件
    if name.startswith("."):
        name = "file_" + name

    return name or "upload.bin"
```

### 4. 临时文件管理

```python
import secrets
import shutil

async def convert_documents_base64(...):
    # 创建唯一的临时目录
    upload_dir = Path(output_dir) / "_uploads" / secrets.token_hex(12)
    upload_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 处理文件
        results = await _process_files(upload_dir, files)
        return results
    finally:
        # 清理临时文件
        if not keep_uploaded_files and upload_dir.exists():
            try:
                shutil.rmtree(upload_dir)
            except Exception as e:
                logger.error(f"清理临时文件失败: {str(e)}")
```

### 5. 统一的错误处理

```python
def _build_results_response(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """统一的结果打包格式"""
    if not results:
        return {"status": "error", "error": "未处理任何文件"}

    success_count = len([r for r in results if r.get("status") == "success"])
    error_count = len([r for r in results if r.get("status") == "error"])
    total_count = len(results)

    # 单文件情况：保持向后兼容
    if total_count == 1:
        result = results[0].copy()
        result.pop("filename", None)
        return result

    # 多文件情况
    overall_status = "success"
    if success_count == 0:
        overall_status = "error"
    elif error_count > 0:
        overall_status = "partial_success"

    return {
        "status": overall_status,
        "results": results,
        "summary": {
            "total_files": total_count,
            "success_count": success_count,
            "error_count": error_count,
        },
    }
```

---

## 参数化配置设计

### 设计原则

> **一切皆可配置，零代码调整**

### 配置层级

```
命令行参数（优先级最高）
    ↓
环境变量
    ↓
.env 文件
    ↓
代码默认值（优先级最低）
```

### 1. 通信协议配置

```python
# cli.py
def main():
    parser = argparse.ArgumentParser(description="Pandoc MCP 文档转换服务")

    parser.add_argument(
        "--transport", "-t",
        type=str,
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="通信协议类型"
    )

    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8001,
        help="HTTP 服务端口"
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="HTTP 服务地址"
    )

    args = parser.parse_args()
    run_server(mode=args.transport, port=args.port, host=args.host)


# server.py
def run_server(mode=None, port=8001, host="127.0.0.1"):
    mcp_server = mcp._mcp_server

    if mode == "sse":
        # SSE 模式
        starlette_app = create_starlette_app(mcp_server)
        uvicorn.run(starlette_app, host=host, port=port)
    elif mode == "streamable-http":
        # Streamable HTTP 模式
        mcp.run(mode, port=port, host=host)
    else:
        # STDIO 模式（默认）
        mcp.run(mode or "stdio")
```

### 2. 环境变量配置

```python
# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# === 基础配置 ===
OUTPUT_DIR = os.getenv("PANDOC_OUTPUT_DIR", "./output")
TEMP_DIR = os.getenv("PANDOC_TEMP_DIR", "./temp")

# === 安全配置 ===
# 文件大小限制
MAX_UPLOAD_BYTES = int(os.getenv("PANDOC_MCP_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MAX_FILE_BYTES = int(os.getenv("PANDOC_MCP_MAX_FILE_BYTES", str(50 * 1024 * 1024)))

# 路径访问控制
MCP_DISABLE_PATH_INPUT = os.getenv("PANDOC_MCP_DISABLE_PATH_INPUT", "").lower() in ["true", "1", "yes"]
MCP_REQUIRE_PATH_ALLOWLIST = os.getenv("PANDOC_MCP_REQUIRE_ALLOWLIST", "").lower() in ["true", "1", "yes"]

def _parse_allowed_roots(value: str) -> list[Path]:
    if not value:
        return []
    roots = []
    for chunk in value.split(os.pathsep):
        for item in chunk.split(","):
            item = item.strip()
            if item:
                roots.append(Path(item).expanduser())
    return roots

MCP_ALLOWED_INPUT_ROOTS = _parse_allowed_roots(
    os.getenv("PANDOC_MCP_ALLOWED_INPUT_ROOTS", "")
)

# === 日志配置 ===
LOG_LEVEL = os.getenv("PANDOC_LOG_LEVEL", "INFO").upper()
DEBUG_MODE = os.getenv("PANDOC_DEBUG", "").lower() in ["true", "1", "yes"]

# === Pandoc 配置 ===
PANDOC_PATH = os.getenv("PANDOC_PATH", "pandoc")  # pandoc 可执行文件路径
PANDOC_DATA_DIR = os.getenv("PANDOC_DATA_DIR", "")  # pandoc 数据目录
```

### 3. .env 配置文件模板

```bash
# .env.example

# === 基础配置 ===
PANDOC_OUTPUT_DIR=./output
PANDOC_TEMP_DIR=./temp

# === 安全配置 ===
# 上传文件大小限制（字节），50MB = 52428800
PANDOC_MCP_MAX_UPLOAD_BYTES=52428800

# 本地文件大小限制（字节），100MB = 104857600
PANDOC_MCP_MAX_FILE_BYTES=104857600

# 是否禁用本地路径输入（true/false）
PANDOC_MCP_DISABLE_PATH_INPUT=false

# 是否要求路径白名单（true/false）
PANDOC_MCP_REQUIRE_ALLOWLIST=false

# 允许访问的根目录列表（用冒号或逗号分隔）
# Linux/Mac: /home/user/documents:/data/shared
# Windows: C:\Users\user\Documents,D:\Data
PANDOC_MCP_ALLOWED_INPUT_ROOTS=

# === 日志配置 ===
PANDOC_LOG_LEVEL=INFO
PANDOC_DEBUG=false

# === Pandoc 配置 ===
# pandoc 可执行文件路径（默认从 PATH 查找）
PANDOC_PATH=pandoc

# pandoc 数据目录（可选）
PANDOC_DATA_DIR=
```

### 4. 场景化配置示例

#### 开发环境

```bash
# .env.development
PANDOC_OUTPUT_DIR=./dev_output
PANDOC_LOG_LEVEL=DEBUG
PANDOC_DEBUG=true
PANDOC_MCP_DISABLE_PATH_INPUT=false
PANDOC_MCP_MAX_FILE_BYTES=0  # 无限制

# 启动
pandoc-mcp --transport stdio
```

#### 内网测试环境

```bash
# .env.staging
PANDOC_OUTPUT_DIR=/data/output
PANDOC_LOG_LEVEL=INFO
PANDOC_MCP_REQUIRE_ALLOWLIST=true
PANDOC_MCP_ALLOWED_INPUT_ROOTS=/home/users:/data/shared
PANDOC_MCP_MAX_FILE_BYTES=104857600  # 100MB

# 启动
pandoc-mcp --transport streamable-http --host 0.0.0.0 --port 8001
```

#### 生产环境（公网）

```bash
# .env.production
PANDOC_OUTPUT_DIR=/var/pandoc/output
PANDOC_TEMP_DIR=/var/pandoc/temp
PANDOC_LOG_LEVEL=WARNING
PANDOC_MCP_DISABLE_PATH_INPUT=true  # 禁用本地路径
PANDOC_MCP_MAX_UPLOAD_BYTES=52428800  # 50MB
PANDOC_MCP_MAX_FILE_BYTES=0  # 不使用（已禁用路径）

# 启动（配合反向代理 + HTTPS）
pandoc-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

---

## 实施路线图

### Phase 1: 环境准备与代码拉取

#### Step 1.1: 克隆原项目并创建功能分支

```bash
# 已完成：设置 upstream 远程仓库
git remote add upstream https://github.com/vivekVells/mcp-pandoc.git
git fetch upstream

# 在 feature/pandoc-mcp 分支上工作
git checkout feature/pandoc-mcp

# （可选）拉取原项目最新代码作为参考
git fetch upstream main
```

#### Step 1.2: 分析原项目代码结构

**重点文件**：
- `src/mcp_pandoc/server.py`：现有 FastMCP 服务器实现
- `pyproject.toml`：依赖配置
- 理解 `convert-contents` 工具的实现逻辑

### Phase 2: 配置管理增强（优先级：⭐⭐⭐）

#### Step 2.1: 创建配置模块

**新增文件**：`src/mcp_pandoc/config.py`

参考 MinerU 的配置设计：

```python
"""Pandoc MCP 配置管理"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 输出目录配置
DEFAULT_OUTPUT_DIR = os.getenv("PANDOC_OUTPUT_DIR", "./output")
TEMP_DIR = os.getenv("PANDOC_TEMP_DIR", "./temp")

# 安全配置 - 文件大小限制
MAX_UPLOAD_BYTES = int(os.getenv("PANDOC_MCP_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MAX_FILE_BYTES = int(os.getenv("PANDOC_MCP_MAX_FILE_BYTES", str(50 * 1024 * 1024)))

# 安全配置 - 路径控制
MCP_DISABLE_PATH_INPUT = os.getenv("PANDOC_MCP_DISABLE_PATH_INPUT", "").lower() in ["true", "1", "yes"]
MCP_REQUIRE_PATH_ALLOWLIST = os.getenv("PANDOC_MCP_REQUIRE_ALLOWLIST", "").lower() in ["true", "1", "yes"]

def _parse_allowed_roots(value: str) -> list[Path]:
    if not value:
        return []
    roots: list[Path] = []
    for chunk in value.split(os.pathsep):
        for item in chunk.split(","):
            item = item.strip()
            if item:
                roots.append(Path(item).expanduser())
    return roots

MCP_ALLOWED_INPUT_ROOTS = _parse_allowed_roots(os.getenv("PANDOC_MCP_ALLOWED_INPUT_ROOTS", ""))

# 日志配置
def setup_logging():
    log_level = os.getenv("PANDOC_LOG_LEVEL", "INFO").upper()
    debug_mode = os.getenv("PANDOC_DEBUG", "").lower() in ["true", "1", "yes"]

    if debug_mode:
        log_level = "DEBUG"

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger = logging.getLogger("pandoc")
    return logger

logger = setup_logging()

def ensure_output_dir(output_dir=None):
    """确保输出目录存在"""
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path
```

#### Step 2.2: 创建 .env.example 模板

**新增文件**：`.env.example`

```bash
# 基础配置
PANDOC_OUTPUT_DIR=./output
PANDOC_TEMP_DIR=./temp

# 安全配置 - 文件大小限制
PANDOC_MCP_MAX_UPLOAD_BYTES=52428800  # 50MB
PANDOC_MCP_MAX_FILE_BYTES=104857600   # 100MB

# 安全配置 - 路径控制
PANDOC_MCP_DISABLE_PATH_INPUT=false
PANDOC_MCP_REQUIRE_ALLOWLIST=false
PANDOC_MCP_ALLOWED_INPUT_ROOTS=

# 日志配置
PANDOC_LOG_LEVEL=INFO
PANDOC_DEBUG=false

# Pandoc 配置
PANDOC_PATH=pandoc
PANDOC_DATA_DIR=
```

### Phase 3: 安全函数实现（优先级：⭐⭐⭐）

#### Step 3.1: 在 server.py 中添加安全工具函数

**修改文件**：`src/mcp_pandoc/server.py`

在文件顶部添加导入和工具函数：

```python
import base64
import binascii
import re
import secrets
import shutil
from pathlib import Path

from . import config

# === 安全工具函数 ===

def _decode_base64_payload(base64_payload: str) -> bytes:
    """解码 base64（支持 data URL 前缀）"""
    if not base64_payload:
        raise ValueError("content_base64 为空")

    payload = base64_payload.strip()

    # 移除 data URL 前缀（如 data:application/pdf;base64,）
    if payload.startswith("data:") and "base64," in payload:
        payload = payload.split("base64,", 1)[1]

    # 移除所有空白字符
    payload = re.sub(r"\s+", "", payload)

    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"base64 解码失败: {str(e)}") from e


def _sanitize_filename(filename: str) -> str:
    """清理文件名，防止路径穿越攻击"""
    # 只取文件名部分，去除路径
    name = Path(filename or "").name
    if not name:
        return "upload.bin"

    # 替换危险字符
    name = re.sub(r"[\s,]+", "_", name).strip("_")
    return name or "upload.bin"


def _estimate_base64_decoded_size(base64_payload: str) -> int:
    """估算 base64 解码后的大小（不实际解码）"""
    if not base64_payload:
        return 0

    payload = base64_payload.strip()
    if payload.startswith("data:") and "base64," in payload:
        payload = payload.split("base64,", 1)[1]

    payload = re.sub(r"\s+", "", payload)
    padding = payload.count("=")

    return max(0, (len(payload) * 3) // 4 - padding)


def _validate_local_path(path: Path) -> Optional[str]:
    """验证本地路径是否允许访问"""
    # 检查是否禁用路径输入
    if config.MCP_DISABLE_PATH_INPUT:
        return "当前服务已禁用本地路径输入"

    # 检查是否需要白名单
    if config.MCP_REQUIRE_PATH_ALLOWLIST and not config.MCP_ALLOWED_INPUT_ROOTS:
        return "当前服务要求设置允许目录"

    # 检查路径是否在白名单内
    if config.MCP_REQUIRE_PATH_ALLOWLIST:
        if not _is_path_allowed(path):
            return "文件路径不在允许目录内"

    # 检查文件大小
    if config.MAX_FILE_BYTES > 0:
        try:
            size = path.stat().st_size
            if size > config.MAX_FILE_BYTES:
                return f"文件过大: {size} bytes，超过限制 {config.MAX_FILE_BYTES} bytes"
        except Exception as e:
            return f"无法读取文件大小: {str(e)}"

    return None  # 验证通过


def _is_path_allowed(path: Path) -> bool:
    """检查路径是否在允许列表中"""
    if not config.MCP_ALLOWED_INPUT_ROOTS:
        return True

    try:
        resolved_path = path.resolve()
    except Exception:
        return False

    for root in config.MCP_ALLOWED_INPUT_ROOTS:
        try:
            resolved_root = root.expanduser().resolve()
            if resolved_path.is_relative_to(resolved_root):
                return True
        except Exception:
            continue

    return False
```

### Phase 4: 新增 base64 上传工具（优先级：⭐⭐⭐）

#### Step 4.1: 实现 convert-contents-base64 工具

**修改文件**：`src/mcp_pandoc/server.py`

在现有的 `convert-contents` 工具之后添加：

```python
@mcp.tool()
async def convert_contents_base64(
    files: Annotated[
        List[Dict[str, Any]],
        Field(
            description=(
                "通过 base64 上传文件内容并转换（适用于远端 MCP Server 场景）。\n"
                "格式：[{\"filename\": \"doc.md\", \"content_base64\": \"...\"}, ...]\n"
                "content_base64 支持 data URL 前缀（data:...;base64,xxxx）。"
            )
        ),
    ],
    output_format: Annotated[str, Field(description="目标格式（markdown/docx/pdf等）")],
    input_format: Annotated[str | None, Field(description="源格式（可选，自动检测）")] = None,
    keep_uploaded_files: Annotated[
        bool,
        Field(description="是否保留服务端落盘的上传文件（默认False）")
    ] = False,
) -> Dict[str, Any]:
    """
    通过 base64 上传文件内容并转换（适用于远程 HTTP 服务）。

    示例：
    files = [
        {
            "filename": "document.md",
            "content_base64": "IyBIZWxsbyBXb3JsZA=="
        }
    ]
    """
    if not files:
        return {"status": "error", "error": "files 不能为空"}

    # 创建临时上传目录
    upload_dir = config.ensure_output_dir(config.TEMP_DIR) / "_uploads" / secrets.token_hex(12)
    upload_dir.mkdir(parents=True, exist_ok=True)

    results = []
    saved_files = []

    try:
        # 处理每个上传的文件
        for item in files:
            if not isinstance(item, dict):
                results.append({
                    "status": "error",
                    "error_message": "每个文件必须是对象"
                })
                continue

            # 1. 验证和清理文件名
            filename = _sanitize_filename(item.get("filename", ""))
            content_b64 = item.get("content_base64")

            if not isinstance(content_b64, str):
                results.append({
                    "filename": filename,
                    "status": "error",
                    "error_message": "缺少 content_base64"
                })
                continue

            try:
                # 2. 估算文件大小
                estimated_size = _estimate_base64_decoded_size(content_b64)
                if estimated_size > config.MAX_UPLOAD_BYTES:
                    raise ValueError(
                        f"文件过大: 估算 {estimated_size} bytes，"
                        f"超过限制 {config.MAX_UPLOAD_BYTES} bytes"
                    )

                # 3. 解码 base64
                file_bytes = _decode_base64_payload(content_b64)

                # 4. 再次检查实际大小
                if len(file_bytes) > config.MAX_UPLOAD_BYTES:
                    raise ValueError(
                        f"文件过大: {len(file_bytes)} bytes，"
                        f"超过限制 {config.MAX_UPLOAD_BYTES} bytes"
                    )

                # 5. 保存到临时文件
                temp_path = upload_dir / filename
                temp_path.write_bytes(file_bytes)
                saved_files.append(str(temp_path))

                # 6. 调用现有的转换逻辑（需要适配 Pandoc）
                result = await _convert_file(temp_path, output_format, input_format)
                results.append(result)

            except Exception as e:
                results.append({
                    "filename": filename,
                    "status": "error",
                    "error_message": str(e)
                })

    finally:
        # 清理临时文件（如果不保留）
        if not keep_uploaded_files and upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

    return _build_results_response(results)


def _build_results_response(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """统一的结果打包格式"""
    if not results:
        return {"status": "error", "error": "未处理任何文件"}

    success_count = len([r for r in results if r.get("status") == "success"])
    error_count = len([r for r in results if r.get("status") == "error"])
    total_count = len(results)

    # 单文件情况：保持向后兼容
    if total_count == 1:
        result = results[0].copy()
        result.pop("filename", None)
        return result

    # 多文件情况
    overall_status = "success"
    if success_count == 0:
        overall_status = "error"
    elif error_count > 0:
        overall_status = "partial_success"

    return {
        "status": overall_status,
        "results": results,
        "summary": {
            "total_files": total_count,
            "success_count": success_count,
            "error_count": error_count,
        },
    }


async def _convert_file(
    input_path: Path,
    output_format: str,
    input_format: Optional[str] = None,
) -> Dict[str, Any]:
    """
    转换文件（需要根据原项目的 Pandoc 集成逻辑进行适配）

    这里是示例框架，具体实现需要参考原项目的 convert-contents 工具
    """
    try:
        # TODO: 调用原项目的 Pandoc 转换逻辑
        # 这里需要根据原项目的实现进行适配

        return {
            "filename": input_path.name,
            "status": "success",
            "output_content": "转换后的内容",  # 或者返回输出文件路径
        }
    except Exception as e:
        return {
            "filename": input_path.name,
            "status": "error",
            "error_message": str(e)
        }
```

### Phase 5: CLI 和 HTTP 模式支持（优先级：⭐⭐）

#### Step 5.1: 创建 CLI 模块

**新增文件**：`src/mcp_pandoc/cli.py`

```python
"""Pandoc MCP 命令行界面"""
import sys
import argparse

from . import config
from . import server


def main():
    """命令行入口点"""
    parser = argparse.ArgumentParser(description="Pandoc 文档转换服务")

    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        help="保存转换后文件的目录 (默认: ./output)"
    )

    parser.add_argument(
        "--transport", "-t",
        type=str,
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="通信协议类型 (默认: stdio)"
    )

    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8001,
        help="服务器端口 (默认: 8001, 仅在HTTP协议时有效)"
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="服务器主机地址 (默认: 127.0.0.1, 仅在HTTP协议时有效)"
    )

    args = parser.parse_args()

    # 如果提供了输出目录，则进行设置
    if args.output_dir:
        server.set_output_dir(args.output_dir)

    # 打印配置信息
    print("Pandoc MCP 服务启动...")
    if args.transport in ["sse", "streamable-http"]:
        print(f"服务器地址: {args.host}:{args.port}")
    print("按 Ctrl+C 可以退出服务")

    server.run_server(mode=args.transport, port=args.port, host=args.host)


if __name__ == "__main__":
    main()
```

#### Step 5.2: 修改 server.py 以支持多协议

**修改文件**：`src/mcp_pandoc/server.py`

添加服务器启动函数：

```python
import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route


def create_starlette_app(mcp_server, *, debug: bool = False) -> Starlette:
    """创建用于SSE传输的Starlette应用"""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        """处理SSE连接请求"""
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


def run_server(mode=None, port=8001, host="127.0.0.1"):
    """运行 FastMCP 服务器"""
    # 确保输出目录存在
    config.ensure_output_dir(output_dir)

    # 获取MCP服务器实例
    mcp_server = mcp._mcp_server

    try:
        # 运行服务器
        if mode == "sse":
            config.logger.info(f"启动SSE服务器: {host}:{port}")
            starlette_app = create_starlette_app(mcp_server, debug=True)
            uvicorn.run(starlette_app, host=host, port=port)
        elif mode == "streamable-http":
            config.logger.info(f"启动Streamable HTTP服务器: {host}:{port}")
            mcp.run(mode, port=port, host=host)
        else:
            # 默认stdio模式
            config.logger.info("启动STDIO服务器")
            mcp.run(mode or "stdio")
    except Exception as e:
        config.logger.error(f"服务异常退出: {str(e)}")
        raise


# 全局输出目录变量
output_dir = config.DEFAULT_OUTPUT_DIR


def set_output_dir(dir_path: str):
    """设置转换后文件的输出目录"""
    global output_dir
    output_dir = dir_path
    config.ensure_output_dir(output_dir)
    return output_dir
```

#### Step 5.3: 更新 pyproject.toml

**修改文件**：`pyproject.toml`

在 `[project.scripts]` 部分更新命令入口：

```toml
[project.scripts]
mcp-pandoc = "mcp_pandoc.cli:main"  # 更新为新的 CLI 入口
```

添加新依赖（如果需要）：

```toml
dependencies = [
    "fastmcp>=2.5.2",
    "python-dotenv>=1.0.0",
    "uvicorn>=0.20.0",      # HTTP 模式需要
    "starlette>=0.27.0",    # SSE 模式需要
    # ... 原有的其他依赖
]
```

### Phase 6: 测试与验证

#### Step 6.1: 本地测试（stdio 模式）

```bash
# 测试原有功能是否正常
mcp-pandoc

# 测试新的 CLI 参数
mcp-pandoc --transport stdio --output-dir ./test_output
```

#### Step 6.2: HTTP 模式测试

```bash
# 启动 SSE 服务器
mcp-pandoc --transport sse --host 0.0.0.0 --port 8001

# 启动 Streamable HTTP 服务器
mcp-pandoc --transport streamable-http --host 127.0.0.1 --port 8001
```

#### Step 6.3: base64 工具测试

创建测试脚本测试新的 `convert-contents-base64` 工具。

### Phase 7: 文档更新

#### Step 7.1: 更新 README.md

添加新功能说明：
- HTTP 模式使用方法
- base64 上传工具使用示例
- 环境变量配置说明

#### Step 7.2: 创建配置文档

说明所有环境变量的含义和使用场景。

### 实施时间估算

| 阶段 | 内容 | 预计时间 |
|-----|------|---------|
| Phase 1 | 环境准备 | 0.5天 |
| Phase 2 | 配置管理 | 0.5天 |
| Phase 3 | 安全函数 | 1天 |
| Phase 4 | base64工具 | 1.5天 |
| Phase 5 | HTTP模式 | 1天 |
| Phase 6 | 测试验证 | 1天 |
| Phase 7 | 文档更新 | 0.5天 |
| **总计** | | **6天** |

### 注意事项

1. **保持兼容性**：每一步修改都要确保原有功能继续正常工作
2. **增量开发**：可以先完成 Phase 2-4（base64 支持），再添加 Phase 5（HTTP 模式）
3. **测试驱动**：每完成一个 Phase 都要进行测试
4. **代码复用**：尽量复用原项目的 Pandoc 转换逻辑，只添加新功能

---

## 代码示例

### 完整的 server.py 框架

```python
"""Pandoc MCP 服务器实现"""

import base64
import binascii
import json
import re
import secrets
import shutil
import subprocess
import traceback
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route
import uvicorn

from . import config
from .converter import PandocConverter

# 初始化 FastMCP
mcp = FastMCP(
    name="Pandoc Document Converter",
    instructions="""...""",
)

# 全局转换器实例
_converter_instance: Optional[PandocConverter] = None


def get_converter() -> PandocConverter:
    """获取转换器单例"""
    global _converter_instance
    if _converter_instance is None:
        _converter_instance = PandocConverter(config.PANDOC_PATH)
    return _converter_instance


# === 工具函数 ===

def _decode_base64_payload(base64_payload: str) -> bytes:
    """解码 base64"""
    # ... (参考前面的实现)


def _sanitize_filename(filename: str) -> str:
    """清理文件名"""
    # ... (参考前面的实现)


def _validate_local_path(path: Path) -> Optional[str]:
    """验证本地路径"""
    # ... (参考前面的实现)


def _build_results_response(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """打包结果"""
    # ... (参考前面的实现)


# === MCP 工具 ===

@mcp.tool()
async def convert_documents(
    file_sources: Annotated[str, Field(...)],
    output_format: Annotated[str, Field(...)],
    input_format: Annotated[str | None, Field(...)] = None,
) -> Dict[str, Any]:
    """转换文档（本地路径或URL）"""
    sources = _parse_list_input(file_sources)

    results = []
    for source in sources:
        if source.startswith(("http://", "https://")):
            # URL 处理
            result = await _convert_url(source, output_format)
        else:
            # 本地文件处理
            path = Path(source)

            # 安全验证
            validation_error = _validate_local_path(path)
            if validation_error:
                results.append({
                    "filename": path.name,
                    "source_path": source,
                    "status": "error",
                    "error_message": validation_error,
                })
                continue

            # 转换
            result = await _convert_local_file(path, output_format, input_format)
            results.append(result)

    return _build_results_response(results)


@mcp.tool()
async def convert_documents_base64(
    files: Annotated[List[Dict[str, Any]], Field(...)],
    output_format: Annotated[str, Field(...)],
    input_format: Annotated[str | None, Field(...)] = None,
    keep_uploaded_files: Annotated[bool, Field(...)] = False,
) -> Dict[str, Any]:
    """转换文档（base64上传）"""

    if not files:
        return {"status": "error", "error": "files 不能为空"}

    # 创建临时目录
    upload_dir = Path(config.TEMP_DIR) / "_uploads" / secrets.token_hex(12)
    upload_dir.mkdir(parents=True, exist_ok=True)

    results = []

    try:
        for item in files:
            # 1. 验证
            if not isinstance(item, dict):
                results.append({
                    "status": "error",
                    "error_message": "每个文件必须是对象",
                })
                continue

            filename = _sanitize_filename(item.get("filename", ""))
            content_b64 = item.get("content_base64")

            if not isinstance(content_b64, str):
                results.append({
                    "filename": filename,
                    "status": "error",
                    "error_message": "缺少 content_base64",
                })
                continue

            # 2. 解码
            try:
                file_bytes = _decode_base64_payload(content_b64)

                # 大小检查
                if len(file_bytes) > config.MAX_UPLOAD_BYTES:
                    raise ValueError(f"文件过大: {len(file_bytes)} bytes")

                # 保存临时文件
                temp_path = upload_dir / filename
                temp_path.write_bytes(file_bytes)

                # 转换
                result = await _convert_local_file(temp_path, output_format, input_format)
                results.append(result)

            except Exception as e:
                results.append({
                    "filename": filename,
                    "status": "error",
                    "error_message": str(e),
                })

    finally:
        # 清理
        if not keep_uploaded_files and upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

    return _build_results_response(results)


@mcp.tool()
async def list_formats() -> Dict[str, Any]:
    """列出支持的格式"""
    converter = get_converter()
    return converter.list_formats()


@mcp.tool()
async def get_pandoc_version() -> Dict[str, Any]:
    """获取版本信息"""
    converter = get_converter()
    return converter.get_version()


# === 内部函数 ===

async def _convert_local_file(
    input_path: Path,
    output_format: str,
    input_format: Optional[str] = None,
) -> Dict[str, Any]:
    """转换本地文件"""
    try:
        converter = get_converter()
        output_path = await converter.convert_file(
            input_path,
            output_format,
            input_format,
        )

        # 读取输出内容
        content = output_path.read_text(encoding="utf-8")

        return {
            "filename": input_path.name,
            "status": "success",
            "content": content,
            "output_path": str(output_path),
        }
    except Exception as e:
        return {
            "filename": input_path.name,
            "status": "error",
            "error_message": str(e),
        }


# === 服务器启动 ===

def create_starlette_app(mcp_server, *, debug: bool = False) -> Starlette:
    """创建 SSE 服务器"""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


def run_server(mode=None, port=8001, host="127.0.0.1"):
    """启动服务器"""
    mcp_server = mcp._mcp_server

    try:
        if mode == "sse":
            config.logger.info(f"启动SSE服务器: {host}:{port}")
            app = create_starlette_app(mcp_server, debug=True)
            uvicorn.run(app, host=host, port=port)
        elif mode == "streamable-http":
            config.logger.info(f"启动HTTP服务器: {host}:{port}")
            mcp.run(mode, port=port, host=host)
        else:
            config.logger.info("启动STDIO模式")
            mcp.run(mode or "stdio")
    except Exception as e:
        config.logger.error(f"服务异常: {str(e)}")
        traceback.print_exc()
```

---

## 部署场景

### 场景1：本地开发（stdio）

```bash
# 安装
cd pandoc-mcp
uv venv
uv pip install -e .

# 配置
cp .env.example .env
# 编辑 .env，设置 PANDOC_PATH 等

# 运行
pandoc-mcp --transport stdio
```

**Claude Desktop 配置**：
```json
{
  "mcpServers": {
    "pandoc-mcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/pandoc-mcp", "run", "-m", "pandoc.cli"],
      "env": {
        "PANDOC_OUTPUT_DIR": "./output"
      }
    }
  }
}
```

### 场景2：内网团队服务（HTTP）

```bash
# 配置
export PANDOC_MCP_REQUIRE_ALLOWLIST=true
export PANDOC_MCP_ALLOWED_INPUT_ROOTS="/data/shared:/home/projects"
export PANDOC_MCP_MAX_FILE_BYTES=104857600

# 运行
pandoc-mcp --transport streamable-http --host 0.0.0.0 --port 8001
```

### 场景3：公网服务（Docker + HTTPS）

```yaml
# docker-compose.yml
version: '3.8'

services:
  pandoc-mcp:
    build: .
    ports:
      - "8001:8001"
    environment:
      - PANDOC_OUTPUT_DIR=/app/output
      - PANDOC_TEMP_DIR=/app/temp
      - PANDOC_MCP_DISABLE_PATH_INPUT=true
      - PANDOC_MCP_MAX_UPLOAD_BYTES=52428800
      - PANDOC_LOG_LEVEL=INFO
    volumes:
      - ./output:/app/output
      - ./temp:/app/temp
    restart: unless-stopped
    command: ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8001"]

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - pandoc-mcp
```

---

## 总结

### 核心要点

1. **双模式支持**：stdio（本地）+ base64（远程）
2. **安全优先**：文件大小限制 + 路径白名单 + 文件名清理
3. **参数化配置**：通过环境变量控制所有行为
4. **统一接口**：一致的返回格式 + 完善的错误处理

### 关键差异：Pandoc vs MinerU

| 方面 | MinerU | Pandoc MCP |
|------|--------|-----------|
| 核心功能 | PDF→Markdown | 多格式互转 |
| 外部依赖 | MinerU API | Pandoc CLI |
| 处理时间 | 较长（需API） | 较快（本地） |
| 复杂度 | 高（OCR、AI） | 中（格式转换） |

### 下一步行动

1. ✅ 创建项目结构
2. ✅ 实现 stdio 模式 + 基础转换
3. ✅ 添加 base64 上传支持
4. ✅ 完善安全验证
5. ✅ 编写测试和文档
6. ✅ Docker 部署配置

---

## 参考资料

- [FastMCP 官方文档](https://github.com/jlowin/fastmcp)
- [Pandoc 用户手册](https://pandoc.org/MANUAL.html)
- [MinerU 项目](https://github.com/opendatalab/MinerU)
- [MCP 协议规范](https://modelcontextprotocol.io/)

---

**文档维护**: 请根据实际开发进展更新本文档
**反馈渠道**: 项目 Issue 或团队讨论
