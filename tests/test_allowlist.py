# test_allowlist.py
import pytest
import os
from mcp_convert_router.validators import validate_url

def test_allowlist_permits_private_ip():
    """Verify allowlisted hosts bypass SSRF protection."""
    os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "192.168.1.100,openwebui"

    result = validate_url("http://192.168.1.100/api/files/123", {})
    assert result["valid"] is True

    result = validate_url("http://openwebui/api/files/456", {})
    assert result["valid"] is True

def test_non_allowlisted_private_ip_rejected():
    """Verify non-allowlisted private IPs are blocked."""
    os.environ["MCP_CONVERT_ALLOWED_URL_HOSTS"] = "192.168.1.100"

    result = validate_url("http://192.168.1.200/file.pdf", {})
    assert result["valid"] is False
    assert result["error_code"] == "E_URL_FORBIDDEN"
