# Python-only G2B business API/Worker image. n8n is deployed separately.
# No Vite/React Flow build, JS workflow runner, or duplicate DAG engine.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium
COPY . .
RUN python -c "import base64,io,tarfile,pathlib; p=pathlib.Path('/app/legacy_sources.tar.gz.b64'); b=base64.b64decode(p.read_text(encoding='ascii')); tarfile.open(fileobj=io.BytesIO(b),mode='r:gz').extractall('/app',filter='data')" \
    && python -m py_compile main.py n8n_scenarios.py n8n_landing.py g2b_feature_api.py g2b_feature_data.py worker.py legacy_import.py legacy/g2b_headless_collect.py legacy/kapt_headless_collect.py
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
