# Assessment bank API. Mock auth and an in-memory store unless the container env says otherwise.
# Build from the repo root:
#   docker build -f assessment-bank/Dockerfile -t assessment-bank .
FROM python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ASSESSMENT_AUTH_MODE=mock ASSESSMENT_STORE=memory PORT=8080
# The pinned digest predates Debian 13 fixes for apt (CVE-2026-109518) and zlib (CVE-2026-85091).
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.23
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY shared ./shared
RUN uv sync --locked --no-dev
COPY assessment-bank/assessment_bank ./assessment_bank
COPY assessment-bank/banks ./banks
COPY assessment-bank/labs ./labs
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
RUN /usr/local/bin/python -m pip uninstall -y uv pip \
    && useradd -m portfolio && chown -R portfolio /app
USER portfolio
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["sh", "-c", "uvicorn assessment_bank.app:create_app --factory --host 0.0.0.0 --port ${PORT}"]
