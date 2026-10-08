# Care BFF + MCP servers share one image; docker-compose picks the command per service.
# Build from the repo root:  docker build -f projects/11-customer-care-e2e/Dockerfile -t care-e2e .
# Base image pinned by digest (tag kept for readability); Dependabot's docker ecosystem bumps both.
FROM python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LLM_PROVIDER=mock
RUN pip install --no-cache-dir uv==0.12.23
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY shared ./shared
RUN uv sync --locked --no-dev --extra openai
COPY projects/11-customer-care-e2e ./projects/11-customer-care-e2e
ENV PYTHONPATH=/app:/app/projects/11-customer-care-e2e PATH="/app/.venv/bin:$PATH"
# uv and pip are build tools only; they are not shipped in the runtime image (the app runs from /app/.venv).
RUN /usr/local/bin/python -m pip uninstall -y uv pip \
    && useradd -m care && chown -R care /app
USER care
EXPOSE 8080
CMD ["uvicorn", "care_e2e.bff:app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
