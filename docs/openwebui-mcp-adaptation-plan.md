# OpenWebUI MCP "Tool" Integration Plan (File URL Fetch)

## Context

We have an MCP server (`mcp_convert_router`) that can convert an input document to Markdown via:

- `source` = local server file path
- `source` = URL (server downloads the file, then converts)
- `source` = croc code (server receives via croc, then converts)

OpenWebUI runs on a server and exposes files via its own HTTP API under `/api/v1/files/...`.
OpenWebUI does not need MinIO for this flow. Instead, the OpenWebUI "Tool" should:

1. Construct a download URL for the uploaded file.
2. Call `mcp_convert_router` and pass the URL as `source`.
3. Let `mcp_convert_router` download and process the file.

Desktop/local clients can continue to use croc; OpenWebUI server-side should prefer URL fetch.

## Goals

- Support OpenWebUI "Tool" integration without sending base64/binary blobs through the tool call.
- Download from OpenWebUI via `/api/v1/files/{id}/content` (optionally `?attachment=true`).
- Support both public and private network deployments by using an explicit allowlist.
- Avoid MinIO entirely for this OpenWebUI integration.

## Non-goals

- Implementing or modifying OpenWebUI itself (only referencing its API).
- Disabling SSRF protections globally (we will use allowlists, not broad allow-all).
- Changing the existing croc flow for desktop/local clients.

## Source of Truth (OpenWebUI)

Verified in `D:\Work\open-webui`:

- File download routes (FastAPI):
  - `backend/open_webui/routers/files.py`:
    - `GET /api/v1/files/{id}/content` (supports `?attachment=true`)
    - `GET /api/v1/files/{id}/content/{file_name}`
    - `GET /api/v1/files/{id}/content/html` (admin-only)
    - `GET /api/v1/files/{id}/data/content` (extracted text as JSON)
- Auth requirements:
  - File routes depend on `get_verified_user` which depends on `get_current_user`:
    - `backend/open_webui/utils/auth.py`
  - Token sources:
    - `Authorization: Bearer <token>` header, OR cookie `token`
  - API keys are supported when token starts with `sk-` (permission gated).
- Response headers:
  - `Content-Disposition` is set with RFC5987 `filename*=` (UTF-8 percent-encoded).

## Implementation Plan

### 1) Extend MCP tool inputs to support URL fetch from OpenWebUI

Update `mcp_convert_router` to accept optional URL request headers:

- Add tool argument: `url_headers` (object: string -> string)
- When `source_type == "url"`, pass `url_headers` into the downloader so it can request
  authenticated OpenWebUI endpoints (Bearer token or `sk-` API key).

Files to edit:
- `mcp_convert_router/server.py` (schema + plumb args through)
- `mcp_convert_router/url_downloader.py` (accept headers and send them)

Logging / safety:
- Do not log header values.
- Keep errors user-friendly without leaking secrets.

### 2) Allow OpenWebUI hosts while preserving SSRF protection

Today URL validation and SSRF checks block private networks in two places:

- `mcp_convert_router/validators.py` rejects private/localhost-like hosts.
- `mcp_convert_router/url_downloader.py` performs DNS/IP SSRF checks and also blocks private ranges.

Add a strict allowlist mechanism for URL hosts:

- `MCP_CONVERT_ALLOWED_URL_HOSTS` (comma-separated)
  - Example: `openwebui.example.com,211.93.0.206,192.168.1.236,openwebui,localhost`

Behavior:
- If URL hostname matches allowlist, permit it (even if private IP), and proceed.
- Otherwise keep current SSRF rules (deny private ranges, localhost, metadata IPs, etc.).

Files to edit:
- `mcp_convert_router/validators.py`
- `mcp_convert_router/url_downloader.py`
- `.env.template` and `mcp_convert_router/README.md` (document the env var)

### 3) Improve filename inference for OpenWebUI `/content` URLs

OpenWebUI's primary endpoint ends with `/content` (often no filename/extension).
To preserve correct extensions and improve downstream UX:

- Prefer filename from `Content-Disposition` (`filename` / `filename*`) if present.
- Sanitize the filename to prevent traversal (strip slashes, remove `..`, etc.).
- Fall back to current URL-path-derived naming if header is absent.

Files to edit:
- `mcp_convert_router/url_downloader.py`

### 4) Provide an OpenWebUI Tool script (URL-based)

Create a reference Tool script (to be copied into OpenWebUI Tools) that:

- Accepts `file_id`
- Constructs:
  - `file_url = <openwebui_base_url>/api/v1/files/{file_id}/content?attachment=true`
- Extracts auth from the OpenWebUI request context:
  - Prefer forwarding `Authorization` header if present
  - Else forward cookie `token` as `Authorization: Bearer <token>` if available
- Calls MCP JSON-RPC:
  - `method: tools/call`
  - `name: convert_to_markdown`
  - `arguments: { "source": file_url, "url_headers": { ... }, ... }`

We will also support an optional Tool valve `openwebui_api_key`:

- If set, it overrides forwarded user auth and uses:
  - `Authorization: Bearer sk-...` (OpenWebUI API key)

Files to add:
- `docs/openwebui/openwebui_tool_filetomd_url.py` (reference implementation)

### 5) TLS / HTTPS considerations (optional but likely needed)

If OpenWebUI is served via HTTPS with a self-signed/internal cert, MCP downloads may fail.
Add an opt-in env var:

- `MCP_CONVERT_URL_TLS_VERIFY` (default: true)

If set to `false`, `httpx` should skip TLS verification for URL downloads.

Files to edit:
- `mcp_convert_router/url_downloader.py`
- `.env.template` / docs

### 6) Tests / smoke checks

Add lightweight tests (unittest) focusing on:

- Allowlisted hosts bypass private-IP blocking
- `Content-Disposition filename*` parsing yields a safe filename
- Passed headers are included in outbound request (using `httpx.MockTransport`)

Also run:

- `python -m compileall mcp_convert_router`
- `python -m unittest` (if tests are added)

## Configuration (MCP side)

Required for OpenWebUI integration (recommended defaults shown):

- `MCP_CONVERT_ALLOWED_URL_HOSTS`:
  - Must include BOTH:
    - the public host (if used), AND
    - the internal host/IP (if used)

Optional:
- `MCP_CONVERT_URL_TLS_VERIFY=false` (only if OpenWebUI uses untrusted TLS)

## Configuration (OpenWebUI Tool side)

Tool valves:

- `mcp_url`: base URL of the MCP server (e.g. `http://mcp-convert-router:25081`)
- `openwebui_base_url`: base URL of OpenWebUI as reachable FROM the MCP server
- `timeout_seconds`: MCP call timeout
- `openwebui_api_key` (optional): `sk-...` API key used for file download (overrides user auth forwarding)

## Security Notes

- Default posture remains SSRF-safe. Only allowlisted hosts are permitted for URL downloads.
- Forwarding user tokens is least-privilege and matches OpenWebUI ACLs, but it increases trust in MCP.
- Using a service API key is operationally simpler but can be higher privilege; use only if needed.

## Rollout / Verification Checklist

1. Confirm MCP can reach OpenWebUI `openwebui_base_url` (DNS + routing).
2. Set `MCP_CONVERT_ALLOWED_URL_HOSTS` accordingly.
3. In OpenWebUI, install the URL-based Tool script and configure valves.
4. Upload a file in OpenWebUI, call the Tool with its `file_id`.
5. Verify:
   - MCP downloads the file successfully (no 401/403)
   - Output Markdown looks correct
   - No base64 content is returned to the user/tool

