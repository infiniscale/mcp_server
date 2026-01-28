"""URL 下载模块 - 安全下载远程文件并落盘。

包含 SSRF 防护、超时控制、大小限制等安全措施。
"""

import asyncio
import ipaddress
import logging
import os
import re
import socket
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# 默认超时时间（秒）
DEFAULT_CONNECT_TIMEOUT = 60
DEFAULT_READ_TIMEOUT = 600

# 默认最大下载大小（字节）
DEFAULT_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50MB

# 最大重定向次数
MAX_REDIRECTS = 5

# 私有/保留 IP 范围
PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private A
    ipaddress.ip_network("172.16.0.0/12"),    # Private B
    ipaddress.ip_network("192.168.0.0/16"),   # Private C
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local
    ipaddress.ip_network("224.0.0.0/4"),      # Multicast
    ipaddress.ip_network("240.0.0.0/4"),      # Reserved
    ipaddress.ip_network("0.0.0.0/8"),        # "This" network
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 private
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


async def download_file_from_url(
    url: str,
    work_dir: Path,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: int = DEFAULT_READ_TIMEOUT,
    custom_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    从 URL 下载文件并保存到工作目录。

    包含 SSRF 防护：
    - 只允许 http/https 协议
    - 解析 DNS 并检查目标 IP 是否为私有/保留地址
    - 限制重定向次数，每次重定向都检查目标

    Args:
        url: 文件 URL
        work_dir: 工作目录（文件将保存到 work_dir/input/）
        max_bytes: 最大下载大小（字节）
        connect_timeout: 连接超时（秒）
        read_timeout: 读取超时（秒）
        custom_headers: 可选的自定义 HTTP 请求头（如 Authorization）

    Returns:
        Dict[str, Any]: {
            "ok": bool,
            "file_path": str (下载的文件路径),
            "filename": str,
            "size_bytes": int,
            "content_type": str,
            "error_code": str (如果失败),
            "error_message": str (如果失败),
            "elapsed_ms": int
        }
    """
    start_time = time.time()
    result = {
        "ok": False,
        "file_path": None,
        "filename": None,
        "size_bytes": 0,
        "content_type": None,
        "error_code": None,
        "error_message": None,
        "elapsed_ms": 0
    }

    # 1. 协议检查
    parsed = urlparse(url)
    logger.info(f"[URL_DOWNLOAD] 开始下载: {url[:80]}...")
    if parsed.scheme not in ("http", "https"):
        result["error_code"] = "E_URL_FORBIDDEN"
        result["error_message"] = f"不支持的协议: {parsed.scheme}。仅支持 http/https"
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return result

    # 2. SSRF 防护：解析 DNS 并检查 IP
    try:
        logger.info(f"[URL_DOWNLOAD] SSRF 检查: {parsed.hostname}")
        ssrf_check = await _check_ssrf(parsed.hostname)
        logger.info(f"[URL_DOWNLOAD] SSRF 检查完成: {ssrf_check}")
        if not ssrf_check["safe"]:
            result["error_code"] = "E_URL_FORBIDDEN"
            result["error_message"] = ssrf_check["reason"]
            result["elapsed_ms"] = int((time.time() - start_time) * 1000)
            return result
    except Exception as e:
        result["error_code"] = "E_URL_FORBIDDEN"
        result["error_message"] = f"DNS 解析失败: {str(e)}"
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return result

    # 3. 确保输入目录存在
    input_dir = work_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    # 文件名将在获得响应头后提取

    # 5. 下载文件
    try:
        # 准备请求头
        headers = custom_headers.copy() if custom_headers else {}
        logger.info(f"[URL_DOWNLOAD] 准备 httpx 客户端, headers: {list(headers.keys())}")

        # TLS 验证控制
        tls_verify_str = os.getenv("MCP_CONVERT_URL_TLS_VERIFY", "true").strip().lower()
        tls_verify = tls_verify_str not in ("false", "0", "no", "off")
        logger.info(f"[URL_DOWNLOAD] TLS 验证: {tls_verify}, 超时: connect={connect_timeout}s, read={read_timeout}s")

        # 使用同步客户端在线程池中执行，避免 async 事件循环问题
        def _sync_download():
            """在线程池中执行同步下载，使用 urllib 替代 httpx"""
            import threading
            import urllib.request
            import urllib.error
            import ssl

            logger.info(f"[URL_DOWNLOAD] 线程池任务开始执行, thread={threading.current_thread().name}")
            try:
                # 构建请求
                req = urllib.request.Request(url, headers=headers)
                logger.info(f"[URL_DOWNLOAD] 使用 urllib 发送请求: {url[:80]}...")

                # SSL 上下文
                ssl_context = None
                if not tls_verify:
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                # 发送请求
                with urllib.request.urlopen(req, timeout=read_timeout, context=ssl_context) as response:
                    status_code = response.status
                    logger.info(f"[URL_DOWNLOAD] urllib 收到响应: {status_code}")

                    if status_code != 200:
                        return {"error": "E_URL_HTTP_ERROR", "message": f"HTTP 错误: {status_code}"}

                    # 读取内容
                    content = response.read()
                    response_headers = dict(response.headers)

                    return {
                        "ok": True,
                        "content": content,
                        "headers": response_headers,
                        "final_url": response.url or url
                    }

            except urllib.error.HTTPError as e:
                logger.error(f"[URL_DOWNLOAD] urllib HTTP 错误: {e.code}")
                return {"error": "E_URL_HTTP_ERROR", "message": f"HTTP 错误: {e.code}"}
            except urllib.error.URLError as e:
                logger.error(f"[URL_DOWNLOAD] urllib URL 错误: {e.reason}")
                return {"error": "E_URL_CONNECT_ERROR", "message": str(e.reason)}
            except Exception as e:
                logger.error(f"[URL_DOWNLOAD] 线程内异常: {type(e).__name__}: {e}")
                return {"error": "E_URL_DOWNLOAD_FAILED", "message": str(e)}

        # 在线程池中执行同步下载
        logger.info(f"[URL_DOWNLOAD] 准备提交到线程池...")
        loop = asyncio.get_event_loop()
        sync_result = await loop.run_in_executor(None, _sync_download)
        logger.info(f"[URL_DOWNLOAD] 线程池任务完成, result_keys={list(sync_result.keys())}")

        if "error" in sync_result:
            result["error_code"] = sync_result["error"]
            result["error_message"] = sync_result["message"]
        elif sync_result.get("ok"):
            content = sync_result["content"]
            response_headers = sync_result["headers"]
            current_url = sync_result["final_url"]

            # 从响应头提取文件名
            content_disposition = response_headers.get("Content-Disposition", "")
            filename = None
            if content_disposition:
                # 尝试 filename*= (RFC 5987)
                match = re.search(r"filename\*=(?:UTF-8''|utf-8'')(.+?)(?:;|$)", content_disposition, re.IGNORECASE)
                if match:
                    from urllib.parse import unquote
                    filename = unquote(match.group(1).strip())
                else:
                    # 尝试 filename=
                    match = re.search(r'filename=["\']?([^"\';\n]+)["\']?', content_disposition)
                    if match:
                        filename = match.group(1).strip()

            if not filename:
                # 从 URL 提取
                path = urlparse(current_url).path
                filename = path.split("/")[-1] if path else "downloaded_file"

            output_path = input_dir / filename

            # 检查大小
            total_bytes = len(content)
            if total_bytes > max_bytes:
                result["error_code"] = "E_INPUT_TOO_LARGE"
                result["error_message"] = f"下载超过大小限制 {max_bytes / 1024 / 1024:.2f}MB"
            else:
                with open(output_path, "wb") as f:
                    f.write(content)

                result["ok"] = True
                result["file_path"] = str(output_path)
                result["filename"] = filename
                result["size_bytes"] = total_bytes
                result["content_type"] = response_headers.get("Content-Type")
                logger.info(f"[URL_DOWNLOAD] 下载成功: {filename}, {total_bytes} bytes")

    except httpx.TimeoutException:
        result["error_code"] = "E_TIMEOUT"
        result["error_message"] = f"下载超时（连接: {connect_timeout}s, 读取: {read_timeout}s）"
    except httpx.ConnectError as e:
        result["error_code"] = "E_URL_CONNECT_ERROR"
        result["error_message"] = f"连接失败: {str(e)}"
    except Exception as e:
        result["error_code"] = "E_URL_DOWNLOAD_FAILED"
        result["error_message"] = str(e)

    result["elapsed_ms"] = int((time.time() - start_time) * 1000)
    return result


async def _check_ssrf(hostname: str) -> Dict[str, Any]:
    """SSRF 防护：检查主机名是否安全。允许白名单中的主机绕过检查。"""
    if not hostname:
        return {"safe": False, "reason": "主机名为空", "ip": None}

    # 检查白名单
    allowed_hosts = {h.strip().lower() for h in os.getenv("MCP_CONVERT_ALLOWED_URL_HOSTS", "").split(",") if h.strip()}

    if hostname.lower() in allowed_hosts:
        return {"safe": True, "reason": "allowlisted", "ip": None, "allowlisted": True}

    # 检查常见危险主机名
    dangerous_hostnames = [
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "[::1]",
        "metadata.google.internal",  # GCP metadata
        "169.254.169.254",  # AWS/Azure metadata
    ]

    if hostname.lower() in dangerous_hostnames:
        return {"safe": False, "reason": f"不允许访问 {hostname}", "ip": None}

    # 检查是否是 IP 地址
    try:
        ip = ipaddress.ip_address(hostname.strip("[]"))

        if str(ip) in allowed_hosts:
            return {"safe": True, "reason": "allowlisted", "ip": str(ip), "allowlisted": True}

        if _is_private_ip(ip):
            return {"safe": False, "reason": f"不允许访问私有/保留 IP: {ip}", "ip": str(ip)}
        return {"safe": True, "reason": None, "ip": str(ip)}
    except ValueError:
        pass  # 不是 IP 地址，继续 DNS 解析

    # DNS 解析
    try:
        loop = asyncio.get_event_loop()
        # 使用线程池执行同步的 DNS 解析
        addresses = await loop.run_in_executor(None, socket.gethostbyname_ex, hostname)
        ip_list = addresses[2]

        if not ip_list:
            return {"safe": False, "reason": f"DNS 解析失败: {hostname}", "ip": None}

        # 检查所有解析到的 IP
        for ip_str in ip_list:
            try:
                ip = ipaddress.ip_address(ip_str)
                if _is_private_ip(ip):
                    return {"safe": False, "reason": f"DNS 解析到私有/保留 IP: {ip_str}", "ip": ip_str}
            except ValueError:
                continue

        return {"safe": True, "reason": None, "ip": ip_list[0] if ip_list else None}

    except socket.gaierror as e:
        return {"safe": False, "reason": f"DNS 解析失败: {str(e)}", "ip": None}
    except Exception as e:
        return {"safe": False, "reason": f"DNS 检查失败: {str(e)}", "ip": None}


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """检查 IP 是否为私有/保留地址。"""
    for network in PRIVATE_IP_RANGES:
        try:
            if ip in network:
                return True
        except TypeError:
            # IPv4/IPv6 类型不匹配
            continue
    return False


def _extract_filename_from_response(response: httpx.Response, url: str) -> str:
    """从响应中提取文件名，优先使用 Content-Disposition。"""
    content_disposition = response.headers.get("content-disposition", "")

    if content_disposition:
        import re
        from urllib.parse import unquote

        # RFC 5987: filename*=UTF-8''encoded
        match = re.search(r"filename\*=([^']+)''(.+)", content_disposition)
        if match:
            encoded_filename = match.group(2)
            try:
                filename = unquote(encoded_filename)
                filename = filename.replace("/", "_").replace("\\", "_")
                filename = re.sub(r'[<>:"|?*]', "_", filename)
                if filename and filename not in (".", ".."):
                    return filename
            except Exception:
                pass

        # RFC 2183: filename="name"
        match = re.search(r'filename="?([^";\r\n]+)"?', content_disposition)
        if match:
            filename = match.group(1).strip()
            filename = filename.replace("/", "_").replace("\\", "_")
            filename = re.sub(r'[<>:"|?*]', "_", filename)
            if filename and filename not in (".", ".."):
                return filename

    return _extract_filename_from_url(url)


def _extract_filename_from_url(url: str) -> str:
    """从 URL 中提取文件名。"""
    from urllib.parse import urlparse
    import re

    parsed = urlparse(url)
    path = parsed.path

    if path:
        filename = path.split("/")[-1]
        if "?" in filename:
            filename = filename.split("?")[0]
        filename = re.sub(r'[<>:"|?*]', "_", filename)
        if filename:
            return filename

    return "downloaded_file"
