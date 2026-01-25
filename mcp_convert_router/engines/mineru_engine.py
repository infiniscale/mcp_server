"""MinerU 引擎封装 - 直接通过 HTTP 调用 MinerU（不依赖 mcp_mineru 代码）。

注意：mcp_mineru 目录仅作为参考，本引擎不 import 其中任何模块。
"""

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..logging_utils import get_current_context
from ..zip_security import safe_extract_zip

# 超时与轮询
MINERU_TIMEOUT = int(os.getenv("MINERU_TIMEOUT", "300"))
MINERU_POLL_INTERVAL_SECONDS = int(os.getenv("MINERU_POLL_INTERVAL_SECONDS", "5"))
MINERU_MAX_RESULT_ZIP_BYTES = int(os.getenv("MINERU_MAX_RESULT_ZIP_BYTES", "209715200"))  # 200MB


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _mineru_remote_base() -> str:
    return (os.getenv("MINERU_API_BASE") or "https://mineru.net").rstrip("/")


def _mineru_local_base() -> str:
    return (os.getenv("LOCAL_MINERU_API_BASE") or "http://localhost:8080").rstrip("/")


def _running_in_docker() -> bool:
    try:
        return Path("/.dockerenv").exists()
    except Exception:
        return False


def _sanitize_url(raw: str) -> str:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            return raw.split("?", 1)[0].split("#", 1)[0]
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return raw.split("?", 1)[0].split("#", 1)[0]


def _maybe_log(event_type: str, message: str, **kwargs) -> None:
    ctx = get_current_context()
    if ctx is None:
        return
    ctx.log_event(event_type, message, **kwargs)


def _mineru_debug_enabled() -> bool:
    return _bool_env("MINERU_DEBUG", False)


def _connection_hint(*, mode: str, api_base: str) -> str:
    if mode == "local" and _running_in_docker():
        if api_base.startswith("http://localhost") or api_base.startswith("http://127.0.0.1"):
            return (
                "检测到在 Docker 容器内使用本地 MinerU 且 api_base 指向 localhost；"
                "容器内 localhost 指向容器自身。若 MinerU 跑在宿主机，请将 "
                "LOCAL_MINERU_API_BASE 设置为 http://host.docker.internal:8080 "
                "（或将 MinerU 和本服务加入同一 docker network / docker-compose）。"
            )
    if mode == "remote":
        return "请检查容器是否允许访问外网、DNS 解析、代理/防火墙策略，以及 MINERU_API_BASE 是否可达。"
    return ""


def _format_httpx_request_error(err: httpx.RequestError, *, mode: str, api_base: str) -> str:
    request_url = ""
    try:
        if getattr(err, "request", None) is not None and getattr(err.request, "url", None) is not None:
            request_url = _sanitize_url(str(err.request.url))
    except Exception:
        request_url = ""

    parts = [f"MinerU 连接失败（mode={mode}, api_base={api_base}）"]
    if request_url:
        parts.append(f"request_url={request_url}")
    parts.append(f"error_type={err.__class__.__name__}")
    if str(err):
        parts.append(f"error={str(err)}")
    hint = _connection_hint(mode=mode, api_base=api_base)
    if hint:
        parts.append(f"hint={hint}")
    return "; ".join(parts)


