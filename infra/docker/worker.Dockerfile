FROM python:3.12-slim
WORKDIR /app
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY apps/worker/src ./apps/worker/src
ENV PYTHONPATH=/app/apps/worker/src
CMD ["python", "-m", "platform_worker.main"]
