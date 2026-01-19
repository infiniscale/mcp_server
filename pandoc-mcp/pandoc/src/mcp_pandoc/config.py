"""Pandoc MCP configuration management module.

This module provides centralized configuration management with support for:
- Environment variables
- .env file loading
- Default values
- Security settings (file size limits, path validation)
- Logging configuration
"""

import logging
import os
from pathlib import Path
from typing import Optional

# Try to load dotenv, but don't fail if not available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# === Basic Configuration ===
DEFAULT_OUTPUT_DIR = os.getenv("PANDOC_OUTPUT_DIR", "./output")
TEMP_DIR = os.getenv("PANDOC_TEMP_DIR", "./temp")

# Pandoc executable path
PANDOC_PATH = os.getenv("PANDOC_PATH", "pandoc")
PANDOC_DATA_DIR = os.getenv("PANDOC_DATA_DIR", "")


def configure_pandoc(log: Optional[logging.Logger] = None):
    """Configure pypandoc to use custom pandoc path.

    This should be called early in the application startup.

    Args:
        log: Optional logger for status messages
    """
    if PANDOC_PATH and PANDOC_PATH != "pandoc":
        # Set environment variable for pypandoc
        os.environ["PYPANDOC_PANDOC"] = PANDOC_PATH
        if log:
            log.info(f"Configured custom pandoc path: {PANDOC_PATH}")

    if PANDOC_DATA_DIR:
        os.environ["PANDOC_DATA_DIR"] = PANDOC_DATA_DIR
        if log:
            log.info(f"Configured pandoc data dir: {PANDOC_DATA_DIR}")


