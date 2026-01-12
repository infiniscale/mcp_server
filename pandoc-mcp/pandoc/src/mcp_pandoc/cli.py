"""Pandoc MCP Command Line Interface.

This module provides the command-line entry point for the Pandoc MCP server,
supporting multiple transport modes:
- stdio (default): Standard input/output for local use
- sse: Server-Sent Events for HTTP connections
- streamable-http: Streamable HTTP for modern MCP clients
"""

import argparse
import sys

from . import config
from . import server


def main():
    """Main entry point for the Pandoc MCP CLI."""
    parser = argparse.ArgumentParser(
        description="Pandoc MCP Server - Document conversion service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in stdio mode (default, for Claude Desktop)
  mcp-pandoc

  # Run as HTTP server with SSE
  mcp-pandoc --transport sse --port 8001

  # Run with custom output directory
  mcp-pandoc --output-dir ./converted_files

  # Run on all interfaces (for remote access)
  mcp-pandoc --transport sse --host 0.0.0.0 --port 8001

Environment Variables:
  PANDOC_OUTPUT_DIR              Output directory for converted files
  PANDOC_TEMP_DIR                Temporary file directory
  PANDOC_MCP_MAX_UPLOAD_BYTES    Maximum upload file size (bytes)
  PANDOC_MCP_MAX_FILE_BYTES      Maximum local file size (bytes)
  PANDOC_MCP_DISABLE_PATH_INPUT  Disable local file path access
  PANDOC_MCP_REQUIRE_ALLOWLIST   Require path allowlist
  PANDOC_MCP_ALLOWED_INPUT_ROOTS Allowed input directories
  PANDOC_LOG_LEVEL               Logging level (DEBUG, INFO, WARNING, ERROR)
  PANDOC_DEBUG                   Enable debug mode

See .env.example for detailed configuration options.
        """
    )

    parser.add_argument(
        "--transport", "-t",
        type=str,
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport mode (default: stdio)"
    )

    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8001,
        help="Server port for HTTP modes (default: 8001)"
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host address for HTTP modes (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        help=f"Output directory for converted files (default: {config.DEFAULT_OUTPUT_DIR})"
    )

    parser.add_argument(
        "--version", "-v",
        action="version",
        version="mcp-pandoc 0.9.0"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show current configuration and exit"
    )

    args = parser.parse_args()

    # Handle debug mode
    if args.debug:
        import logging
        config.logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)

    # Show configuration if requested
    if args.show_config:
        _show_config()
        sys.exit(0)

    # Set output directory if provided
    if args.output_dir:
        server.set_output_dir(args.output_dir)

    # Print startup information for HTTP modes
    if args.transport in ["sse", "streamable-http"]:
        print(f"Starting Pandoc MCP Server")
        print(f"  Transport: {args.transport}")
        print(f"  Address:   {args.host}:{args.port}")
        print(f"  Output:    {server.get_output_dir()}")
        print()
        print("Press Ctrl+C to stop the server")
        print()

    try:
        # Run the server
        server.run_server(
            mode=args.transport,
            port=args.port,
            host=args.host
        )
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)
    except ImportError as e:
        print(f"Error: Missing dependencies - {e}")
        print("For HTTP modes, install: pip install starlette uvicorn")
        sys.exit(1)
    except Exception as e:
        config.logger.error(f"Server error: {e}")
        sys.exit(1)


def _show_config():
    """Display current configuration settings."""
    print("Pandoc MCP Server Configuration")
    print("=" * 40)

    cfg = config.get_config_summary()

    print(f"\nBasic Settings:")
    print(f"  Output Directory:  {cfg['output_dir']}")
    print(f"  Temp Directory:    {cfg['temp_dir']}")
    print(f"  Pandoc Path:       {cfg['pandoc_path']}")

    print(f"\nSecurity Settings:")
    print(f"  Max Upload Size:   {cfg['max_upload_bytes'] / 1024 / 1024:.1f} MB")
    print(f"  Max File Size:     {cfg['max_file_bytes'] / 1024 / 1024:.1f} MB")
    print(f"  Max Upload Files:  {cfg['max_upload_files']}")
    print(f"  Max Total Upload:  {cfg['max_total_upload_bytes'] / 1024 / 1024:.1f} MB")
    print(f"  Disable Path Input: {cfg['disable_path_input']}")
    print(f"  Disable Filters:    {cfg['disable_filters']}")
    print(f"  Require Allowlist:  {cfg['require_path_allowlist']}")
    print(f"  Restrict Output Dir: {cfg['restrict_output_dir']}")

    if cfg['allowed_input_roots']:
        print(f"  Allowed Input Roots:")
        for root in cfg['allowed_input_roots']:
            print(f"    - {root}")

    if cfg['allowed_output_roots']:
        print(f"  Allowed Output Roots:")
        for root in cfg['allowed_output_roots']:
            print(f"    - {root}")

    print(f"\nLogging:")
    print(f"  Log Level:  {cfg['log_level']}")
    print(f"  Debug Mode: {cfg['debug_mode']}")

    # Check pandoc availability
    print(f"\nPandoc Status:")
    try:
        import pypandoc
        version = pypandoc.get_pandoc_version()
        print(f"  Version: {version}")
        print(f"  Status:  Available")
    except Exception as e:
        print(f"  Status:  Not available ({e})")


if __name__ == "__main__":
    main()
