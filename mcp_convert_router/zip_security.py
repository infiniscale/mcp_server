"""ZIP 安全检查模块 - 防止 zip bomb 等 DoS 攻击。

对 ZIP 容器（包括 docx/xlsx/pptx 等 OOXML 格式）进行安全检查。
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional
import shutil

# 安全限制默认值
DEFAULT_MAX_ENTRIES = 2000  # 最大条目数
DEFAULT_MAX_TOTAL_SIZE = 200 * 1024 * 1024  # 最大解压后总大小 (200MB)
DEFAULT_MAX_ENTRY_SIZE = 50 * 1024 * 1024  # 单个条目最大大小 (50MB)
DEFAULT_MAX_COMPRESSION_RATIO = 100  # 最大压缩比（超过此值可能是 zip bomb）


@dataclass
class ZipSecurityConfig:
    """ZIP 安全检查配置。"""
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_total_size: int = DEFAULT_MAX_TOTAL_SIZE
    max_entry_size: int = DEFAULT_MAX_ENTRY_SIZE
    max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO


@dataclass
class ZipSecurityResult:
    """ZIP 安全检查结果。"""
    safe: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None


def check_zip_security(
    file_path: Path,
    config: Optional[ZipSecurityConfig] = None
) -> ZipSecurityResult:
    """
    检查 ZIP 文件的安全性。

    只读取 ZIP 目录信息，不进行解压操作。

    Args:
        file_path: ZIP 文件路径
        config: 安全配置（可选，使用默认值）

    Returns:
        ZipSecurityResult: 检查结果
    """
    if config is None:
        config = ZipSecurityConfig()

    file_path = Path(file_path)

    if not file_path.exists():
        return ZipSecurityResult(
            safe=False,
            error_code="E_FILE_NOT_FOUND",
            error_message=f"文件不存在: {file_path}"
        )

    # 获取压缩文件大小
    compressed_size = file_path.stat().st_size

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # 获取所有条目信息（只读取目录，不解压）
            info_list = zf.infolist()

            # 统计信息
            entry_count = len(info_list)
            total_uncompressed_size = 0
            max_entry_uncompressed = 0
            suspicious_entries: List[str] = []

            for info in info_list:
                # 累计解压后总大小
                total_uncompressed_size += info.file_size

                # 记录最大的单个条目
                if info.file_size > max_entry_uncompressed:
                    max_entry_uncompressed = info.file_size

                # 检查单个条目是否超限
                if info.file_size > config.max_entry_size:
                    suspicious_entries.append(
                        f"{info.filename} ({info.file_size / 1024 / 1024:.2f}MB)"
                    )

                # 检查压缩比（防止 zip bomb）
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > config.max_compression_ratio:
                        return ZipSecurityResult(
                            safe=False,
                            error_code="E_ZIP_BOMB_DETECTED",
                            error_message=(
                                f"检测到可疑压缩比: 条目 '{info.filename}' "
                                f"压缩比为 {ratio:.1f}:1，超过限制 {config.max_compression_ratio}:1。"
                                f"可能是 zip bomb 攻击。"
                            ),
                            stats={
                                "entry_count": entry_count,
                                "suspicious_entry": info.filename,
                                "compression_ratio": ratio
                            }
                        )

            # 检查条目数量
            if entry_count > config.max_entries:
                return ZipSecurityResult(
                    safe=False,
                    error_code="E_ZIP_TOO_MANY_ENTRIES",
                    error_message=(
                        f"ZIP 文件条目数过多: {entry_count} 个，"
                        f"超过限制 {config.max_entries} 个。"
                    ),
                    stats={
                        "entry_count": entry_count,
                        "max_entries": config.max_entries
                    }
                )

            # 检查解压后总大小
            if total_uncompressed_size > config.max_total_size:
                return ZipSecurityResult(
                    safe=False,
                    error_code="E_ZIP_TOO_LARGE",
                    error_message=(
                        f"ZIP 解压后总大小过大: {total_uncompressed_size / 1024 / 1024:.2f}MB，"
                        f"超过限制 {config.max_total_size / 1024 / 1024:.2f}MB。"
                    ),
                    stats={
                        "entry_count": entry_count,
                        "total_uncompressed_size": total_uncompressed_size,
                        "max_total_size": config.max_total_size
                    }
                )

            # 检查是否有超大单个条目
            if suspicious_entries:
                return ZipSecurityResult(
                    safe=False,
                    error_code="E_ZIP_ENTRY_TOO_LARGE",
                    error_message=(
                        f"ZIP 包含过大的条目: {', '.join(suspicious_entries[:3])}。"
                        f"单个条目限制为 {config.max_entry_size / 1024 / 1024:.2f}MB。"
                    ),
                    stats={
                        "entry_count": entry_count,
                        "suspicious_entries": suspicious_entries[:10],
                        "max_entry_size": config.max_entry_size
                    }
                )

            # 计算整体压缩比
            overall_ratio = (
                total_uncompressed_size / compressed_size
                if compressed_size > 0 else 0
            )

            # 检查整体压缩比
            if overall_ratio > config.max_compression_ratio:
                return ZipSecurityResult(
                    safe=False,
                    error_code="E_ZIP_BOMB_DETECTED",
                    error_message=(
                        f"检测到可疑整体压缩比: {overall_ratio:.1f}:1，"
                        f"超过限制 {config.max_compression_ratio}:1。"
                        f"可能是 zip bomb 攻击。"
                    ),
                    stats={
                        "entry_count": entry_count,
                        "compressed_size": compressed_size,
                        "total_uncompressed_size": total_uncompressed_size,
                        "compression_ratio": overall_ratio
                    }
                )

            # 所有检查通过
            return ZipSecurityResult(
                safe=True,
                stats={
                    "entry_count": entry_count,
                    "compressed_size": compressed_size,
                    "total_uncompressed_size": total_uncompressed_size,
                    "max_entry_size": max_entry_uncompressed,
                    "compression_ratio": overall_ratio
                }
            )

    except zipfile.BadZipFile:
        return ZipSecurityResult(
            safe=False,
            error_code="E_ZIP_INVALID",
            error_message="无效的 ZIP 文件格式"
        )
    except Exception as e:
        return ZipSecurityResult(
            safe=False,
            error_code="E_ZIP_CHECK_FAILED",
            error_message=f"ZIP 安全检查失败: {str(e)}"
        )


def is_zip_file(file_path: Path) -> bool:
    """检查文件是否是 ZIP 格式（包括 docx/xlsx/pptx 等）。"""
    try:
        with open(file_path, "rb") as f:
            header = f.read(4)
            return header == b"PK\x03\x04"
    except Exception:
        return False


def safe_extract_zip(
    zip_path: Path,
    dest_dir: Path,
    config: Optional[ZipSecurityConfig] = None,
) -> Dict[str, Any]:
    """安全解压 ZIP（防 zip slip + 复用 zip bomb 限制）。

    Returns:
        dict: {
          "ok": bool,
          "dest_dir": str,
          "files": list[str],
          "error_code": str | None,
          "error_message": str | None,
          "security_stats": dict | None
        }
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    security = check_zip_security(zip_path, config)
    if not security.safe:
        return {
            "ok": False,
            "dest_dir": str(dest_dir),
            "files": [],
            "error_code": security.error_code,
            "error_message": security.error_message,
            "security_stats": security.stats,
        }

    extracted_files: List[str] = []
    dest_root = dest_dir.resolve()

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename

                # 基础拒绝：绝对路径 / Windows 盘符 / 目录穿越
                if not name or name.startswith(("/", "\\")) or ":" in Path(name).drive:
                    return {
                        "ok": False,
                        "dest_dir": str(dest_dir),
                        "files": extracted_files,
                        "error_code": "E_ZIP_PATH_TRAVERSAL",
                        "error_message": f"ZIP 条目路径非法: {name}",
                        "security_stats": security.stats,
                    }

                target_path = (dest_dir / name).resolve()
                if not str(target_path).startswith(str(dest_root)):
                    return {
                        "ok": False,
                        "dest_dir": str(dest_dir),
                        "files": extracted_files,
                        "error_code": "E_ZIP_PATH_TRAVERSAL",
                        "error_message": f"ZIP 条目尝试写出目标目录: {name}",
                        "security_stats": security.stats,
                    }

                # 目录
                if name.endswith("/"):
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)

                # 解压文件（流式拷贝）
                with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)

                extracted_files.append(str(target_path.relative_to(dest_dir)))

        return {
            "ok": True,
            "dest_dir": str(dest_dir),
            "files": extracted_files,
            "error_code": None,
            "error_message": None,
            "security_stats": security.stats,
        }

    except zipfile.BadZipFile:
        return {
            "ok": False,
            "dest_dir": str(dest_dir),
            "files": extracted_files,
            "error_code": "E_ZIP_INVALID",
            "error_message": "无效的 ZIP 文件格式",
            "security_stats": security.stats,
        }
    except Exception as e:
        return {
            "ok": False,
            "dest_dir": str(dest_dir),
            "files": extracted_files,
            "error_code": "E_ZIP_EXTRACT_FAILED",
            "error_message": str(e),
            "security_stats": security.stats,
        }
