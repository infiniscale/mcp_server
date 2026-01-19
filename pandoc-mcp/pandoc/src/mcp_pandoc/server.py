"""mcp-pandoc server module.

Enhanced version with support for:
- Original stdio mode
- HTTP modes (sse, streamable-http)
- Base64 file upload for remote scenarios
- Security features (file size limits, path validation)
"""

import base64
import binascii
import io
import json
import os
import re
import secrets
import shutil
import zipfile
from pathlib import Path
from typing import Any, Optional

import mcp.server.stdio
import mcp.types as types
import pypandoc
import yaml
from mcp.server import NotificationOptions, Server
from mcp.server.lowlevel.server import request_ctx
from mcp.server.models import InitializationOptions

from . import config
from . import storage

# Initialize server
server = Server("mcp-pandoc")

# Global output directory (can be set via CLI)
_output_dir: str = config.DEFAULT_OUTPUT_DIR

# Format mapping for Pandoc
FORMAT_ALIASES = {
    "txt": "plain",  # Pandoc uses 'plain' for plain text output
}

INPUT_FORMAT_ALIASES = {
    "txt": "markdown",  # Treat txt as markdown for input
    "tex": "latex",
}

# MIME types for output formats
MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "epub": "application/epub+zip",
    "odt": "application/vnd.oasis.opendocument.text",
    "ipynb": "application/x-ipynb+json",
}

# Binary formats that should be returned as base64
# Note: ipynb is JSON text, not binary
BINARY_FORMATS = {"pdf", "docx", "epub", "odt"}

MIME_TO_INPUT_FORMAT = {
    "text/markdown": "markdown",
    "text/plain": "txt",
    "text/html": "html",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/epub+zip": "epub",
    "application/x-tex": "latex",
    "application/x-ipynb+json": "ipynb",
}

EXTENSION_TO_INPUT_FORMAT = {
    "md": "markdown",
    "markdown": "markdown",
    "html": "html",
    "htm": "html",
    "txt": "txt",
    "rst": "rst",
    "tex": "latex",
    "docx": "docx",
    "odt": "odt",
    "epub": "epub",
    "ipynb": "ipynb",
    "pdf": "pdf",
}


def set_output_dir(dir_path: str) -> str:
    """Set the output directory for converted files.

    Args:
        dir_path: Path to the output directory

    Returns:
        The configured output directory path
    """
    global _output_dir
    _output_dir = dir_path
    config.ensure_output_dir(_output_dir)
    return _output_dir


def get_output_dir() -> str:
    """Get the current output directory.

    Returns:
        Current output directory path
    """
    return _output_dir


# === Security Utility Functions ===


def _decode_base64_payload(base64_payload: str) -> bytes:
    """Decode base64 content, supporting data URL prefix.

    Args:
        base64_payload: Base64 encoded string, optionally with data URL prefix

    Returns:
        Decoded bytes

    Raises:
        ValueError: If decoding fails or payload is empty
    """
    if not base64_payload:
        raise ValueError("content_base64 is empty")

    payload = base64_payload.strip()

    # Check again after stripping whitespace
    if not payload:
        raise ValueError("content_base64 is empty")

    # Remove data URL prefix if present (e.g., data:application/pdf;base64,)
    if payload.startswith("data:") and "base64," in payload:
        payload = payload.split("base64,", 1)[1]

    # Remove all whitespace characters
    payload = re.sub(r"\s+", "", payload)

    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"Base64 decode failed: {str(e)}") from e


def _encode_base64(data: bytes) -> str:
    """Encode bytes to base64 string.

    Args:
        data: Bytes to encode

    Returns:
        Base64 encoded string
    """
    return base64.b64encode(data).decode("ascii")


def _sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal attacks.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename safe for use
    """
    # Extract only the filename part, remove any path components
    name = Path(filename or "").name
    if not name:
        return "upload.bin"

    # Replace dangerous characters: whitespace, comma, semicolon, pipe, etc.
    name = re.sub(r"[\s,;|&$<>()]+", "_", name)
    name = name.strip("_.")

    # Prevent hidden files
    if name.startswith("."):
        name = "file_" + name

    return name or "upload.bin"


def _estimate_base64_decoded_size(base64_payload: str) -> int:
    """Estimate decoded size without actually decoding.

    Args:
        base64_payload: Base64 encoded string

    Returns:
        Estimated decoded size in bytes
    """
    if not base64_payload:
        return 0

    payload = base64_payload.strip()
    if payload.startswith("data:") and "base64," in payload:
        payload = payload.split("base64,", 1)[1]

    payload = re.sub(r"\s+", "", payload)
    padding = payload.count("=")

    return max(0, (len(payload) * 3) // 4 - padding)


def _build_results_response(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build unified results response format.

    Args:
        results: List of individual file processing results

    Returns:
        Unified response dictionary
    """
    if not results:
        return {"status": "error", "error": "No files processed"}

    success_count = len([r for r in results if r.get("status") == "success"])
    error_count = len([r for r in results if r.get("status") == "error"])
    total_count = len(results)

    # Single file case: maintain backward compatibility
    if total_count == 1:
        result = results[0].copy()
        return result

    # Multiple files case
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


def _get_pandoc_format(format_name: str, is_input: bool = False) -> str:
    """Get the Pandoc format name for a given format.

    Args:
        format_name: User-provided format name
        is_input: Whether this is an input format

    Returns:
        Pandoc-compatible format name
    """
    format_lower = format_name.lower()
    if is_input:
        return INPUT_FORMAT_ALIASES.get(format_lower, format_lower)
    return FORMAT_ALIASES.get(format_lower, format_lower)


def _infer_format_from_bytes(data: bytes) -> Optional[str]:
    """Infer input format from file signature when extension/MIME is unavailable."""
    if not data:
        return None

    header = data[:8]
    if header.startswith(b"%PDF-"):
        return "pdf"

    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                if "word/document.xml" in names:
                    return "docx"

                if "mimetype" in names:
                    mimetype = archive.read("mimetype").decode("utf-8", "ignore").strip()
                    if mimetype == "application/epub+zip":
                        return "epub"
                    if mimetype == "application/vnd.oasis.opendocument.text":
                        return "odt"
        except zipfile.BadZipFile:
            return None

    snippet = data.lstrip()[:4096]
    if snippet.startswith(b"{") and b"\"cells\"" in snippet:
        return "ipynb"

    return None


