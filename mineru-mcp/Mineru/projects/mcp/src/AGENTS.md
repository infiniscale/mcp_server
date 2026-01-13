# Repository Guidelines

## Project Structure & Module Organization
- `src/mineru/` holds the MCP server implementation (`cli.py`, `server.py`, `api.py`, `config.py`, `language.py`).
- `README.md` documents installation and MCP usage; `DOCKER_README.md` covers container deployment.
- `Dockerfile` and `docker-compose.yml` define container builds and local orchestration.
- `.env.example` is the reference for environment configuration.

## Build, Test, and Development Commands
Run these from `projects/mcp/`:
- `uv pip install -e .` or `pip install -e .`: install the package in editable mode for development.
- `mineru-mcp`: start the MCP server using the installed entry point.
- `python -m mineru.cli --transport sse --host 127.0.0.1 --port 8001`: run directly from source with explicit transport options.
- `docker-compose up -d`: build and run the service in Docker (see `DOCKER_README.md`).
- `docker-compose logs -f`: tail container logs.

## Coding Style & Naming Conventions
- Python 3.10+; use 4-space indentation and PEP 8 spacing.
- Use `snake_case` for functions/variables, `CapWords` for classes, and keep module names short and descriptive.
- Prefer small, focused helpers; log through the standard `logging` setup in `config.py`.

## Testing Guidelines
- There is no dedicated test suite under `projects/mcp/` today.
- If you add tests, place them in `projects/mcp/tests/` and run with `python -m pytest`.
- Include at least one integration-style check (e.g., call `parse_documet` against a known sample) when changing API behavior.

## Commit & Pull Request Guidelines
- Recent history is free-form (including Chinese summaries) with no enforced conventional format.
- Use a concise, imperative summary and keep the body focused on “what changed” and “why”.
- PRs should include: a short description, any config/env var changes, and how the server was exercised (command or Docker run).
- Avoid committing secrets; update `.env.example` when new env vars are introduced.

## Security & Configuration Tips
- `MINERU_API_KEY` is required to start the server; set it in `.env` or your shell.
- Remote vs. local parsing is controlled by `USE_LOCAL_API` and `LOCAL_MINERU_API_BASE`.
- For stricter local file handling, use `MINERU_MCP_DISABLE_PATH_INPUT`, `MINERU_MCP_REQUIRE_ALLOWLIST`, and `MINERU_MCP_ALLOWED_INPUT_ROOTS`.
