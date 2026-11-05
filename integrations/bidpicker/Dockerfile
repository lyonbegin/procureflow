FROM python:3.11-slim
WORKDIR /app
COPY integrations /app/integrations
RUN pip install --no-cache-dir fastapi==0.115.12 "uvicorn[standard]==0.34.2" "psycopg[binary]==3.2.9"
EXPOSE 8000
CMD ["uvicorn", "integrations.bidpicker.bridge:app", "--host", "0.0.0.0", "--port", "8000"]
