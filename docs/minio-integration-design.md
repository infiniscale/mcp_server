# MinIO集成设计方案

## 问题背景

在Cherry Studio等MCP客户端中:
- ✅ 可以获取文件内容 (base64或文本)
- ❌ 无法获取文件元数据(文件名、路径等)
- ❌ 远程MCP协议无法直接访问文件系统

## 解决方案

### 架构概览

```
Cherry Studio Client
    ↓ (上传文件内容 base64)
Pandoc MCP Server
    ↓ (转换文件)
    ↓ (存储到MinIO)
MinIO Storage
    ↓ (生成下载链接)
Response to Client
```

### 实现步骤

#### 1. MinIO配置模块 (`config.py`)

添加以下环境变量配置:

```python
# MinIO Configuration
MINIO_ENABLED = os.getenv("PANDOC_MINIO_ENABLED", "").lower() in ["true", "1", "yes"]
MINIO_ENDPOINT = os.getenv("PANDOC_MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("PANDOC_MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("PANDOC_MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("PANDOC_MINIO_BUCKET", "pandoc-conversions")
MINIO_SECURE = os.getenv("PANDOC_MINIO_SECURE", "false").lower() in ["true", "1", "yes"]
MINIO_URL_EXPIRY = int(os.getenv("PANDOC_MINIO_URL_EXPIRY", str(7 * 24 * 3600)))  # 7天
```

#### 2. MinIO存储模块 (`storage.py`)

创建新文件处理MinIO操作:

```python
"""MinIO storage integration for Pandoc MCP."""

import os
from datetime import timedelta
from pathlib import Path
from typing import Optional
import logging

try:
    from minio import Minio
    from minio.error import S3Error
    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False

from . import config

logger = logging.getLogger(__name__)


class MinIOStorage:
    """MinIO storage handler for converted files."""

    def __init__(self):
        """Initialize MinIO client."""
        if not MINIO_AVAILABLE:
            raise ImportError("minio package not installed. Install with: pip install minio")

        if not config.MINIO_ENABLED:
            raise RuntimeError("MinIO is not enabled in configuration")

        if not config.MINIO_ACCESS_KEY or not config.MINIO_SECRET_KEY:
            raise RuntimeError("MinIO credentials not configured")

        self.client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_SECURE
        )
        self.bucket = config.MINIO_BUCKET

        # Ensure bucket exists
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Ensure the bucket exists, create if not."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created MinIO bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"Failed to check/create bucket: {e}")
            raise

    def upload_file(
        self,
        file_path: Path,
        object_name: Optional[str] = None,
        content_type: Optional[str] = None
    ) -> dict:
        """Upload file to MinIO and return metadata with download URL.

        Args:
            file_path: Path to file to upload
            object_name: Optional custom object name (defaults to filename)
            content_type: Optional MIME type

        Returns:
            Dictionary containing:
            - object_name: Name in MinIO
            - download_url: Pre-signed download URL
            - size: File size in bytes
            - content_type: MIME type
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Generate object name with timestamp to avoid collisions
        if not object_name:
            import time
            timestamp = int(time.time())
            object_name = f"{timestamp}_{file_path.name}"

        # Detect content type if not provided
        if not content_type:
            content_type = self._detect_content_type(file_path)

        try:
            # Upload file
            result = self.client.fput_object(
                self.bucket,
                object_name,
                str(file_path),
                content_type=content_type
            )

            logger.info(f"Uploaded {file_path.name} to MinIO as {object_name}")

            # Generate pre-signed download URL
            download_url = self.client.presigned_get_object(
                self.bucket,
                object_name,
                expires=timedelta(seconds=config.MINIO_URL_EXPIRY)
            )

            # Get file size
            file_size = file_path.stat().st_size

            return {
                "object_name": object_name,
                "download_url": download_url,
                "size": file_size,
                "content_type": content_type,
                "bucket": self.bucket
            }

        except S3Error as e:
            logger.error(f"Failed to upload to MinIO: {e}")
            raise

    def _detect_content_type(self, file_path: Path) -> str:
        """Detect MIME type from file extension."""
        ext = file_path.suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".md": "text/markdown",
            ".html": "text/html",
            ".txt": "text/plain",
            ".epub": "application/epub+zip",
            ".odt": "application/vnd.oasis.opendocument.text",
            ".tex": "application/x-tex",
            ".ipynb": "application/x-ipynb+json",
        }
        return mime_map.get(ext, "application/octet-stream")


def get_storage() -> Optional[MinIOStorage]:
    """Get MinIO storage instance if enabled.

    Returns:
        MinIOStorage instance or None if disabled
    """
    if not config.MINIO_ENABLED:
        return None

    try:
        return MinIOStorage()
    except Exception as e:
        logger.error(f"Failed to initialize MinIO storage: {e}")
        return None
```