def _infer_input_format(
    provided: Optional[str],
    filename: Optional[str],
    mime_type: Optional[str],
    data: Optional[bytes] = None,
) -> str:
    """Infer input format using explicit value, MIME, magic bytes, then extension."""
    if provided:
        return provided.lower()

    if mime_type:
        format_from_mime = MIME_TO_INPUT_FORMAT.get(mime_type.lower())
        if format_from_mime:
            return format_from_mime

    if data:
        magic_format = _infer_format_from_bytes(data)
        if magic_format:
            return magic_format

    if filename:
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext:
            return EXTENSION_TO_INPUT_FORMAT.get(ext, ext)

    return "markdown"


def _ensure_accept_header(scope: dict) -> dict:
    """Ensure Accept header satisfies streamable-http expectations."""
    method = (scope.get("method") or "").upper()
    desired = b"text/event-stream" if method == "GET" else b"application/json"
    headers = list(scope.get("headers") or [])
    updated_headers = []
    accept_found = False

    for key, value in headers:
        if key.lower() == b"accept":
            updated_headers.append((key, desired))
            accept_found = True
        else:
            updated_headers.append((key, value))

    if not accept_found:
        updated_headers.append((b"accept", desired))

    new_scope = dict(scope)
    new_scope["headers"] = updated_headers
    return new_scope


def _normalize_mcp_headers(scope: dict, session_manager: Any) -> dict:
    """Normalize streamable-http headers to tolerate stale session ids."""
    from mcp.server.streamable_http import MCP_SESSION_ID_HEADER

    scope = _ensure_accept_header(scope)
    headers = list(scope.get("headers") or [])
    normalized_headers = []
    session_key = MCP_SESSION_ID_HEADER.encode("utf-8")

    for key, value in headers:
        if key.lower() == session_key:
            try:
                session_id = value.decode("utf-8")
            except Exception:
                session_id = ""

            if session_id and session_id in getattr(session_manager, "_server_instances", {}):
                normalized_headers.append((key, value))
            # Drop invalid or empty session ids to allow new session creation
            continue

        normalized_headers.append((key, value))

    new_scope = dict(scope)
    new_scope["headers"] = normalized_headers
    return new_scope


# === Filter and Path Resolution Functions ===


def _resolve_filter_path(filter_path: str, defaults_file: Optional[str] = None) -> Optional[str]:
    """Resolve a filter path by trying multiple possible locations.

    Args:
        filter_path: The original filter path (absolute or relative)
        defaults_file: Optional path to the defaults file for context

    Returns:
        Resolved absolute path to the filter if found, or None if not found
    """
    # If it's already an absolute path, just use it
    if os.path.isabs(filter_path):
        paths = [filter_path]
    else:
        # Try multiple locations for relative paths
        paths = [
            # 1. Relative to current working directory
            os.path.abspath(filter_path),
            # 2. Relative to the defaults file directory (if provided)
            os.path.join(os.path.dirname(os.path.abspath(defaults_file)), filter_path) if defaults_file else None,
            # 3. Relative to the .pandoc/filters directory
            os.path.join(os.path.expanduser("~"), ".pandoc", "filters", os.path.basename(filter_path))
        ]
        # Remove None entries
        paths = [p for p in paths if p]

    # Try each path
    for path in paths:
        if os.path.exists(path):
            config.logger.debug(f"Found filter at: {path}")
            return path

    return None


def _validate_filters(filters: list[str], defaults_file: Optional[str] = None) -> list[str]:
    """Validate filter paths and ensure they exist and are executable.

    Args:
        filters: List of filter paths
        defaults_file: Optional defaults file path for context

    Returns:
        List of validated, resolved filter paths

    Raises:
        ValueError: If any filter is not found or fails validation
    """
    validated_filters = []

    for filter_path in filters:
        resolved_path = _resolve_filter_path(filter_path, defaults_file)
        if not resolved_path:
            raise ValueError(f"Filter not found in any of the searched locations: {filter_path}")

        # Validate the filter path using config validation
        validation_error = config.validate_filter_path(Path(resolved_path))
        if validation_error:
            raise ValueError(f"Filter validation failed for {filter_path}: {validation_error}")

        validated_filters.append(resolved_path)

    return validated_filters


def _format_result_info(
    filters: Optional[list[str]] = None,
    defaults_file: Optional[str] = None,
    validated_filters: Optional[list[str]] = None
) -> tuple[str, str]:
    """Format filter and defaults file information for result messages.

    Args:
        filters: Original filter list
        defaults_file: Defaults file path
        validated_filters: Resolved filter paths

    Returns:
        Tuple of (filter_info, defaults_info) strings
    """
    filter_info = ""
    defaults_info = ""

    if filters and validated_filters:
        filter_names = [os.path.basename(f) for f in validated_filters]
        filter_info = f" with filters: {', '.join(filter_names)}"

    if defaults_file:
        defaults_basename = os.path.basename(defaults_file)
        defaults_info = f" using defaults file: {defaults_basename}"

    return filter_info, defaults_info


# === Core Conversion Function ===


