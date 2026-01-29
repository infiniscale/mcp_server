# OpenWebUI Tools

这个目录包含用于 OpenWebUI 的 Tool 脚本，用于与 MCP Convert Router 服务集成。

## 文件列表

| 文件 | 功能 |
|------|------|
| `file_to_markdown.py` | 准备文件转换参数，调用 MCP 进行 Markdown 转换 |

## 安装方法

### 1. 登录 OpenWebUI

使用管理员账户登录 OpenWebUI。

### 2. 进入 Tools 管理页面

- 点击左侧菜单 **Workspace**
- 选择 **Tools**
- 点击 **+ Create a new tool**

### 3. 复制脚本内容

打开 `file_to_markdown.py` 文件，复制全部内容到 OpenWebUI 的 Tool 编辑器中。

### 4. 保存

点击 **Save** 保存 Tool。

### 5. 配置（可选）

在 Tool 的 Valves 配置中，可以修改：

- **mcp_url**: MCP Convert Router 的 JSON-RPC 地址（例如 `http://mcp:25081/mcp/`）
- **openwebui_base_url**: OpenWebUI 的基础 URL（默认：`http://192.168.1.236:22030`）
- **openwebui_api_key**: （可选）OpenWebUI API Key（当 `__user__.token` 不存在时使用）
- **timeout_seconds**: Tool 等待 MCP 处理的超时时间（默认 600 秒）

## 使用方法

### 前提条件

1. MCP Convert Router 服务已部署并运行
2. MCP 服务已通过 mcpo 代理连接到 OpenWebUI

### 使用流程

1. **上传文件**：在 OpenWebUI 对话界面上传文件（PDF、DOCX、图片等）

2. **调用 Tool**：直接告诉 LLM 转换“刚上传的文件”即可（无需手动查 file_id），例如：
   ```
   请使用 File to Markdown Converter 工具把我刚上传的文件转换成 Markdown
   ```
   如果一次上传了多个文件，工具会依次转换并把结果按文件名分段返回。

3. **LLM 自动调用 MCP**：Tool 会返回调用指令，LLM 会自动调用 `convert_to_markdown` 工具完成转换

### 参数说明

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| file_id | string | ✅ | - | 上传文件的 UUID |
| enable_ocr | bool | ❌ | false | 是否启用 OCR（扫描件需要） |
| language | string | ❌ | "ch" | OCR 语言（ch=中文, en=英文） |

## 工作原理

```
用户上传文件到 OpenWebUI
    ↓
用户请求转换文件
    ↓
LLM 调用 prepare_file_for_conversion(file_id)
    ↓
Tool 脚本：
  1. 拼接文件 URL: http://openwebui/api/v1/files/{file_id}/content
  2. 获取当前用户的认证 Token
  3. 返回调用指令
    ↓
LLM 调用 convert_to_markdown(source=URL, url_headers={...})
    ↓
MCP 服务：
  1. 下载文件（带认证头）
  2. 转换为 Markdown
  3. 返回结果
    ↓
用户看到 Markdown 内容
```

## 职责划分

| 组件 | 职责 |
|------|------|
| **Tool 脚本** | 获取 file_id → 拼接 URL → 准备认证头 → 返回调用指令 |
| **MCP 服务** | 接收 URL → 下载文件 → 转换 Markdown → 返回结果 |

## 故障排查

### 问题：401 Unauthorized

**原因**：认证头无效或未传递

**解决**：
- 确保用户已登录 OpenWebUI
- 检查 `__user__` 参数是否包含有效的 token

### 问题：文件不存在

**原因**：file_id 无效或文件已被删除

**解决**：
- 确认文件已成功上传
- 检查 file_id 格式是否正确（UUID 格式）

### 问题：MCP 服务无响应

**原因**：MCP 服务未运行或网络问题

**解决**：
- 检查 MCP 服务状态：`docker logs mcp-convert-router`
- 检查 mcpo 代理状态：`docker logs mcpo`

### 问题：下载超时（600s）——MCP 回调 OpenWebUI 时卡住

**现象**：通过 OpenWebUI Tool 调用 MCP 后，MCP 需要再访问 `OpenWebUI /api/v1/files/{id}/content` 下载文件，但一直超时。

**根因（常见）**：调用链是「OpenWebUI（执行 Tool）→ MCP → OpenWebUI（文件下载）」。如果 OpenWebUI 在执行 Tool 时占用了同一个 worker/事件循环（同步阻塞），就会导致 OpenWebUI 无法并发处理文件下载请求，从而形成“自调用死锁”。

**解决**：
- 优先用 OpenWebUI 原生 MCP（见 `docs/openwebui/README.md`），避免 Tool 脚本同步阻塞 OpenWebUI。
- 或者把 OpenWebUI 配置为可并发处理请求（例如多 worker / 多线程），保证 Tool 执行期间 `/api/v1/files/.../content` 仍可被访问。
- 使用本仓库 `file_to_markdown.py` v2.1.0+（`convert_file` 为 async），减少阻塞概率（取决于 OpenWebUI Tool 运行方式）。

## 相关文档

- [MCP Convert Router 文档](../mcp_convert_router/README.md)
- [OpenWebUI 官方文档](https://docs.openwebui.com)