#### 3. 修改 `server.py` - 增强 `convert-contents-base64` 工具

在 `_handle_convert_contents_base64` 函数中添加MinIO上传逻辑:

```python
# 在文件转换完成后 (第943-972行之间)
# 添加MinIO上传逻辑

# Import at top of file
from . import storage

# In _handle_convert_contents_base64, after conversion succeeds:
if output_path.exists():
    # Try to upload to MinIO if enabled
    minio_client = storage.get_storage()
    if minio_client:
        try:
            upload_result = minio_client.upload_file(
                output_path,
                content_type=result.get("content_type")
            )

            # Add MinIO metadata to result
            result["minio"] = {
                "uploaded": True,
                "download_url": upload_result["download_url"],
                "object_name": upload_result["object_name"],
                "size": upload_result["size"]
            }

            logger.info(f"File uploaded to MinIO: {upload_result['download_url']}")

        except Exception as e:
            logger.warning(f"Failed to upload to MinIO: {e}")
            result["minio"] = {
                "uploaded": False,
                "error": str(e)
            }
```

#### 4. 更新响应格式

修改文本输出以包含下载链接 (第993-1034行):

```python
if result.get("minio", {}).get("uploaded"):
    minio_info = result["minio"]
    text_output = (
        f"File '{result.get('filename')}' successfully converted to {output_format}.\n\n"
        f"📥 Download URL (有效期{config.MINIO_URL_EXPIRY // 3600}小时):\n"
        f"{minio_info['download_url']}\n\n"
        f"文件大小: {minio_info['size']} bytes\n"
    )

    # 对于小文件，同时返回内联内容
    if result.get("content") and len(result["content"]) < 5000:
        text_output += f"\n预览内容:\n{result['content'][:500]}...\n"
    elif result.get("content_base64"):
        text_output += f"\nBase64 内容: {len(result['content_base64'])} 字符\n"
```

### 环境变量配置示例

```bash
# MinIO配置
PANDOC_MINIO_ENABLED=true
PANDOC_MINIO_ENDPOINT=minio.example.com:9000
PANDOC_MINIO_ACCESS_KEY=your_access_key
PANDOC_MINIO_SECRET_KEY=your_secret_key
PANDOC_MINIO_BUCKET=pandoc-conversions
PANDOC_MINIO_SECURE=true  # 使用HTTPS
PANDOC_MINIO_URL_EXPIRY=604800  # 7天 (秒)
```

### 工作流程示例

```
用户在Cherry Studio上传PDF文件
    ↓
Cherry Studio发送MCP请求:
{
  "tool": "convert-contents-base64",
  "files": [{
    "filename": "document.pdf",
    "content_base64": "JVBERi0xLjQK..."
  }],
  "output_format": "markdown"
}
    ↓
Pandoc MCP Server:
1. 解码base64内容
2. 保存到临时文件
3. 使用Pandoc转换为Markdown
4. 上传结果到MinIO
5. 生成下载链接
    ↓
返回响应:
{
  "status": "success",
  "filename": "document.pdf",
  "content": "# Document Title\n\n...",
  "minio": {
    "uploaded": true,
    "download_url": "https://minio.example.com/pandoc-conversions/1234567890_document.md?X-Amz-...",
    "size": 2048
  }
}
```

### 优势

1. ✅ **解决远程访问问题**: 通过MinIO提供持久化存储
2. ✅ **灵活返回**: 小文件返回内联内容 + 链接，大文件仅返回链接
3. ✅ **安全**: 使用预签名URL,有过期时间
4. ✅ **可选功能**: MinIO是可选的,不影响现有功能
5. ✅ **清理策略**: 临时文件仍然会被清理,MinIO存储可独立管理

### 依赖包

```bash
pip install minio
```

### 未来改进

1. 添加MinIO生命周期策略自动清理旧文件
2. 支持自定义过期时间
3. 支持分片上传大文件
4. 添加进度回调