async def convert_with_mineru(
    file_path: str,
    enable_ocr: bool = False,
    language: str = "ch",
    work_dir: Optional[Path] = None,
    page_ranges: Optional[str] = None,
) -> Dict[str, Any]:
    """使用 MinerU 将文件转换为 Markdown（remote 或 local）。

    Returns:
        dict: {
          "ok": bool,
          "markdown_text": str,
          "output_dir": str,
          "files": list[str],
          "warnings": list[str],
          "attempt": dict,
          "error_code": str (失败时),
          "error_message": str (失败时)
        }
    """
    start_time = time.time()
    attempt = {
        "engine": "mineru",
        "status": "running",
        "error_code": None,
        "error_message": None,
        "elapsed_ms": 0,
        "timed_out": False,
        "exit_code": None,
        "stderr_tail": None,
    }

    warnings: list[str] = []
    work_dir = Path(work_dir) if work_dir else Path("/tmp")

    api_key = (os.getenv("MINERU_API_KEY") or "").strip()
    use_local = _bool_env("USE_LOCAL_API", False)
    mode = "remote" if api_key else ("local" if use_local else "unconfigured")
    api_base = _mineru_remote_base() if mode == "remote" else (_mineru_local_base() if mode == "local" else "")
    attempt["mode"] = mode
    attempt["api_base"] = api_base
    attempt["api_key_set"] = bool(api_key)
    attempt["use_local_api"] = bool(use_local)

    try:
        _maybe_log(
            "mineru_config",
            "MinerU 配置",
            mode=mode,
            api_base=api_base,
            api_key_set=bool(api_key),
            use_local_api=bool(use_local),
            timeout_s=MINERU_TIMEOUT,
            poll_interval_s=MINERU_POLL_INTERVAL_SECONDS,
            running_in_docker=_running_in_docker(),
        )
        if api_key:
            result = await _convert_remote(
                file_path=Path(file_path),
                api_base=api_base,
                api_key=api_key,
                enable_ocr=enable_ocr,
                language=language,
                page_ranges=page_ranges,
                work_dir=work_dir,
            )
        elif use_local:
            result = await _convert_local(
                file_path=Path(file_path),
                api_base=api_base,
                enable_ocr=enable_ocr,
                language=language,
                page_ranges=page_ranges,
                work_dir=work_dir,
            )
        else:
            attempt["status"] = "error"
            attempt["error_code"] = "E_MINERU_NOT_CONFIGURED"
            attempt["error_message"] = "MinerU 未配置：需要设置 MINERU_API_KEY 或 USE_LOCAL_API=true"
            attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)
            return {
                "ok": False,
                "attempt": attempt,
                "error_code": attempt["error_code"],
                "error_message": attempt["error_message"],
                "warnings": ["请在 .env 中配置 MINERU_API_KEY 或开启 USE_LOCAL_API"],
            }

        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)
        if result.get("ok"):
            attempt["status"] = "success"
            return {**result, "attempt": attempt, "warnings": warnings + result.get("warnings", [])}

        attempt["status"] = "error"
        attempt["error_code"] = result.get("error_code", "E_MINERU_FAILED")
        attempt["error_message"] = result.get("error_message", "MinerU 转换失败")
        return {**result, "attempt": attempt, "warnings": warnings + result.get("warnings", [])}

    except httpx.TimeoutException:
        attempt["status"] = "error"
        attempt["error_code"] = "E_TIMEOUT"
        attempt["error_message"] = f"MinerU 请求超时（mode={mode}, api_base={api_base}, timeout={MINERU_TIMEOUT}秒）"
        attempt["timed_out"] = True
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_TIMEOUT",
            "error_message": attempt["error_message"],
            "warnings": warnings,
        }
    except httpx.HTTPStatusError as e:
        status_code = None
        sanitized_url = ""
        response_preview = ""
        try:
            status_code = e.response.status_code
        except Exception:
            status_code = None
        try:
            sanitized_url = _sanitize_url(str(e.request.url))
        except Exception:
            sanitized_url = ""
        try:
            response_preview = (e.response.text or "")[:300].replace("\n", " ").strip()
        except Exception:
            response_preview = ""

        attempt["status"] = "error"
        attempt["error_code"] = "E_MINERU_API_ERROR"
        attempt["error_message"] = (
            f"MinerU API 返回错误（mode={mode}, api_base={api_base}, status={status_code}, url={sanitized_url}）"
        )
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)
        _maybe_log(
            "warning",
            "MinerU API HTTP 错误",
            mode=mode,
            api_base=api_base,
            status=status_code,
            url=sanitized_url,
            response_preview=response_preview,
        )
        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_MINERU_API_ERROR",
            "error_message": attempt["error_message"] + (f" response={response_preview}" if response_preview else ""),
            "warnings": warnings,
        }
    except httpx.RequestError as e:
        attempt["status"] = "error"
        attempt["error_code"] = "E_MINERU_FAILED"
        attempt["error_message"] = _format_httpx_request_error(e, mode=mode, api_base=api_base)
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)
        _maybe_log(
            "error",
            "MinerU 请求失败",
            mode=mode,
            api_base=api_base,
            error_type=e.__class__.__name__,
            error=str(e),
        )
        if _mineru_debug_enabled():
            cause = getattr(e, "__cause__", None)
            if cause is not None:
                _maybe_log("warning", "MinerU 异常 cause", cause_type=cause.__class__.__name__, cause=str(cause))
        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_MINERU_FAILED",
            "error_message": attempt["error_message"],
            "warnings": warnings,
        }
    except Exception as e:
        attempt["status"] = "error"
        attempt["error_code"] = "E_MINERU_FAILED"
        attempt["error_message"] = str(e)
        attempt["elapsed_ms"] = int((time.time() - start_time) * 1000)
        return {
            "ok": False,
            "attempt": attempt,
            "error_code": "E_MINERU_FAILED",
            "error_message": str(e),
            "warnings": warnings,
        }


