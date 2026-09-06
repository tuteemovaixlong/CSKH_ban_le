FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RETAILOPS_OUTPUT=/data
COPY retailops_baseline.py inference_proxy.py retailops_api.py retailops_conversation.py /app/
COPY web /app/web
COPY deploy/compose.api.yaml /app/deploy/compose.api.yaml
COPY tests /app/tests
COPY data/smoke.jsonl /app/data/smoke.jsonl
COPY data/products.json /app/data/products.json
RUN groupadd --gid 10001 retailops && useradd --uid 10001 --gid 10001 --no-create-home retailops && mkdir /data && chown 10001:10001 /data
USER 10001:10001
ENTRYPOINT ["python", "retailops_baseline.py"]
CMD ["--help"]
