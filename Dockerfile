FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium
RUN python -c "import os; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); chrome=p.chromium.executable_path; assert os.path.isfile(chrome),chrome; os.symlink(chrome, '/usr/local/bin/chromium'); p.stop()"
COPY . .
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
