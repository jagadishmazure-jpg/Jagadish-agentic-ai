# Care BFF + MCP servers share one image; docker-compose picks the command per service.
# Build from the repo root:  docker build -f projects/11-customer-care-e2e/Dockerfile -t care-e2e .
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LLM_PROVIDER=mock
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY shared ./shared
RUN uv sync --locked --no-dev --extra openai
COPY projects/11-customer-care-e2e ./projects/11-customer-care-e2e
ENV PYTHONPATH=/app:/app/projects/11-customer-care-e2e PATH="/app/.venv/bin:$PATH"
RUN useradd -m care && chown -R care /app
USER care
EXPOSE 8080
CMD ["uvicorn", "care_e2e.bff:app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