async def _convert_with_pandoc(
    contents: Optional[str] = None,
    input_file: Optional[str] = None,
    output_file: Optional[str] = None,
    output_format: str = "markdown",
    input_format: str = "markdown",
    reference_doc: Optional[str] = None,
    filters: Optional[list[str]] = None,
    defaults_file: Optional[str] = None,
    skip_path_validation: bool = False,
) -> dict[str, Any]:
    """Core conversion function using Pandoc.

    Args:
        contents: Content string to convert (if no input_file)
        input_file: Path to input file
        output_file: Path to output file (required for some formats)
        output_format: Target format
        input_format: Source format
        reference_doc: Reference document for styling (docx only)
        filters: List of Pandoc filters to apply
        defaults_file: Pandoc defaults file path
        skip_path_validation: Skip path validation (for internal use with temp files)

    Returns:
        Dictionary with conversion result
    """
    filters = filters or []

    # Validate input parameters
    if not contents and not input_file:
        raise ValueError("Either 'contents' or 'input_file' must be provided")

    # Validate paths unless skipped (for internal temp file operations)
    if not skip_path_validation:
        # Validate input file path
        if input_file:
            validation_error = config.validate_local_path(Path(input_file))
            if validation_error:
                raise ValueError(f"Input file access denied: {validation_error}")

        # Validate output file path
        if output_file:
            validation_error = config.validate_output_path(Path(output_file))
            if validation_error:
                raise ValueError(f"Output file access denied: {validation_error}")

        # Validate reference document path
        if reference_doc:
            validation_error = config.validate_local_path(Path(reference_doc))
            if validation_error:
                raise ValueError(f"Reference document access denied: {validation_error}")

        # Validate defaults file path
        if defaults_file:
            validation_error = config.validate_local_path(Path(defaults_file))
            if validation_error:
                raise ValueError(f"Defaults file access denied: {validation_error}")

    # Validate reference_doc if provided
    if reference_doc:
        if output_format != "docx":
            raise ValueError("reference_doc parameter is only supported for docx output format")
        if not os.path.exists(reference_doc):
            raise ValueError(f"Reference document not found: {reference_doc}")

    # Validate defaults_file if provided
    if defaults_file:
        if not os.path.exists(defaults_file):
            raise ValueError(f"Defaults file not found: {defaults_file}")

        try:
            with open(defaults_file, encoding="utf-8") as f:
                yaml_content = yaml.safe_load(f)

            if not isinstance(yaml_content, dict):
                raise ValueError(f"Invalid defaults file format: {defaults_file} - must be a YAML dictionary")

            if 'to' in yaml_content and yaml_content['to'] != output_format:
                config.logger.warning(
                    f"Defaults file specifies output format '{yaml_content['to']}' "
                    f"but requested format is '{output_format}'. Using requested format."
                )

        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing defaults file {defaults_file}: {str(e)}") from e
        except PermissionError as e:
            raise ValueError(f"Permission denied when reading defaults file: {defaults_file}") from e

    # Define supported formats
    supported_formats = {'html', 'markdown', 'pdf', 'docx', 'rst', 'latex', 'epub', 'txt', 'ipynb', 'odt', 'plain'}
    if output_format not in supported_formats:
        raise ValueError(
            f"Unsupported output format: '{output_format}'. Supported formats are: {', '.join(supported_formats)}"
        )

    # Get Pandoc-compatible format names
    pandoc_output_format = _get_pandoc_format(output_format, is_input=False)
    pandoc_input_format = _get_pandoc_format(input_format, is_input=True)

    # Validate output_file requirement for advanced formats
    advanced_formats = {'pdf', 'docx', 'rst', 'latex', 'epub'}
    if output_format in advanced_formats and not output_file:
        raise ValueError(f"output_file path is required for {output_format} format")

    # Validate filters if provided
    if filters:
        if not isinstance(filters, list):
            raise ValueError("filters parameter must be an array of strings")
        for filter_path in filters:
            if not isinstance(filter_path, str):
                raise ValueError("Each filter must be a string path")

    try:
        # Prepare conversion arguments
        extra_args = []

        # Add defaults file if provided
        if defaults_file:
            defaults_file_abs = os.path.abspath(defaults_file)
            extra_args.extend(["--defaults", defaults_file_abs])

        # Validate filters once and reuse the result
        validated_filters = _validate_filters(filters, defaults_file) if filters else []

        # Handle filter arguments
        for filter_path in validated_filters:
            extra_args.extend(["--filter", filter_path])

        # Handle PDF-specific conversion if needed
        if output_format == "pdf":
            extra_args.extend([
                "--pdf-engine=xelatex",
                "-V", "geometry:margin=1in"
            ])

        # Handle reference doc for docx format
        if reference_doc and output_format == "docx":
            extra_args.extend([
                "--reference-doc", reference_doc
            ])

        # Convert content using pypandoc
        if input_file:
            if not os.path.exists(input_file):
                raise ValueError(f"Input file not found: {input_file}")

            if output_file:
                # Convert file to file
                pypandoc.convert_file(
                    input_file,
                    pandoc_output_format,
                    outputfile=output_file,
                    extra_args=extra_args
                )

                filter_info, defaults_info = _format_result_info(filters, defaults_file, validated_filters)
                return {
                    "status": "success",
                    "message": f"File successfully converted{filter_info}{defaults_info} and saved to: {output_file}",
                    "output_file": output_file,
                }
            else:
                # Convert file to string
                converted_output = pypandoc.convert_file(
                    input_file,
                    pandoc_output_format,
                    extra_args=extra_args
                )
                filter_info, defaults_info = _format_result_info(filters, defaults_file, validated_filters)
                return {
                    "status": "success",
                    "content": converted_output,
                    "message": f"Content converted to {output_format}{filter_info}{defaults_info}",
                }
        else:
            if output_file:
                # Convert content to file
                pypandoc.convert_text(
                    contents,
                    pandoc_output_format,
                    format=pandoc_input_format,
                    outputfile=output_file,
                    extra_args=extra_args
                )

                filter_info, defaults_info = _format_result_info(filters, defaults_file, validated_filters)
                return {
                    "status": "success",
                    "message": f"Content successfully converted{filter_info}{defaults_info} and saved to: {output_file}",
                    "output_file": output_file,
                }
            else:
                # Convert content to string
                converted_output = pypandoc.convert_text(
                    contents,
                    pandoc_output_format,
                    format=pandoc_input_format,
                    extra_args=extra_args
                )

                if not converted_output:
                    raise ValueError("Conversion resulted in empty output")

                filter_info, defaults_info = _format_result_info(filters, defaults_file, validated_filters)
                return {
                    "status": "success",
                    "content": converted_output,
                    "message": f"Content converted to {output_format}{filter_info}{defaults_info}",
                }

    except Exception as e:
        error_prefix = "Error converting"
        error_details = str(e)

        if "Filter not found" in error_details or "Filter is not executable" in error_details:
            error_prefix = "Filter error during conversion"
        elif "defaults" in error_details and defaults_file:
            error_prefix = "Defaults file error during conversion"
            error_details += f" (defaults file: {defaults_file})"
        elif "pandoc" in error_details.lower() and "not found" in error_details.lower():
            error_prefix = "Pandoc executable not found"
            error_details = "Please ensure Pandoc is installed and available in your PATH"

        raise ValueError(
            f"{error_prefix} {'file' if input_file else 'contents'} from {input_format} to "
            f"{output_format}: {error_details}"
        ) from e


