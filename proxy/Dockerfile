FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY wu_proxy ./wu_proxy
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-m", "wu_proxy.healthcheck"]
CMD ["python", "-m", "wu_proxy"]
