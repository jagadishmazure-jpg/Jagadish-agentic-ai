# IT desk playbook agent (project 01's graph, IT playbooks, Bedrock or the mock).
# AgentCore Runtime runs linux/arm64. Build that image with:
#   docker buildx build --platform linux/arm64 -f aws-it-desk-agent/Dockerfile -t it-desk-playbook .
# A local mock run works on the host architecture too.
# Build from the repo root.
FROM python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 IT_DESK_PROVIDER=mock PORT=8080
RUN pip install --no-cache-dir uv==0.12.23
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY shared ./shared
RUN uv sync --locked --no-dev --extra aws
COPY projects/01-policy-qa-rag/policy_qa ./policy_qa
COPY aws-it-desk-agent/it_desk ./it_desk
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
RUN /usr/local/bin/python -m pip uninstall -y uv pip \
    && useradd -m portfolio && chown -R portfolio /app
USER portfolio
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ping')"
CMD ["sh", "-c", "uvicorn it_desk.service:create_app --factory --host 0.0.0.0 --port ${PORT}"]