async def _convert_remote(
    *,
    file_path: Path,
    api_base: str,
    api_key: str,
    enable_ocr: bool,
    language: str,
    page_ranges: Optional[str],
    work_dir: Path,
) -> Dict[str, Any]:
    """远程 MinerU：上传文件 → 轮询任务 → 下载结果 zip → 安全解压 → 读取 md。"""
    if not file_path.exists():
        return {"ok": False, "error_code": "E_FILE_NOT_FOUND", "error_message": f"文件不存在: {file_path}"}

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    timeout = httpx.Timeout(connect=15, read=MINERU_TIMEOUT, write=60, pool=60)

    async with httpx.AsyncClient(timeout=timeout) as client:
        # 1) 获取上传 URL
        if _mineru_debug_enabled():
            _maybe_log(
                "mineru_http",
                "MinerU 获取上传 URL",
                api_base=api_base,
                endpoint="/api/v4/file-urls/batch",
            )
        payload = {"language": language, "files": [{"name": file_path.name, "is_ocr": enable_ocr}]}
        if page_ranges is not None:
            payload["files"][0]["page_ranges"] = page_ranges

        resp = await client.post(f"{api_base}/api/v4/file-urls/batch", json=payload, headers=headers)
        resp.raise_for_status()
        _maybe_log(
            "mineru_http_response",
            "MinerU 远程响应体",
            status=resp.status_code,
            endpoint="/api/v4/file-urls/batch",
            body=resp.text,
        )
        data = resp.json().get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            return {"ok": False, "error_code": "E_MINERU_FAILED", "error_message": "获取上传 URL 失败（响应缺少 batch_id/file_urls）"}

        upload_url = file_urls[0]

        # 2) PUT 上传（不要设置 Content-Type，让存储服务处理）
        if _mineru_debug_enabled():
            _maybe_log(
                "mineru_http",
                "MinerU 上传文件（PUT 到存储）",
                upload_url=_sanitize_url(upload_url),
            )
        async def _file_iter(p: Path):
            with open(p, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        put_resp = await client.put(upload_url, content=_file_iter(file_path))
        if put_resp.status_code != 200:
            return {
                "ok": False,
                "error_code": "E_MINERU_FAILED",
                "error_message": f"文件上传失败（HTTP {put_resp.status_code}）",
            }

        # 3) 轮询任务状态
        deadline = time.time() + MINERU_TIMEOUT
        full_zip_url: Optional[str] = None
        last_state: Optional[str] = None
        last_err: Optional[str] = None
        last_logged_state: Optional[str] = None

        while time.time() < deadline:
            status_resp = await client.get(f"{api_base}/api/v4/extract-results/batch/{batch_id}", headers=headers)
            status_resp.raise_for_status()
            _maybe_log(
                "mineru_http_response",
                "MinerU 远程响应体",
                status=status_resp.status_code,
                endpoint="/api/v4/extract-results/batch/{batch_id}",
                body=status_resp.text,
            )
            status_data = status_resp.json().get("data") or {}
            extract_result = status_data.get("extract_result") or []

            # 单文件：取第一个匹配 file_name 的结果；找不到就取第一个
            item = None
            for r in extract_result:
                if (r.get("file_name") or "") == file_path.name:
                    item = r
                    break
            if item is None and extract_result:
                item = extract_result[0]

            if item:
                last_state = item.get("state")
                if _mineru_debug_enabled() and last_state and last_state != last_logged_state:
                    _maybe_log("mineru_poll", "MinerU 任务状态", batch_id=batch_id, state=last_state)
                    last_logged_state = last_state
                if last_state == "done":
                    full_zip_url = item.get("full_zip_url") or item.get("zip_url")
                    break
                if last_state in ("failed", "error"):
                    last_err = item.get("err_msg") or "MinerU 处理失败"
                    break

            await _sleep(MINERU_POLL_INTERVAL_SECONDS)

        if last_state in ("failed", "error"):
            return {"ok": False, "error_code": "E_MINERU_FAILED", "error_message": last_err or "MinerU 处理失败"}
        if not full_zip_url:
            return {"ok": False, "error_code": "E_TIMEOUT", "error_message": f"MinerU 任务未在 {MINERU_TIMEOUT} 秒内完成"}

        # 4) 下载结果 zip（流式 + 上限）
        if _mineru_debug_enabled():
            _maybe_log(
                "mineru_http",
                "MinerU 下载结果 zip",
                zip_url=_sanitize_url(full_zip_url),
            )
        out_dir = work_dir / "output" / "mineru" / str(batch_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / "result.zip"

        bytes_written = 0
        async with client.stream("GET", full_zip_url, headers=headers) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=8192):
                    bytes_written += len(chunk)
                    if bytes_written > MINERU_MAX_RESULT_ZIP_BYTES:
                        f.close()
                        zip_path.unlink(missing_ok=True)
                        return {
                            "ok": False,
                            "error_code": "E_INPUT_TOO_LARGE",
                            "error_message": "MinerU 结果 zip 超过大小限制",
                        }
                    f.write(chunk)

        # 5) 安全解压 & 读取 md
        extract_dir = out_dir / "extract"
        extract_result2 = safe_extract_zip(zip_path, extract_dir)
        if not extract_result2.get("ok"):
            zip_path.unlink(missing_ok=True)
            return {
                "ok": False,
                "error_code": extract_result2.get("error_code", "E_ZIP_EXTRACT_FAILED"),
                "error_message": extract_result2.get("error_message", "ZIP 解压失败"),
                "warnings": [],
            }

        md_files = sorted(extract_dir.rglob("*.md"))
        markdown_text = ""
        if md_files:
            markdown_text = md_files[0].read_text(encoding="utf-8", errors="ignore")

        zip_path.unlink(missing_ok=True)
        files = [str(p.relative_to(extract_dir)) for p in extract_dir.rglob("*") if p.is_file()]
        return {
            "ok": True,
            "markdown_text": markdown_text,
            "output_dir": str(extract_dir),
            "files": files,
            "warnings": [],
        }


async def _convert_local(
    *,
    file_path: Path,
    api_base: str,
    enable_ocr: bool,
    language: str,
    page_ranges: Optional[str],
    work_dir: Path,
) -> Dict[str, Any]:
    """本地 MinerU：尝试调用 /file_parse（best-effort）。

    说明：不同本地部署的 MinerU API 返回格式可能不同，这里做“尽力解析”。
    """
    if not file_path.exists():
        return {"ok": False, "error_code": "E_FILE_NOT_FOUND", "error_message": f"文件不存在: {file_path}"}

    timeout = httpx.Timeout(connect=10, read=MINERU_TIMEOUT, write=60, pool=60)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if _mineru_debug_enabled():
            _maybe_log("mineru_http", "MinerU 本地调用 /file_parse", api_base=api_base, endpoint="/file_parse")
        files = {"files": (file_path.name, file_path.read_bytes(), "application/octet-stream")}
        data = {"parse_method": "auto", "language": language}
        if enable_ocr:
            data["enable_ocr"] = "true"
        if page_ranges is not None:
            data["page_ranges"] = page_ranges

        resp = await client.post(f"{api_base}/file_parse", files=files, data=data)
        resp.raise_for_status()
        _maybe_log(
            "mineru_http_response",
            "MinerU 本地响应体",
            status=resp.status_code,
            body=resp.text,
        )

        # 尝试解析 JSON
        try:
            payload = resp.json()
        except Exception:
            return {
                "ok": False,
                "error_code": "E_MINERU_FAILED",
                "error_message": "本地 MinerU 返回非 JSON，无法解析",
            }

        # 常见字段：content/markdown/result_path/extract_dir/extract_path
        markdown_text = payload.get("content") or payload.get("markdown") or ""
        extract_path = payload.get("extract_path") or payload.get("extract_dir") or payload.get("result_path") or ""

        if extract_path:
            extract_dir = Path(extract_path)
            md_files = sorted(extract_dir.rglob("*.md")) if extract_dir.exists() else []
            if md_files:
                markdown_text = markdown_text or md_files[0].read_text(encoding="utf-8", errors="ignore")
            files_list = [str(p.relative_to(extract_dir)) for p in extract_dir.rglob("*") if p.is_file()] if extract_dir.exists() else []
            return {
                "ok": True,
                "markdown_text": markdown_text,
                "output_dir": str(extract_dir),
                "files": files_list,
                "warnings": ["本地 MinerU 模式为 best-effort，输出结构可能因部署不同而变化"],
            }

        if markdown_text:
            out_dir = work_dir / "output" / "mineru_local"
            out_dir.mkdir(parents=True, exist_ok=True)
            return {
                "ok": True,
                "markdown_text": markdown_text,
                "output_dir": str(out_dir),
                "files": [],
                "warnings": ["本地 MinerU 直接返回 markdown_text，未提供 extract_dir"],
            }

        return {
            "ok": False,
            "error_code": "E_MINERU_FAILED",
            "error_message": "本地 MinerU 返回格式无法识别（缺少 content/markdown/result_path）",
        }


async def _sleep(seconds: int) -> None:
    # 单独封装，避免未来替换为 asyncio.sleep 时到处改
    import asyncio
    await asyncio.sleep(max(0, int(seconds)))


def is_mineru_available() -> bool:
    """检查 MinerU 是否可用（只检查配置，不做网络探测）。"""
    if (os.getenv("MINERU_API_KEY") or "").strip():
        return True
    if _bool_env("USE_LOCAL_API", False):
        return True
    return False
