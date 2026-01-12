# Pandoc MCP Server Dockerfile
# Multi-stage build for smaller image size

# ============================================
# Builder stage
# ============================================
FROM python:3.11-slim-bookworm as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml uv.lock* ./
COPY src/ ./src/

# Install dependencies using uv
RUN uv sync --frozen --no-dev || uv sync --no-dev

# ============================================
# Production image (without TeX - smaller)
# ============================================
FROM python:3.11-slim-bookworm as production

# Install Pandoc only (no TeX, ~100MB smaller)
RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy virtual environment and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/pyproject.toml /app/

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Default security configuration for remote deployment
ENV PANDOC_OUTPUT_DIR=/app/output
ENV PANDOC_TEMP_DIR=/app/temp
ENV PANDOC_MCP_DISABLE_PATH_INPUT=true
ENV PANDOC_MCP_DISABLE_FILTERS=true
ENV PANDOC_LOG_LEVEL=INFO

# Create directories and set permissions
RUN mkdir -p /app/output /app/temp && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Default port
EXPOSE 8001

# Health check for streamable-http mode
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/mcp', timeout=5)" || exit 1

# Default command - streamable-http on 0.0.0.0:8001
CMD ["python", "-m", "mcp_pandoc.cli", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8001"]

# ============================================
# Production image with TeX (for PDF support)
# ============================================
FROM python:3.11-slim-bookworm as production-pdf

# Install Pandoc and TeX Live for PDF conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-lang-chinese \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy virtual environment and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/pyproject.toml /app/

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Default security configuration for remote deployment
ENV PANDOC_OUTPUT_DIR=/app/output
ENV PANDOC_TEMP_DIR=/app/temp
ENV PANDOC_MCP_DISABLE_PATH_INPUT=true
ENV PANDOC_MCP_DISABLE_FILTERS=true
ENV PANDOC_LOG_LEVEL=INFO

# Create directories and set permissions
RUN mkdir -p /app/output /app/temp && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Default port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/mcp', timeout=5)" || exit 1

# Default command
CMD ["python", "-m", "mcp_pandoc.cli", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8001"]
