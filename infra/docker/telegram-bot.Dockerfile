FROM python:3.12.8-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system vpnsale && adduser --system --ingroup vpnsale --home /home/vpnsale vpnsale
COPY requirements-dev.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip==24.3.1 \
    && pip install --no-cache-dir -r requirements.txt
COPY apps/telegram-bot ./apps/telegram-bot
COPY packages ./packages
ENV PYTHONPATH=/app/apps/telegram-bot/src:/app/packages/domain/src
USER vpnsale
STOPSIGNAL SIGTERM
CMD ["python", "-m", "telegram_bot.main"]
