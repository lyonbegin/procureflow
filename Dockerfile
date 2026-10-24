# Build the real React Flow application once; serve it from the existing FastAPI.
# Both API and worker services can use this image. No additional Railway service
# or runtime Node process is required.
FROM node:22-bookworm-slim AS studio-build
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund --package-lock=false
COPY frontend/ ./
RUN npm run test && npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium
COPY . .
COPY --from=studio-build /frontend/dist /app/static/studio
RUN python -c "import base64,io,tarfile,pathlib; p=pathlib.Path('/app/legacy_sources.tar.gz.b64'); b=base64.b64decode(p.read_text(encoding='ascii')); tarfile.open(fileobj=io.BytesIO(b),mode='r:gz').extractall('/app',filter='data')" \
    && python -m py_compile main.py g2b_feature_api.py g2b_feature_data.py worker.py legacy_import.py legacy/g2b_headless_collect.py legacy/kapt_headless_collect.py
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
