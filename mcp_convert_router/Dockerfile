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
# - INSTALL_CROC=1 enables croc receive mode (downloaded from GitHub releases)
ARG INSTALL_LIBREOFFICE=0
ARG INSTALL_CROC=1
ARG CROC_VERSION=10.3.1

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates pandoc curl; \
    if [ "${INSTALL_LIBREOFFICE}" = "1" ] || [ "${INSTALL_LIBREOFFICE}" = "true" ]; then \
      apt-get install -y --no-install-recommends libreoffice; \
    fi; \
    if [ "${INSTALL_CROC}" = "1" ] || [ "${INSTALL_CROC}" = "true" ]; then \
      curl -fL "https://github.com/schollz/croc/releases/download/v${CROC_VERSION}/croc_v${CROC_VERSION}_Linux-64bit.tar.gz" \
        -o /tmp/croc.tar.gz; \
      tar -xzf /tmp/croc.tar.gz -C /tmp; \
      mv /tmp/croc /usr/local/bin/croc; \
      chmod +x /usr/local/bin/croc; \
      rm -rf /tmp/*; \
    fi; \
    apt-get purge -y --auto-remove curl; \
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