# === MCP Tool Handlers ===


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools.

    Each tool specifies its arguments using JSON Schema validation.
    """
    tools = [
        types.Tool(
            name="convert-contents",
            description=(
                "Converts content between different formats. Transforms input content from any supported format "
                "into the specified output format.\n\n"
                "Supported formats: markdown, html, pdf, docx, rst, latex, epub, txt, ipynb, odt\n\n"
                "Features:\n"
                "- Custom DOCX styling with reference documents\n"
                "- Pandoc filter support for custom transformations\n"
                "- Defaults file support for batch configuration\n\n"
                "Requirements:\n"
                "- PDF conversion requires TeX Live (xelatex)\n"
                "- Advanced formats (pdf, docx, rst, latex, epub) require output_file path"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "contents": {
                        "type": "string",
                        "description": "The content to be converted (required if input_file not provided)"
                    },
                    "input_file": {
                        "type": "string",
                        "description": "Complete path to input file (e.g., '/path/to/input.md')"
                    },
                    "input_format": {
                        "type": "string",
                        "description": "Source format of the content (defaults to markdown)",
                        "default": "markdown",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Desired output format (defaults to markdown)",
                        "default": "markdown",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    },
                    "output_file": {
                        "type": "string",
                        "description": "Complete path where to save the output (required for pdf, docx, rst, latex, epub)"
                    },
                    "reference_doc": {
                        "type": "string",
                        "description": "Path to a reference document for styling (docx output only)"
                    },
                    "filters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Pandoc filter paths to apply during conversion"
                    },
                    "defaults_file": {
                        "type": "string",
                        "description": "Path to a Pandoc defaults file (YAML) containing conversion options"
                    }
                },
                "additionalProperties": False
            },
        ),
        types.Tool(
            name="convert-contents-base64",
            description=(
                "Converts file content uploaded via base64 encoding. Designed for remote HTTP scenarios "
                "where direct file path access is not available.\n\n"
                "Usage:\n"
                "- Upload files as base64 encoded strings\n"
                "- Supports data URL prefix (data:...;base64,...)\n"
                "- Multiple files can be converted in one request\n"
                "- Binary outputs (docx, pdf, epub, odt) are returned as base64\n\n"
                "Supported formats: markdown, html, pdf, docx, rst, latex, epub, txt, ipynb, odt\n\n"
                "Example files format:\n"
                '[{"filename": "doc.md", "content_base64": "IyBIZWxsbyBXb3JsZA=="}]'
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {
                                    "type": "string",
                                    "description": "Original filename with extension"
                                },
                                "content_base64": {
                                    "type": "string",
                                    "description": "Base64 encoded file content"
                                }
                            },
                            "required": ["filename", "content_base64"]
                        },
                        "description": "Array of files to convert"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Desired output format",
                        "default": "markdown",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    },
                    "input_format": {
                        "type": "string",
                        "description": "Source format (optional, auto-detected from filename)",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    },
                    "keep_uploaded_files": {
                        "type": "boolean",
                        "description": "Keep uploaded files on server after conversion (default: false)",
                        "default": False
                    }
                },
                "required": ["files", "output_format"],
                "additionalProperties": False
            },
        ),
        types.Tool(
            name="convert-contents-text",
            description=(
                "Converts plain text content uploaded directly. Designed for clients that send text content "
                "rather than base64.\n\n"
                "Usage:\n"
                "- Upload text content with a filename for format detection\n"
                "- Binary outputs (docx, pdf, epub, odt) are returned as base64\n\n"
                "Supported formats: markdown, html, pdf, docx, rst, latex, epub, txt, ipynb, odt\n\n"
                "Example:\n"
                '{"filename": "doc.md", "content": "# Hello", "output_format": "html"}'
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Text content to convert"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Original filename with extension"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Desired output format",
                        "default": "markdown",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    },
                    "input_format": {
                        "type": "string",
                        "description": "Source format (optional, auto-detected from filename)",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    },
                    "keep_uploaded_files": {
                        "type": "boolean",
                        "description": "Keep uploaded files on server after conversion (default: false)",
                        "default": False
                    }
                },
                "required": ["content", "filename", "output_format"],
                "additionalProperties": False
            },
        ),
        types.Tool(
            name="convert-document-resource",
            description=(
                "Converts documents from MCP Resource URIs. Designed for GUI clients (like Cherry Studio) "
                "that expose uploaded files as MCP Resources.\n\n"
                "The client must support MCP Resource protocol and expose uploaded files as Resources.\n\n"
                "Usage:\n"
                "- Client uploads file through GUI\n"
                "- Client exposes file as Resource (e.g., file:///uploads/document.pdf)\n"
                "- This tool requests the Resource content from the client\n"
                "- Binary outputs (docx, pdf, epub, odt) are returned as base64\n\n"
                "Supported formats: markdown, html, pdf, docx, rst, latex, epub, txt, ipynb, odt\n\n"
                "Example: resource_uri='file:///uploads/document.pdf'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_uri": {
                        "type": "string",
                        "description": "MCP Resource URI (e.g., file:///uploads/document.pdf)"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Desired output format",
                        "default": "markdown",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    },
                    "input_format": {
                        "type": "string",
                        "description": "Source format (optional, auto-detected from URI)",
                        "enum": ["markdown", "html", "pdf", "docx", "rst", "latex", "epub", "txt", "ipynb", "odt"]
                    }
                },
                "required": ["resource_uri"],
                "additionalProperties": False
            },
        ),
    ]

    return tools


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests.

    Tools can modify server state and notify clients of changes.
    """
    if name not in [
        "convert-contents",
        "convert-contents-base64",
        "convert-contents-text",
        "convert-document-resource",
    ]:
        raise ValueError(f"Unknown tool: {name}")

    config.logger.debug(f"Tool call: {name}, arguments: {arguments}")

    # Detailed logging to inspect what Cherry Studio sends
    try:
        ctx = request_ctx.get()
        config.logger.info(f"=== DETAILED TOOL CALL DEBUG ===")
        config.logger.info(f"Tool name: {name}")
        config.logger.info(f"Arguments type: {type(arguments)}")
        config.logger.info(f"Arguments: {json.dumps(arguments, indent=2, ensure_ascii=False)}")
        config.logger.info(f"Request context available: {ctx is not None}")
        if hasattr(ctx, 'meta'):
            config.logger.info(f"Context meta: {ctx.meta}")
        config.logger.info(f"=================================")
    except Exception as e:
        config.logger.warning(f"Could not log detailed context: {e}")

    if not arguments:
        raise ValueError("Missing arguments")

    if name == "convert-contents":
        return await _handle_convert_contents(arguments)
    elif name == "convert-contents-base64":
        return await _handle_convert_contents_base64(arguments)
    elif name == "convert-contents-text":
        return await _handle_convert_contents_text(arguments)
    elif name == "convert-document-resource":
        return await _handle_convert_document_resource(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def _handle_convert_contents(
    arguments: dict
) -> list[types.TextContent]:
    """Handle convert-contents tool execution.

    Args:
        arguments: Tool arguments

    Returns:
        List of text content responses
    """
    contents = arguments.get("contents")
    input_file = arguments.get("input_file")
    output_file = arguments.get("output_file")
    output_format = (arguments.get("output_format") or "markdown").lower()
    input_format = (arguments.get("input_format") or "markdown").lower()
    reference_doc = arguments.get("reference_doc")
    filters = arguments.get("filters", [])
    defaults_file = arguments.get("defaults_file")

    try:
        result = await _convert_with_pandoc(
            contents=contents,
            input_file=input_file,
            output_file=output_file,
            output_format=output_format,
            input_format=input_format,
            reference_doc=reference_doc,
            filters=filters,
            defaults_file=defaults_file,
        )

        if result.get("output_file"):
            notify_with_result = result["message"]
        else:
            converted_output = result.get("content", "")
            notify_with_result = (
                f'Following are the converted contents in {output_format} format.\n'
                f'Ask user if they expect to save this file. If so, provide the output_file parameter with '
                f'complete path.\n'
                f'Converted Contents:\n\n{converted_output}'
            )

        return [
            types.TextContent(
                type="text",
                text=notify_with_result
            )
        ]

    except Exception as e:
        raise ValueError(str(e)) from e


async def _handle_convert_contents_base64(
    arguments: dict
) -> list[types.TextContent]:
    """Handle convert-contents-base64 tool execution.

    Args:
        arguments: Tool arguments

    Returns:
        List of text content responses
    """
    files = arguments.get("files", [])
    output_format = arguments.get("output_format", "markdown").lower()
    input_format = arguments.get("input_format")
    keep_uploaded_files = arguments.get("keep_uploaded_files", False)

    if not files:
        raise ValueError("files parameter is required and cannot be empty")

    # Check batch limits
    if len(files) > config.MAX_UPLOAD_FILES:
        raise ValueError(
            f"Too many files: {len(files)}, maximum is {config.MAX_UPLOAD_FILES}"
        )

    # Estimate total size
    total_estimated_size = 0
    for item in files:
        if isinstance(item, dict) and isinstance(item.get("content_base64"), str):
            total_estimated_size += _estimate_base64_decoded_size(item["content_base64"])

    if total_estimated_size > config.MAX_TOTAL_UPLOAD_BYTES:
        raise ValueError(
            f"Total upload size too large: estimated {total_estimated_size} bytes, "
            f"limit is {config.MAX_TOTAL_UPLOAD_BYTES} bytes"
        )

    # Create temporary upload directory
    temp_dir = config.ensure_temp_dir()
    upload_dir = temp_dir / "_uploads" / secrets.token_hex(12)
    upload_dir.mkdir(parents=True, exist_ok=True)

    results = []

    try:
        for item in files:
            if not isinstance(item, dict):
                results.append({
                    "status": "error",
                    "error_message": "Each file must be an object with filename and content_base64"
                })
                continue

            # Sanitize filename
            filename = _sanitize_filename(item.get("filename", ""))
            content_b64 = item.get("content_base64")

            if not isinstance(content_b64, str):
                results.append({
                    "filename": filename,
                    "status": "error",
                    "error_message": "Missing or invalid content_base64"
                })
                continue

            try:
                # Estimate file size before decoding
                estimated_size = _estimate_base64_decoded_size(content_b64)
                if estimated_size > config.MAX_UPLOAD_BYTES:
                    raise ValueError(
                        f"File too large: estimated {estimated_size} bytes, "
                        f"limit is {config.MAX_UPLOAD_BYTES} bytes"
                    )

                # Decode base64
                file_bytes = _decode_base64_payload(content_b64)

                # Verify actual size
                if len(file_bytes) > config.MAX_UPLOAD_BYTES:
                    raise ValueError(
                        f"File too large: {len(file_bytes)} bytes, "
                        f"limit is {config.MAX_UPLOAD_BYTES} bytes"
                    )

                # Save to temporary file
                temp_path = upload_dir / filename
                temp_path.write_bytes(file_bytes)

                # Determine input format from filename if not specified
                file_input_format = input_format
                if not file_input_format:
                    ext = Path(filename).suffix.lower().lstrip(".")
                    format_map = {
                        "md": "markdown",
                        "html": "html",
                        "htm": "html",
                        "txt": "txt",
                        "rst": "rst",
                        "tex": "latex",
                        "docx": "docx",
                        "odt": "odt",
                        "epub": "epub",
                        "ipynb": "ipynb",
                    }
                    file_input_format = format_map.get(ext, "markdown")

                # Determine output file path
                output_ext = output_format
                if output_format == "latex":
                    output_ext = "tex"
                elif output_format == "markdown":
                    output_ext = "md"
                elif output_format == "plain" or output_format == "txt":
                    output_ext = "txt"

                output_filename = f"{Path(filename).stem}.{output_ext}"
                output_path = upload_dir / output_filename

                # Convert file (skip path validation for internal temp files)
                result = await _convert_with_pandoc(
                    input_file=str(temp_path),
                    output_file=str(output_path),
                    output_format=output_format,
                    input_format=file_input_format,
                    skip_path_validation=True,
                )

                # Read converted content based on format type
                if output_format in BINARY_FORMATS:
                    # Return binary content as base64
                    try:
                        output_bytes = output_path.read_bytes()
                        result["content_base64"] = _encode_base64(output_bytes)
                        result["content_type"] = MIME_TYPES.get(output_format, f"application/{output_format}")
                    except (OSError, IOError) as e:
                        config.logger.error(f"Failed to read output file: {e}")
                else:
                    # Return text content directly (including ipynb which is JSON)
                    try:
                        converted_content = output_path.read_text(encoding="utf-8")
                        result["content"] = converted_content
                        if output_format == "ipynb":
                            result["content_type"] = MIME_TYPES.get("ipynb", "application/json")
                    except (OSError, UnicodeDecodeError) as e:
                        config.logger.error(f"Failed to read output file: {e}")

                result["filename"] = filename
                results.append(result)

            except Exception as e:
                results.append({
                    "filename": filename,
                    "status": "error",
                    "error_message": str(e)
                })

    finally:
        # Clean up temporary files if not keeping
        if not keep_uploaded_files and upload_dir.exists():
            try:
                shutil.rmtree(upload_dir)
            except (OSError, PermissionError) as e:
                config.logger.error(f"Failed to clean up temporary files: {str(e)}")

    # Build response
    response = _build_results_response(results)

    # Format output for text response
    if response.get("status") == "success" and len(results) == 1:
        result = results[0]
        if result.get("content"):
            text_output = (
                f"File '{result.get('filename')}' successfully converted to {output_format}.\n\n"
                f"Converted Content:\n\n{result['content']}"
            )
        elif result.get("content_base64"):
            text_output = (
                f"File '{result.get('filename')}' successfully converted to {output_format}.\n\n"
                f"Binary output (base64):\n{result['content_base64'][:100]}...\n"
                f"(Total {len(result['content_base64'])} characters)"
            )
        else:
            text_output = f"File '{result.get('filename')}' successfully converted to {output_format}."
    else:
        # Multiple files or error case
        text_output = f"Conversion results: {response['status']}\n"
        if response.get("summary"):
            summary = response["summary"]
            text_output += (
                f"Total: {summary['total_files']}, "
                f"Success: {summary['success_count']}, "
                f"Errors: {summary['error_count']}\n\n"
            )

        for result in results:
            status = result.get("status", "unknown")
            fname = result.get("filename", "unknown")
            if status == "success":
                text_output += f"  [OK] {fname}\n"
                if result.get("content"):
                    # Truncate long content
                    content_preview = result["content"][:500]
                    if len(result["content"]) > 500:
                        content_preview += "...[truncated]"
                    text_output += f"    Preview: {content_preview}\n"
                elif result.get("content_base64"):
                    text_output += f"    Binary output: {len(result['content_base64'])} chars (base64)\n"
            else:
                error_msg = result.get("error_message", "Unknown error")
                text_output += f"  [ERROR] {fname}: {error_msg}\n"

    return [
        types.TextContent(
            type="text",
            text=text_output
        )
    ]


async def _handle_convert_contents_text(
    arguments: dict
) -> list[types.TextContent]:
    """Handle convert-contents-text tool execution.

    Args:
        arguments: Tool arguments

    Returns:
        List of text content responses
    """
    content = arguments.get("content")
    raw_filename = arguments.get("filename")
    output_format = arguments.get("output_format", "markdown").lower()
    input_format = arguments.get("input_format")
    keep_uploaded_files = arguments.get("keep_uploaded_files", False)

    if not isinstance(content, str) or not content:
        raise ValueError("content parameter is required and cannot be empty")

    if not isinstance(raw_filename, str) or not raw_filename:
        raise ValueError("filename parameter is required and cannot be empty")

    filename = _sanitize_filename(raw_filename)

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > config.MAX_UPLOAD_BYTES:
        raise ValueError(
            f"Content too large: {len(content_bytes)} bytes, "
            f"limit is {config.MAX_UPLOAD_BYTES} bytes"
        )

    # Create temporary upload directory
    temp_dir = config.ensure_temp_dir()
    upload_dir = temp_dir / "_uploads" / secrets.token_hex(12)
    upload_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    try:
        # Save to temporary file
        temp_path = upload_dir / filename
        temp_path.write_text(content, encoding="utf-8")

        # Determine input format from filename if not specified
        file_input_format = _infer_input_format(input_format, filename, None, None)
        if file_input_format in BINARY_FORMATS:
            raise ValueError(
                "Binary inputs require convert-document-resource or convert-contents-base64"
            )

        # Determine output file path
        output_ext = output_format
        if output_format == "latex":
            output_ext = "tex"
        elif output_format == "markdown":
            output_ext = "md"
        elif output_format == "plain" or output_format == "txt":
            output_ext = "txt"

        output_filename = f"{Path(filename).stem}.{output_ext}"
        output_path = upload_dir / output_filename

        # Convert file (skip path validation for internal temp files)
        result = await _convert_with_pandoc(
            input_file=str(temp_path),
            output_file=str(output_path),
            output_format=output_format,
            input_format=file_input_format,
            skip_path_validation=True,
        )

        # Read converted content based on format type
        if output_format in BINARY_FORMATS:
            try:
                output_bytes = output_path.read_bytes()
                result["content_base64"] = _encode_base64(output_bytes)
                result["content_type"] = MIME_TYPES.get(output_format, f"application/{output_format}")
            except (OSError, IOError) as e:
                config.logger.error(f"Failed to read output file: {e}")
        else:
            try:
                converted_content = output_path.read_text(encoding="utf-8")
                result["content"] = converted_content
                if output_format == "ipynb":
                    result["content_type"] = MIME_TYPES.get("ipynb", "application/json")
            except (OSError, UnicodeDecodeError) as e:
                config.logger.error(f"Failed to read output file: {e}")

        # Optional MinIO upload
        if output_path.exists():
            minio_client = storage.get_storage()
            if minio_client:
                try:
                    upload_result = minio_client.upload_file(
                        output_path,
                        content_type=result.get("content_type"),
                    )
                    result["minio"] = {
                        "uploaded": True,
                        "download_url": upload_result["download_url"],
                        "object_name": upload_result["object_name"],
                        "size": upload_result["size"],
                        "bucket": upload_result["bucket"],
                    }
                except Exception as e:
                    result["minio"] = {
                        "uploaded": False,
                        "error": str(e),
                    }

        result["filename"] = filename
        results.append(result)

    except Exception as e:
        results.append({
            "filename": filename,
            "status": "error",
            "error_message": str(e),
        })

    finally:
        if not keep_uploaded_files and upload_dir.exists():
            try:
                shutil.rmtree(upload_dir)
            except (OSError, PermissionError) as e:
                config.logger.error(f"Failed to clean up temporary files: {str(e)}")

    response = _build_results_response(results)

    if response.get("status") == "success" and len(results) == 1:
        result = results[0]
        text_output = f"File '{result.get('filename')}' successfully converted to {output_format}.\n\n"
        minio_info = result.get("minio", {})
        if minio_info.get("uploaded"):
            hours = max(1, config.MINIO_URL_EXPIRY // 3600)
            text_output += (
                f"Download URL (expires in {hours} hours):\n"
                f"{minio_info.get('download_url')}\n\n"
            )
        elif minio_info.get("error"):
            text_output += f"MinIO upload failed: {minio_info.get('error')}\n\n"

        if result.get("content"):
            text_output += f"Converted Content:\n\n{result['content']}"
        elif result.get("content_base64") and not minio_info.get("uploaded"):
            text_output += (
                "Binary output (base64):\n"
                f"{result['content_base64'][:100]}...\n"
                f"(Total {len(result['content_base64'])} characters)"
            )
    else:
        text_output = f"Conversion results: {response['status']}\n"
        if response.get("summary"):
            summary = response["summary"]
            text_output += (
                f"Total: {summary['total_files']}, "
                f"Success: {summary['success_count']}, "
                f"Errors: {summary['error_count']}\n\n"
            )

        for result in results:
            status = result.get("status", "unknown")
            fname = result.get("filename", "unknown")
            if status == "success":
                text_output += f"  [OK] {fname}\n"
                if result.get("content"):
                    content_preview = result["content"][:500]
                    if len(result["content"]) > 500:
                        content_preview += "...[truncated]"
                    text_output += f"    Preview: {content_preview}\n"
                elif result.get("content_base64"):
                    text_output += f"    Binary output: {len(result['content_base64'])} chars (base64)\n"
            else:
                error_msg = result.get("error_message", "Unknown error")
                text_output += f"  [ERROR] {fname}: {error_msg}\n"

    return [
        types.TextContent(
            type="text",
            text=text_output
        )
    ]


async def _handle_convert_document_resource(
    arguments: dict
) -> list[types.TextContent]:
    """Handle convert-document-resource tool execution.

    Requests file content from MCP client via Resource protocol.

    Args:
        arguments: Tool arguments containing resource_uri, output_format, input_format

    Returns:
        List of text content responses
    """
    resource_uri = arguments.get("resource_uri")
    output_format = arguments.get("output_format", "markdown").lower()
    input_format = arguments.get("input_format")

    if not resource_uri:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": "resource_uri is required"
            })
        )]

    try:
        # STEP 1: Get current request context
        config.logger.info(f"Requesting resource from client: {resource_uri}")
        ctx = request_ctx.get()
        session = ctx.session

        # STEP 2: Send ReadResourceRequest to CLIENT
        config.logger.info(f"=== SENDING RESOURCE READ REQUEST ===")
        config.logger.info(f"Resource URI: {resource_uri}")
        config.logger.info(f"Session type: {type(session)}")

        try:
            read_result = await session.send_request(
                types.ReadResourceRequest(
                    method="resources/read",
                    params=types.ReadResourceRequestParams(uri=resource_uri)
                ),
                types.ReadResourceResult
            )
            config.logger.info(f"Resource read successful, contents: {len(read_result.contents)} items")
        except Exception as req_error:
            config.logger.error(f"=== RESOURCE READ FAILED ===")
            config.logger.error(f"Error type: {type(req_error).__name__}")
            config.logger.error(f"Error message: {str(req_error)}")
            config.logger.error(f"Full error: {repr(req_error)}")
            config.logger.error(f"===========================")
            raise

        # STEP 3: Extract file content from response
        file_bytes = None
        resource_mime_type = None
        for content in read_result.contents:
            if isinstance(content, types.BlobResourceContents):
                # Binary content (PDF, DOCX, images, etc.)
                file_bytes = base64.b64decode(content.blob)
                resource_mime_type = getattr(content, "mimeType", None)
                config.logger.debug(f"Received binary content: {len(file_bytes)} bytes")
                break
            elif isinstance(content, types.TextResourceContents):
                # Text content (markdown, plain text, etc.)
                file_bytes = content.text.encode('utf-8')
                resource_mime_type = getattr(content, "mimeType", None)
                config.logger.debug(f"Received text content: {len(file_bytes)} bytes")
                break

        if file_bytes is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "error": "No content found in resource"
                })
            )]

        # STEP 4: Security validation
        if len(file_bytes) > config.MAX_UPLOAD_BYTES:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "error": f"File too large: {len(file_bytes)} bytes (limit: {config.MAX_UPLOAD_BYTES})"
                })
            )]

        # STEP 5: Save to temporary file
        temp_dir = config.ensure_temp_dir()
        upload_dir = temp_dir / "_uploads" / secrets.token_hex(12)
        upload_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Extract filename from URI
            filename = Path(resource_uri).name or "document.bin"
            filename = _sanitize_filename(filename)
            temp_path = upload_dir / filename
            temp_path.write_bytes(file_bytes)

            config.logger.info(f"Saved resource to temp file: {temp_path}")

            # STEP 6: Infer input format with MIME, magic bytes, and filename fallback
            inferred_input_format = _infer_input_format(
                input_format,
                filename,
                resource_mime_type,
                file_bytes,
            )

            # STEP 7: Convert using existing logic
            result = _convert_file_sync(
                temp_path,
                output_format,
                inferred_input_format
            )

            # Format output
            if result.get("status") == "success":
                output_path = result.get("output_path")
                minio_info = None
                if output_path and Path(output_path).exists():
                    minio_client = storage.get_storage()
                    if minio_client:
                        try:
                            upload_result = minio_client.upload_file(
                                Path(output_path),
                                content_type=result.get("content_type"),
                            )
                            minio_info = {
                                "uploaded": True,
                                "download_url": upload_result["download_url"],
                                "object_name": upload_result["object_name"],
                                "size": upload_result["size"],
                                "bucket": upload_result["bucket"],
                            }
                        except Exception as e:
                            minio_info = {
                                "uploaded": False,
                                "error": str(e),
                            }

                text_output = f"Resource '{filename}' successfully converted to {output_format}.\n\n"
                if minio_info:
                    if minio_info.get("uploaded"):
                        hours = max(1, config.MINIO_URL_EXPIRY // 3600)
                        text_output += (
                            f"Download URL (expires in {hours} hours):\n"
                            f"{minio_info.get('download_url')}\n\n"
                        )
                    else:
                        text_output += f"MinIO upload failed: {minio_info.get('error')}\n\n"

                if result.get("content"):
                    text_output += f"Converted Content:\n\n{result['content']}"
                elif result.get("content_base64") and not (minio_info and minio_info.get("uploaded")):
                    text_output += (
                        "Binary output (base64):\n"
                        f"{result['content_base64'][:100]}...\n"
                        f"(Total {len(result['content_base64'])} characters)"
                    )
            else:
                text_output = (
                    f"Conversion failed for '{filename}'.\n"
                    f"Error: {result.get('error_message', 'Unknown error')}"
                )

            return [types.TextContent(
                type="text",
                text=text_output
            )]

        finally:
            # STEP 8: Cleanup temporary files
            if upload_dir.exists():
                try:
                    shutil.rmtree(upload_dir)
                    config.logger.debug(f"Cleaned up temp directory: {upload_dir}")
                except (OSError, PermissionError) as e:
                    config.logger.error(f"Failed to clean up temp files: {str(e)}")

    except LookupError:
        # request_ctx.get() raised LookupError - context not available
        config.logger.error("Request context not available")
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": "Request context unavailable (internal error)"
            })
        )]

    except Exception as e:
        config.logger.error(f"Resource conversion error: {str(e)}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": str(e)
            })
        )]


