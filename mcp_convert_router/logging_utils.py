"""日志工具模块 - 提供请求级别的日志记录。

每次请求都有唯一的 request_id，便于问题追踪和排查。
"""

import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

def _get_log_level() -> int:
    """从环境变量读取日志等级。"""
    level_str = (os.getenv("MCP_CONVERT_LOG_LEVEL") or "INFO").upper().strip()
    return getattr(logging, level_str, logging.INFO)


# 配置日志格式
logging.basicConfig(
    level=_get_log_level(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger("mcp-convert-router")


def generate_request_id() -> str:
    """生成唯一的请求 ID。"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{timestamp}_{short_uuid}"


@dataclass
class RequestContext:
    """请求上下文，记录请求的完整生命周期。"""
    request_id: str = field(default_factory=generate_request_id)
    start_time: float = field(default_factory=time.time)
    source_type: Optional[str] = None
    source_value: Optional[str] = None
    detected_type: Optional[str] = None
    engine_used: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)

    def log_event(self, event_type: str, message: str, **kwargs):
        """记录一个事件。"""
        elapsed_ms = int((time.time() - self.start_time) * 1000)
        event = {
            "type": event_type,
            "message": message,
            "elapsed_ms": elapsed_ms,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.events.append(event)

        # 输出到日志
        log_msg = f"[{self.request_id}] [{event_type}] {message}"
        if kwargs:
            details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            log_msg += f" ({details})"

        if event_type == "error":
            logger.error(log_msg)
        elif event_type == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def log_start(self, source_type: str, source_value: str):
        """记录请求开始。"""
        self.source_type = source_type
        # 对敏感信息进行脱敏
        if source_type == "croc_code":
            safe_value = f"{source_value[:4]}****" if len(source_value) > 4 else "****"
        elif source_type == "url":
            # 只保留域名
            from urllib.parse import urlparse
            parsed = urlparse(source_value)
            safe_value = f"{parsed.scheme}://{parsed.netloc}/..."
        else:
            safe_value = source_value

        self.source_value = safe_value
        self.log_event("request_start", f"开始处理请求",
                       source_type=source_type, source_value=safe_value)

    def log_file_received(self, filename: str, size_bytes: int):
        """记录文件接收完成。"""
        size_mb = size_bytes / 1024 / 1024
        self.log_event("file_received", f"文件已接收: {filename}",
                       filename=filename, size_bytes=size_bytes, size_mb=f"{size_mb:.2f}")

    def log_type_detected(self, detected_type: str, file_ext: str):
        """记录文件类型识别结果。"""
        self.detected_type = detected_type
        self.log_event("type_detected", f"文件类型识别: {detected_type}",
                       detected_type=detected_type, file_ext=file_ext)

    def log_engine_selected(self, engine: str, route: str):
        """记录引擎选择。"""
        self.engine_used = engine
        self.log_event("engine_selected", f"选择引擎: {engine}",
                       engine=engine, route=route)

    def log_conversion_start(self, engine: str):
        """记录转换开始。"""
        self.log_event("conversion_start", f"开始转换 ({engine})", engine=engine)

    def log_conversion_complete(self, engine: str, success: bool, markdown_length: int = 0):
        """记录转换完成。"""
        status = "成功" if success else "失败"
        self.log_event("conversion_complete", f"转换{status} ({engine})",
                       engine=engine, success=success, markdown_length=markdown_length)

    def log_error(self, error_code: str, error_message: str):
        """记录错误。"""
        self.log_event("error", f"{error_code}: {error_message}",
                       error_code=error_code)

    def log_warning(self, message: str):
        """记录警告。"""
        self.log_event("warning", message)

    def log_complete(self, success: bool):
        """记录请求完成。"""
        total_ms = int((time.time() - self.start_time) * 1000)
        status = "成功" if success else "失败"
        self.log_event("request_complete", f"请求处理{status}",
                       success=success, total_ms=total_ms)

    def get_summary(self) -> Dict[str, Any]:
        """获取请求摘要。"""
        total_ms = int((time.time() - self.start_time) * 1000)
        return {
            "request_id": self.request_id,
            "source_type": self.source_type,
            "detected_type": self.detected_type,
            "engine_used": self.engine_used,
            "total_ms": total_ms,
            "event_count": len(self.events)
        }


@contextmanager
def request_context():
    """创建请求上下文的上下文管理器。"""
    ctx = RequestContext()
    try:
        yield ctx
    finally:
        pass  # 可以在这里添加清理逻辑


# 全局请求上下文（用于不方便传递上下文的场景）
_current_context: Optional[RequestContext] = None


def set_current_context(ctx: RequestContext):
    """设置当前请求上下文。"""
    global _current_context
    _current_context = ctx


def get_current_context() -> Optional[RequestContext]:
    """获取当前请求上下文。"""
    return _current_context


def clear_current_context():
    """清除当前请求上下文。"""
    global _current_context
    _current_context = None
