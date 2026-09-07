FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RETAILOPS_OUTPUT=/data
COPY requirements-web.txt /app/
COPY requirements-postgres.txt requirements-graph.txt /app/
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements-web.txt -r requirements-postgres.txt -r requirements-graph.txt
COPY retailops_baseline.py inference_proxy.py retailops_api.py retailops_conversation.py retailops_agent.py retailops_tools.py agent_protocol.py retailops_providers.py /app/
COPY web /app/web
COPY deploy/compose.api.yaml /app/deploy/compose.api.yaml
COPY retailops_public.py /app/
COPY retailops /app/retailops
COPY deploy/compose.public.yaml deploy/Caddyfile deploy/start-public-web.sh deploy/rollout-public-web.sh /app/deploy/
COPY deploy/compose.postgres.yaml deploy/init-postgres.sh deploy/configure-postgres.py deploy/cutover-postgres.sh deploy/enable-pgvector.sh /app/deploy/
COPY tests /app/tests
COPY data/smoke.jsonl /app/data/smoke.jsonl
COPY data/products.json /app/data/products.json
COPY data/knowledge /app/data/knowledge
RUN groupadd --gid 10001 retailops && useradd --uid 10001 --gid 10001 --no-create-home retailops && mkdir /data && chown 10001:10001 /data
USER 10001:10001
ENTRYPOINT ["python", "retailops_baseline.py"]
CMD ["--help"]
