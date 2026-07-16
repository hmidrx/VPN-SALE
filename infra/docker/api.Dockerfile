FROM python:3.12-slim
WORKDIR /app
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY apps/api/src ./apps/api/src
COPY packages ./packages
ENV PYTHONPATH=/app/apps/api/src:/app/packages/panel-adapters/src:/app/packages/payment-adapters/src
CMD ["uvicorn", "platform_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
