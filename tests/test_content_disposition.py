# test_content_disposition.py
import pytest
from mcp_convert_router.url_downloader import _extract_filename_from_response
import httpx

def test_extract_filename_from_content_disposition():
    """Verify filename extraction from Content-Disposition."""
    response = httpx.Response(
        200,
        headers={"Content-Disposition": 'attachment; filename="report.pdf"'}
    )
    filename = _extract_filename_from_response(response, "https://example.com/content")
    assert filename == "report.pdf"

def test_extract_filename_rfc5987():
    """Verify RFC5987 filename* parsing."""
    response = httpx.Response(
        200,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf"}
    )
    filename = _extract_filename_from_response(response, "https://example.com/content")
    assert filename == "报告.pdf"

def test_fallback_to_url_filename():
    """Verify fallback to URL when no header."""
    response = httpx.Response(200)
    filename = _extract_filename_from_response(response, "https://example.com/documents/report.pdf")
    assert filename == "report.pdf"
