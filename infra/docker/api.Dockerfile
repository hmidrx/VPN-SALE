FROM python:3.12.8-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/home/vpnsale/.local/bin:$PATH
WORKDIR /app
RUN addgroup --system vpnsale && adduser --system --ingroup vpnsale --home /home/vpnsale vpnsale \
    && apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --chmod=0644 requirements-dev.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip==24.3.1 \
    && pip install --no-cache-dir -r requirements.txt
COPY --chown=vpnsale:vpnsale --chmod=u=rwX,go=rX apps/api ./apps/api
COPY --chown=vpnsale:vpnsale --chmod=u=rwX,go=rX packages ./packages
ENV PYTHONPATH=/app/apps/api/src:/app/packages/domain/src:/app/packages/panel-adapters/src:/app/packages/payment-adapters/src
USER vpnsale
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "platform_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
