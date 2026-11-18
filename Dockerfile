FROM python:3.12-slim

LABEL org.opencontainers.image.title="zvm-otel-exporter" \
      org.opencontainers.image.description="Prometheus and OpenTelemetry exporter for z/VM metrics via Feilong" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

USER 65534:65534
EXPOSE 9110

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9110/health')"]

ENTRYPOINT ["zvm-otel-exporter"]
CMD ["--config", "/etc/zvm-exporter/config.yaml"]
