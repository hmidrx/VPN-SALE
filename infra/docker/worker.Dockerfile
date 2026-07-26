FROM python:3.12.8-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system vpnsale && adduser --system --ingroup vpnsale --home /home/vpnsale vpnsale
COPY requirements-dev.txt ./requirements.txt
RUN chmod 0644 ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip==24.3.1 \
    && pip install --no-cache-dir -r requirements.txt
COPY --chown=vpnsale:vpnsale apps/worker ./apps/worker
COPY --chown=vpnsale:vpnsale apps/api ./apps/api
COPY --chown=vpnsale:vpnsale packages ./packages
RUN chmod -R u+rwX,go+rX /app/apps/worker /app/apps/api /app/packages
ENV PYTHONPATH=/app/apps/worker/src:/app/apps/api/src:/app/packages/domain/src:/app/packages/panel-adapters/src:/app/packages/payment-adapters/src
USER vpnsale
STOPSIGNAL SIGTERM
CMD ["python", "-m", "platform_worker.main"]
