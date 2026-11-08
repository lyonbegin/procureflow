FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY integrations /app/integrations
RUN pip install --no-cache-dir fastapi==0.115.12 "uvicorn[standard]==0.34.2" "psycopg[binary]==3.2.9"
CMD ["sh", "-c", "exec uvicorn integrations.bidpicker.bridge:app --host 0.0.0.0 --port ${PORT:-8000}"]