def _convert_file_sync(
    input_path: Path,
    output_format: str,
    input_format: Optional[str] = None
) -> dict[str, Any]:
    """Convert file synchronously using pypandoc.

    Reuses existing conversion logic for Resource-based conversions.

    Args:
        input_path: Path to input file
        output_format: Target format
        input_format: Source format (optional, auto-detected)

    Returns:
        Dictionary with status and conversion results
    """
    try:
        # Detect input format from extension if not provided
        if not input_format:
            ext = input_path.suffix.lower().lstrip(".")
            input_format = INPUT_FORMAT_ALIASES.get(ext, ext) or "markdown"

        # Get Pandoc-compatible format names
        pandoc_output_format = FORMAT_ALIASES.get(output_format, output_format)
        pandoc_input_format = INPUT_FORMAT_ALIASES.get(input_format, input_format)

        config.logger.debug(
            f"Converting {input_path.name}: {pandoc_input_format} -> {pandoc_output_format}"
        )

        # Convert using pypandoc (always write to file for MinIO upload)
        output_ext = output_format
        if output_format == "latex":
            output_ext = "tex"
        elif output_format == "plain" or output_format == "txt":
            output_ext = "txt"
        elif output_format == "markdown":
            output_ext = "md"

        output_path = input_path.parent / f"{input_path.stem}_output.{output_ext}"

        pypandoc.convert_file(
            str(input_path),
            pandoc_output_format,
            format=pandoc_input_format,
            outputfile=str(output_path)
        )

        if output_format in BINARY_FORMATS:
            output_bytes = output_path.read_bytes()
            return {
                "status": "success",
                "filename": input_path.name,
                "output_format": output_format,
                "content_base64": base64.b64encode(output_bytes).decode(),
                "content_type": MIME_TYPES.get(output_format, f"application/{output_format}"),
                "output_path": str(output_path),
            }

        converted_content = output_path.read_text(encoding="utf-8")
        content_type = "application/json" if output_format == "ipynb" else "text/plain"
        if output_format in ("html", "markdown", "md"):
            content_type = "text/html" if output_format == "html" else "text/markdown"

        return {
            "status": "success",
            "filename": input_path.name,
            "output_format": output_format,
            "content": converted_content,
            "content_type": content_type,
            "output_path": str(output_path),
        }

    except Exception as e:
        config.logger.error(f"Conversion error for {input_path.name}: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "filename": input_path.name,
            "error_message": str(e)
        }


