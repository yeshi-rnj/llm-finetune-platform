FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.lock backend/requirements-lora.txt /app/backend/
# Set --build-arg INSTALL_LORA=1 to add torch/transformers/peft (large; use a CUDA base image for GPU training)
ARG INSTALL_LORA=0
RUN pip install --no-cache-dir -r backend/requirements.lock \
 && if [ "$INSTALL_LORA" = "1" ]; then pip install --no-cache-dir -r backend/requirements-lora.txt; fi
COPY backend /app/backend
COPY frontend /app/frontend
RUN useradd -r -u 10001 app && mkdir /data && chown app /data
USER app
ENV HF_HOME=/data/hf APP_ENV=production HOST=0.0.0.0 PORT=8000 DATA_DIR=/data FRONTEND_DIR=/app/frontend
WORKDIR /app/backend
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health'%os.environ.get('PORT','8000'),timeout=3)"
CMD ["python", "-m", "app"]
