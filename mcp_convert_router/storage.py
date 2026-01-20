"""存储管理模块 - 临时目录、文件名规范化、清理策略。"""

import os
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 默认临时目录
DEFAULT_TEMP_BASE = os.getenv("MCP_CONVERT_TEMP_DIR", "/tmp/mcp-convert")

# 临时文件保留时间（小时）
TEMP_RETENTION_HOURS = int(os.getenv("MCP_CONVERT_RETENTION_HOURS", "24"))


class StorageManager:
    """存储管理器 - 管理临时目录和文件。"""

    def __init__(self, temp_base: Optional[str] = None):
        """
        初始化存储管理器。

        Args:
            temp_base: 临时目录基础路径，默认使用环境变量或 /tmp/mcp-convert
        """
        self.temp_base = Path(temp_base or DEFAULT_TEMP_BASE)
        self._ensure_base_dir()

    def _ensure_base_dir(self):
        """确保基础目录存在。"""
        self.temp_base.mkdir(parents=True, exist_ok=True)

    def create_work_dir(self, prefix: str = "") -> Path:
        """
        创建工作目录。

        Args:
            prefix: 目录名前缀

        Returns:
            Path: 创建的工作目录路径
        """
        # 生成唯一的请求 ID
        request_id = self._generate_request_id()

        if prefix:
            dir_name = f"{prefix}_{request_id}"
        else:
            dir_name = request_id

        work_dir = self.temp_base / dir_name
        work_dir.mkdir(parents=True, exist_ok=True)

        # 创建子目录
        (work_dir / "input").mkdir(exist_ok=True)
        (work_dir / "output").mkdir(exist_ok=True)

        return work_dir

    def _generate_request_id(self) -> str:
        """生成唯一的请求 ID。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        return f"{timestamp}_{unique_id}"

    def sanitize_filename(self, filename: str) -> str:
        """
        清理文件名，防止路径穿越和特殊字符问题。

        Args:
            filename: 原始文件名

        Returns:
            str: 清理后的安全文件名
        """
        # 只保留文件名部分
        name = Path(filename).name

        if not name:
            return "unnamed_file"

        # 移除路径穿越字符
        name = name.replace("..", "")
        name = name.replace("/", "_")
        name = name.replace("\\", "_")

        # 移除或替换特殊字符
        name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)

        # 替换空白字符
        name = re.sub(r"\s+", "_", name)

        # 移除开头和结尾的点和空格
        name = name.strip(". ")

        if not name:
            return "unnamed_file"

        # 限制长度
        if len(name) > 200:
            # 保留扩展名
            stem = Path(name).stem[:180]
            suffix = Path(name).suffix
            name = stem + suffix

        return name

    def get_output_path(self, work_dir: Path, filename: str, ext: str = ".md") -> Path:
        """
        获取输出文件路径。

        Args:
            work_dir: 工作目录
            filename: 原始文件名
            ext: 输出文件扩展名

        Returns:
            Path: 输出文件路径
        """
        safe_name = self.sanitize_filename(filename)
        stem = Path(safe_name).stem
        output_name = f"{stem}{ext}"
        return work_dir / "output" / output_name

    def cleanup_work_dir(self, work_dir: Path, force: bool = False):
        """
        清理工作目录。

        Args:
            work_dir: 要清理的工作目录
            force: 是否强制删除（不检查保留时间）
        """
        if not work_dir.exists():
            return

        if force:
            shutil.rmtree(work_dir, ignore_errors=True)
            return

        # 检查是否超过保留时间
        try:
            mtime = datetime.fromtimestamp(work_dir.stat().st_mtime)
            if datetime.now() - mtime > timedelta(hours=TEMP_RETENTION_HOURS):
                shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass

    def cleanup_old_dirs(self):
        """清理所有超过保留时间的临时目录。"""
        if not self.temp_base.exists():
            return

        cutoff_time = datetime.now() - timedelta(hours=TEMP_RETENTION_HOURS)

        for item in self.temp_base.iterdir():
            if not item.is_dir():
                continue

            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if mtime < cutoff_time:
                    shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass

    def get_disk_usage(self) -> dict:
        """获取临时目录的磁盘使用情况。"""
        if not self.temp_base.exists():
            return {"total_bytes": 0, "file_count": 0, "dir_count": 0}

        total_bytes = 0
        file_count = 0
        dir_count = 0

        for item in self.temp_base.rglob("*"):
            if item.is_file():
                total_bytes += item.stat().st_size
                file_count += 1
            elif item.is_dir():
                dir_count += 1

        return {
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / 1024 / 1024, 2),
            "file_count": file_count,
            "dir_count": dir_count,
            "base_path": str(self.temp_base)
        }
