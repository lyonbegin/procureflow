FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py api_v1.py drive_v1.py ./
COPY static ./static
ENV RELAY_DATA_DIR=/data
RUN mkdir -p /data
CMD ["sh","-c","uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
