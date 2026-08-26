FROM python:3.12.8-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/home/vpnsale/.local/bin:$PATH
WORKDIR /app
RUN addgroup --system vpnsale && adduser --system --ingroup vpnsale --home /home/vpnsale vpnsale \
    && install -d -o vpnsale -g vpnsale -m 0700 /var/lib/vpnsale/private \
    && install -d -o vpnsale -g vpnsale -m 0700 /var/lib/vpnsale/private/manual-topups \
    && install -d -o vpnsale -g vpnsale -m 0700 /var/lib/vpnsale/private/support \
    && apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt ./requirements.txt
RUN chmod 0644 ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip==24.3.1 \
    && pip install --no-cache-dir -r requirements.txt
COPY --chown=vpnsale:vpnsale apps/api ./apps/api
COPY --chown=vpnsale:vpnsale packages ./packages
RUN chmod -R u+rwX,go+rX /app/apps/api /app/packages
ENV PYTHONPATH=/app/apps/api/src:/app/packages/domain/src:/app/packages/panel-adapters/src:/app/packages/payment-adapters/src
USER vpnsale
RUN test "$(id -u)" -ne 0 \
    && test -r /app/apps/api/src/platform_api/main.py \
    && test -r /app/apps/api/alembic.ini \
    && test -x /app/apps/api/alembic/versions \
    && find /app/apps/api/alembic/versions -type f -readable | grep -q . \
    && test -w /var/lib/vpnsale/private/manual-topups \
    && test -w /var/lib/vpnsale/private/support \
    && python -c 'import sys; assert "/app/apps/api/src" in sys.path; from platform_api.main import app; assert app' \
    && alembic --version
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "platform_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
