FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

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

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app/mcp_convert_router
RUN chown -R app:app /app

USER app

# MCP stdio transport: keep stdin open when running the container (e.g. docker run -i ...)
CMD ["python", "-m", "mcp_convert_router.server"]