# === Server Startup Functions ===


def create_sse_app():
    """Create Starlette app for SSE transport.

    Returns:
        Starlette application configured for SSE
    """
    try:
        from mcp.server.sse import SseServerTransport
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.middleware.cors import CORSMiddleware
        from starlette.routing import Mount, Route
    except ImportError as e:
        raise ImportError(
            "SSE mode requires additional dependencies. "
            "Install with: pip install starlette uvicorn"
        ) from e

    sse = SseServerTransport("/messages/")
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
    )

    class SSEEndpoint:
        """ASGI endpoint for SSE connections."""

        async def __call__(self, scope, receive, send):
            async with sse.connect_sse(
                scope,
                receive,
                send,
            ) as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="mcp-pandoc",
                        server_version="0.9.0",
                        capabilities=server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )

    class SSEPostEndpoint:
        """ASGI endpoint for SSE message posts."""

        async def __call__(self, scope, receive, send):
            await sse.handle_post_message(scope, receive, send)

    class MCPProxy:
        """ASGI proxy for /mcp with relaxed Accept header requirements."""

        async def __call__(self, scope, receive, send):
            scope = _normalize_mcp_headers(scope, session_manager)
            await session_manager.handle_request(scope, receive, send)

    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Manage streamable-http session manager lifecycle."""
        async with session_manager.run():
            yield

    app = Starlette(
        debug=config.DEBUG_MODE,
        routes=[
            Route("/", endpoint=SSEEndpoint()),
            Route("/sse", endpoint=SSEEndpoint()),
            Route("/sse/", endpoint=SSEEndpoint()),
            Mount("/messages", app=sse.handle_post_message),
            Mount("/sse/messages", app=SSEPostEndpoint()),
            Route("/mcp", endpoint=MCPProxy()),
            Route("/mcp/", endpoint=MCPProxy()),
        ],
        lifespan=lifespan,
    )

    if config.CORS_ALLOW_ORIGINS:
        allow_credentials = config.CORS_ALLOW_ORIGINS != ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.CORS_ALLOW_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=allow_credentials,
        )

    return app


def create_streamable_http_app():
    """Create Starlette app for Streamable HTTP transport.

    Returns:
        Starlette application configured for Streamable HTTP
    """
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.middleware.cors import CORSMiddleware
        from starlette.routing import Mount
    except ImportError as e:
        raise ImportError(
            "Streamable HTTP mode requires additional dependencies. "
            "Install with: pip install starlette uvicorn"
        ) from e

    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,  # Use JSON responses for better compatibility
    )

    class MCPProxy:
        """ASGI proxy for /mcp with relaxed Accept header requirements."""

        async def __call__(self, scope, receive, send):
            scope = _normalize_mcp_headers(scope, session_manager)
            await session_manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Manage session manager lifecycle."""
        async with session_manager.run():
            yield

    app = Starlette(
        debug=config.DEBUG_MODE,
        routes=[
            Route("/mcp", endpoint=MCPProxy()),
            Route("/mcp/", endpoint=MCPProxy()),
        ],
        lifespan=lifespan,
    )

    if config.CORS_ALLOW_ORIGINS:
        allow_credentials = config.CORS_ALLOW_ORIGINS != ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.CORS_ALLOW_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=allow_credentials,
        )

    return app


