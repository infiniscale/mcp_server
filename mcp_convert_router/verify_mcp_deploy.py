#!/usr/bin/env python3
"""
Verify an MCP deployment from the client side.

Checks:
  1) Streamable HTTP: POST to base URL (or --http-path) should NOT be 404.
  2) SSE: GET /sse returns an endpoint event, and POST to returned /messages endpoint should NOT be 404.

Usage:
  python mcp_convert_router/verify_mcp_deploy.py --base-url http://127.0.0.1:8000
  python mcp_convert_router/verify_mcp_deploy.py --base-url https://example.com/mcp --sse-path /mcp/sse
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urljoin, urlparse

import httpx


def _join(base_url: str, path: str) -> str:
    base = base_url.rstrip("/") + "/"
    return urljoin(base, path.lstrip("/"))


def _print_result(ok: bool, name: str, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"{status}: {name} - {detail}")


def _read_sse_endpoint(resp: httpx.Response) -> str | None:
    endpoint = None
    for line in resp.iter_lines():
        if not line:
            continue
        # Example: "data: /messages/?session_id=..."
        if line.startswith("data: "):
            endpoint = line[len("data: ") :].strip()
            break
    return endpoint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Public base URL of your deployment, e.g. http://host:8000")
    parser.add_argument("--http-path", default="/", help="Streamable HTTP path to POST to (default: /)")
    parser.add_argument("--sse-path", default="/sse", help="SSE path to GET (default: /sse)")
    parser.add_argument(
        "--transport",
        choices=["streamable_http", "sse", "auto"],
        default="auto",
        help="Which transport to verify. auto=pass if either works.",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout seconds")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification (https only)")
    args = parser.parse_args(argv)

    # Quick sanity for base URL
    u = urlparse(args.base_url)
    if u.scheme not in ("http", "https") or not u.netloc:
        print("Invalid --base-url, expected like http://host:8000")
        return 2

    client = httpx.Client(timeout=args.timeout, verify=not args.insecure)

    ok_streamable = False
    ok_sse = False

    # 1) Streamable HTTP: many clients POST directly to the base URL (or configured path).
    if args.transport in ("streamable_http", "auto"):
        try:
            url = _join(args.base_url, args.http_path)
            r = client.post(
                url,
                headers={
                    "content-type": "application/json",
                    # streamable_http requires both json and sse accept unless JSON-only mode is enabled
                    "accept": "application/json, text/event-stream",
                },
                # Intentionally minimal/invalid JSON-RPC to avoid needing full MCP handshake here.
                json={},
            )
            ok_streamable = r.status_code != 404
            _print_result(ok_streamable, "streamable_http", f"POST {args.http_path} -> {r.status_code}")
        except Exception as e:
            _print_result(False, "streamable_http", f"exception: {e}")

    # 2) SSE: verify /sse works and endpoint is reachable (no 404).
    if args.transport in ("sse", "auto"):
        try:
            sse_url = _join(args.base_url, args.sse_path)
            with client.stream("GET", sse_url, headers={"accept": "text/event-stream"}) as resp:
                if resp.status_code != 200:
                    _print_result(False, "sse", f"GET {args.sse_path} -> {resp.status_code}")
                else:
                    endpoint = _read_sse_endpoint(resp)
                    if not endpoint:
                        _print_result(False, "sse", "no endpoint event found in SSE stream")
                    else:
                        post_url = _join(args.base_url, endpoint)
                        pr = client.post(post_url, headers={"content-type": "application/json"}, json={})
                        ok_sse = pr.status_code != 404
                        _print_result(ok_sse, "sse_post_endpoint", f"POST {endpoint} -> {pr.status_code}")
        except Exception as e:
            _print_result(False, "sse", f"exception: {e}")

    if args.transport == "streamable_http":
        return 0 if ok_streamable else 1
    if args.transport == "sse":
        return 0 if ok_sse else 1
    # auto: pass if either works (useful for deployments that intentionally expose only one transport)
    return 0 if (ok_streamable or ok_sse) else 1


if __name__ == "__main__":
    raise SystemExit(main())
