# Portfolio API: every LangGraph project behind one FastAPI app (shared/api), for Azure Container Apps.
# Build from the repo root:  docker build -t agentic-portfolio .
# Run:                       docker run -p 8080:8080 agentic-portfolio   ->  GET /healthz, /projects
# Base image pinned by digest (tag kept for readability); Dependabot's docker ecosystem bumps both.
FROM python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LLM_PROVIDER=mock PORT=8080
RUN pip install --no-cache-dir uv==0.12.23
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY shared ./shared
RUN uv sync --locked --no-dev --extra openai --extra otlp
COPY evals ./evals
COPY projects ./projects
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
# uv and pip are build tools only; they are not shipped in the runtime image (the app runs from /app/.venv).
RUN /usr/local/bin/python -m pip uninstall -y uv pip \
    && useradd -m portfolio && chown -R portfolio /app
USER portfolio
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz')"
CMD ["sh", "-c", "uvicorn shared.api.app:create_app --factory --host 0.0.0.0 --port ${PORT}"]