# === Security Configuration - File Size Limits ===
# Default: 50MB for uploads, 100MB for local files
MAX_UPLOAD_BYTES = int(os.getenv("PANDOC_MCP_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MAX_FILE_BYTES = int(os.getenv("PANDOC_MCP_MAX_FILE_BYTES", str(100 * 1024 * 1024)))

# Batch upload limits
MAX_UPLOAD_FILES = int(os.getenv("PANDOC_MCP_MAX_UPLOAD_FILES", "10"))
MAX_TOTAL_UPLOAD_BYTES = int(os.getenv("PANDOC_MCP_MAX_TOTAL_UPLOAD_BYTES", str(100 * 1024 * 1024)))


# === Security Configuration - Path Access Control ===
# Disable local path input entirely (for public deployments)
MCP_DISABLE_PATH_INPUT = os.getenv(
    "PANDOC_MCP_DISABLE_PATH_INPUT", ""
).lower() in ["true", "1", "yes"]

# Disable filters when path input is disabled (security measure)
MCP_DISABLE_FILTERS = os.getenv(
    "PANDOC_MCP_DISABLE_FILTERS", ""
).lower() in ["true", "1", "yes"]

# Require paths to be in allowlist
MCP_REQUIRE_PATH_ALLOWLIST = os.getenv(
    "PANDOC_MCP_REQUIRE_ALLOWLIST", ""
).lower() in ["true", "1", "yes"]

# Restrict output to output directory only
MCP_RESTRICT_OUTPUT_DIR = os.getenv(
    "PANDOC_MCP_RESTRICT_OUTPUT_DIR", ""
).lower() in ["true", "1", "yes"]


def _parse_allowed_roots(value: str) -> list[Path]:
    """Parse allowed root directories from environment variable.

    Supports both comma-separated and path-separator (: or ;) separated values.

    Args:
        value: String containing directory paths

    Returns:
        List of Path objects for allowed directories
    """
    if not value:
        return []

    roots: list[Path] = []
    # Support both comma and os.pathsep as separators
    for chunk in value.split(os.pathsep):
        for item in chunk.split(","):
            item = item.strip()
            if item:
                roots.append(Path(item).expanduser())
    return roots


MCP_ALLOWED_INPUT_ROOTS = _parse_allowed_roots(
    os.getenv("PANDOC_MCP_ALLOWED_INPUT_ROOTS", "")
)

MCP_ALLOWED_OUTPUT_ROOTS = _parse_allowed_roots(
    os.getenv("PANDOC_MCP_ALLOWED_OUTPUT_ROOTS", "")
)


# === HTTP/CORS Configuration ===
def _parse_cors_origins(value: str) -> list[str]:
    """Parse allowed CORS origins from environment variable."""
    value = value.strip()
    if not value:
        return []
    if value == "*":
        return ["*"]
    return [item.strip() for item in value.split(",") if item.strip()]


CORS_ALLOW_ORIGINS = _parse_cors_origins(
    os.getenv("PANDOC_MCP_CORS_ALLOW_ORIGINS", "")
)


# === MinIO Configuration ===
MINIO_ENABLED = os.getenv("PANDOC_MINIO_ENABLED", "").lower() in ["true", "1", "yes"]
MINIO_ENDPOINT = os.getenv("PANDOC_MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("PANDOC_MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("PANDOC_MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("PANDOC_MINIO_BUCKET", "pandoc-conversions")
MINIO_SECURE = os.getenv("PANDOC_MINIO_SECURE", "false").lower() in ["true", "1", "yes"]
MINIO_URL_EXPIRY = int(os.getenv("PANDOC_MINIO_URL_EXPIRY", str(7 * 24 * 3600)))


# === Logging Configuration ===
LOG_LEVEL = os.getenv("PANDOC_LOG_LEVEL", "INFO").upper()
DEBUG_MODE = os.getenv("PANDOC_DEBUG", "").lower() in ["true", "1", "yes"]


def setup_logging() -> logging.Logger:
    """Set up logging configuration.

    Returns:
        Configured logger instance for pandoc module
    """
    level = LOG_LEVEL
    if DEBUG_MODE:
        level = "DEBUG"

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    return logging.getLogger("pandoc")


# Initialize logger
logger = setup_logging()

# Configure pandoc path
configure_pandoc(logger)


def ensure_output_dir(output_dir: Optional[str] = None) -> Path:
    """Ensure output directory exists and return its path.

    Args:
        output_dir: Optional directory path. Uses DEFAULT_OUTPUT_DIR if not provided.

    Returns:
        Path object for the output directory
    """
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def ensure_temp_dir() -> Path:
    """Ensure temporary directory exists and return its path.

    Returns:
        Path object for the temporary directory
    """
    temp_path = Path(TEMP_DIR)
    temp_path.mkdir(parents=True, exist_ok=True)
    return temp_path


def is_path_allowed(path: Path, allowed_roots: Optional[list[Path]] = None) -> bool:
    """Check if a path is in the allowed directories list.

    Args:
        path: Path to check
        allowed_roots: Optional custom list of allowed roots (defaults to input roots)

    Returns:
        True if path is allowed, False otherwise
    """
    roots = allowed_roots if allowed_roots is not None else MCP_ALLOWED_INPUT_ROOTS

    if not roots:
        # If no allowlist configured, check if allowlist is required
        return not MCP_REQUIRE_PATH_ALLOWLIST

    try:
        resolved_path = path.resolve()
    except (OSError, ValueError):
        return False

    for root in roots:
        try:
            resolved_root = root.expanduser().resolve()
            if resolved_path.is_relative_to(resolved_root):
                return True
        except (OSError, ValueError):
            continue

    return False


def validate_local_path(path: Path, check_exists: bool = True) -> Optional[str]:
    """Validate a local file path for read access.

    Checks:
    - Path input is not disabled
    - Path is in allowlist (if required)
    - File size is within limits (if exists)

    Args:
        path: Path to validate
        check_exists: Whether to check if file exists and validate size

    Returns:
        Error message string if validation fails, None if validation passes
    """
    # Check if path input is disabled
    if MCP_DISABLE_PATH_INPUT:
        return "Local path input is disabled for this service"

    # Check if allowlist is required but not configured
    if MCP_REQUIRE_PATH_ALLOWLIST and not MCP_ALLOWED_INPUT_ROOTS:
        return "Path allowlist is required but not configured"

    # Check if path is in allowlist
    if MCP_REQUIRE_PATH_ALLOWLIST and not is_path_allowed(path):
        return "File path is not in allowed directories"

    # Check file size if exists
    if check_exists and MAX_FILE_BYTES > 0:
        try:
            if path.exists():
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    return f"File too large: {size} bytes, limit is {MAX_FILE_BYTES} bytes"
        except (OSError, ValueError) as e:
            return f"Cannot read file size: {str(e)}"

    return None  # Validation passed


def validate_output_path(path: Path) -> Optional[str]:
    """Validate a local file path for write access.

    Checks:
    - Path input is not disabled
    - Path is in output allowlist (if required)
    - Path is within output directory (if restricted)

    Args:
        path: Path to validate

    Returns:
        Error message string if validation fails, None if validation passes
    """
    # Check if path input is disabled
    if MCP_DISABLE_PATH_INPUT:
        return "Local path input is disabled for this service"

    # Check output directory restriction
    if MCP_RESTRICT_OUTPUT_DIR:
        try:
            output_dir = Path(DEFAULT_OUTPUT_DIR).resolve()
            resolved_path = path.resolve()
            if not resolved_path.is_relative_to(output_dir):
                return f"Output path must be within output directory: {DEFAULT_OUTPUT_DIR}"
        except (OSError, ValueError) as e:
            return f"Cannot resolve output path: {str(e)}"

    # Check if output path is in allowlist (if configured)
    if MCP_ALLOWED_OUTPUT_ROOTS:
        if not is_path_allowed(path, MCP_ALLOWED_OUTPUT_ROOTS):
            return "Output path is not in allowed directories"

    return None  # Validation passed


def validate_filter_path(path: Path) -> Optional[str]:
    """Validate a filter file path.

    Checks:
    - Filters are not disabled
    - Filter path is in allowlist (if required)
    - Filter file exists and is executable

    Args:
        path: Path to validate

    Returns:
        Error message string if validation fails, None if validation passes
    """
    # Check if filters are disabled
    if MCP_DISABLE_FILTERS or MCP_DISABLE_PATH_INPUT:
        return "Filters are disabled for this service"

    # Check if path is in allowlist (use input roots for filters)
    if MCP_REQUIRE_PATH_ALLOWLIST and not is_path_allowed(path):
        return "Filter path is not in allowed directories"

    # Check if filter exists
    if not path.exists():
        return f"Filter not found: {path}"

    # Check if filter is executable
    if not os.access(path, os.X_OK):
        return f"Filter is not executable: {path}"

    return None  # Validation passed


def get_config_summary() -> dict:
    """Get a summary of current configuration settings.

    Returns:
        Dictionary containing current configuration values
    """
    return {
        "output_dir": DEFAULT_OUTPUT_DIR,
        "temp_dir": TEMP_DIR,
        "pandoc_path": PANDOC_PATH,
        "minio_enabled": MINIO_ENABLED,
        "minio_endpoint": MINIO_ENDPOINT,
        "minio_bucket": MINIO_BUCKET,
        "minio_secure": MINIO_SECURE,
        "minio_url_expiry": MINIO_URL_EXPIRY,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "max_file_bytes": MAX_FILE_BYTES,
        "max_upload_files": MAX_UPLOAD_FILES,
        "max_total_upload_bytes": MAX_TOTAL_UPLOAD_BYTES,
        "disable_path_input": MCP_DISABLE_PATH_INPUT,
        "disable_filters": MCP_DISABLE_FILTERS,
        "require_path_allowlist": MCP_REQUIRE_PATH_ALLOWLIST,
        "restrict_output_dir": MCP_RESTRICT_OUTPUT_DIR,
        "allowed_input_roots": [str(p) for p in MCP_ALLOWED_INPUT_ROOTS],
        "allowed_output_roots": [str(p) for p in MCP_ALLOWED_OUTPUT_ROOTS],
        "cors_allow_origins": CORS_ALLOW_ORIGINS,
        "log_level": LOG_LEVEL,
        "debug_mode": DEBUG_MODE,
    }
