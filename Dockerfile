# memloom container image — installs the published PyPI package.
# Build: docker build -t memloom:latest .
FROM python:3.11-slim

ARG MEMLOOM_VERSION=0.8.0
ARG UID=1000

RUN pip install --no-cache-dir uv \
    && useradd -m -u $UID -s /bin/bash memloom \
    && mkdir -p /data /config /app \
    && chown -R memloom:memloom /data /config /app

USER memloom
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV=/app/.venv

RUN uv venv /app/.venv \
    && uv pip install --no-cache "memloom==${MEMLOOM_VERSION}"

EXPOSE 8789
CMD ["memloom", "serve", "--host", "0.0.0.0", "--port", "8789"]