def run_server(mode: str = "stdio", port: int = 8001, host: str = "127.0.0.1"):
    """Run the MCP server with specified transport mode.

    Args:
        mode: Transport mode - "stdio", "sse", or "streamable-http"
        port: Port number for HTTP modes
        host: Host address for HTTP modes
    """
    import asyncio

    # Ensure output directory exists
    config.ensure_output_dir(get_output_dir())

    config.logger.info(f"Starting Pandoc MCP server in {mode} mode")
    config.logger.info(f"Output directory: {get_output_dir()}")
    config.logger.info(f"Configuration: {config.get_config_summary()}")

    if mode == "sse":
        try:
            import uvicorn
        except ImportError as e:
            raise ImportError(
                "SSE mode requires uvicorn. Install with: pip install uvicorn"
            ) from e

        config.logger.info(f"Starting SSE server on {host}:{port}")
        app = create_sse_app()
        uvicorn.run(app, host=host, port=port)

    elif mode == "streamable-http":
        try:
            import uvicorn
        except ImportError as e:
            raise ImportError(
                "Streamable HTTP mode requires uvicorn. Install with: pip install uvicorn"
            ) from e

        config.logger.info(f"Starting Streamable HTTP server on {host}:{port}")
        config.logger.info(f"MCP endpoint: http://{host}:{port}/mcp")
        app = create_streamable_http_app()
        uvicorn.run(app, host=host, port=port)

    else:
        # Default: stdio mode
        asyncio.run(main())


async def main():
    """Run the mcp-pandoc server using stdin/stdout streams."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcp-pandoc",
                server_version="0.9.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
