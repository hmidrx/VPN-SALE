FROM python:3.12-slim
WORKDIR /app
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY apps/telegram-bot/src ./apps/telegram-bot/src
ENV PYTHONPATH=/app/apps/telegram-bot/src
CMD ["python", "-m", "telegram_bot.main"]
