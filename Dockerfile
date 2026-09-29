# Portfolio API: every LangGraph project behind one FastAPI app (shared/api), for Azure Container Apps.
# Build from the repo root:  docker build -t agentic-portfolio .
# Run:                       docker run -p 8080:8080 agentic-portfolio   ->  GET /healthz, /projects
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LLM_PROVIDER=mock PORT=8080
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY shared ./shared
RUN uv sync --locked --no-dev --extra openai --extra otlp
COPY evals ./evals
COPY projects ./projects
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
RUN useradd -m portfolio && chown -R portfolio /app
USER portfolio
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz')"
CMD ["sh", "-c", "uvicorn shared.api.app:create_app --factory --host 0.0.0.0 --port ${PORT}"]
