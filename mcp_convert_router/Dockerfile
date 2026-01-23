FROM python:3.12-slim

ARG APP_HOME=/app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=${APP_HOME}

WORKDIR ${APP_HOME}

# Optional features:
# - INSTALL_LIBREOFFICE=1 enables legacy Office conversion via soffice (large image)
# - INSTALL_CROC=1 enables croc receive mode (package availability varies by distro)
ARG INSTALL_LIBREOFFICE=0
ARG INSTALL_CROC=0

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates pandoc; \
    if [ "${INSTALL_LIBREOFFICE}" = "1" ] || [ "${INSTALL_LIBREOFFICE}" = "true" ]; then \
      apt-get install -y --no-install-recommends libreoffice; \
    fi; \
    if [ "${INSTALL_CROC}" = "1" ] || [ "${INSTALL_CROC}" = "true" ]; then \
      apt-get install -y --no-install-recommends croc; \
    fi; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    addgroup --system app; \
    adduser --system --ingroup app app

COPY requirements.txt ${APP_HOME}/requirements.txt
RUN pip install -r ${APP_HOME}/requirements.txt

COPY . ${APP_HOME}/mcp_convert_router
RUN chown -R app:app ${APP_HOME}

USER app

# SSE mode listens on MCP_PORT (default 8000). stdio mode does not listen on a port.
EXPOSE 8000

# Default to Streamable HTTP in containers (modern clients often POST to the base URL).
ENV MCP_TRANSPORT=streamable_http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_HTTP_PATH=/

ENTRYPOINT ["python", "-m", "mcp_convert_router.server"]
