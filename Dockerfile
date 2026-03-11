FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PM3U_DATA_DIR=/app/data
ENV PM3U_HOST=0.0.0.0
ENV PM3U_PORT=5000
ENV PM3U_DEBUG=0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py cleanup_script.py README.md ./
COPY static ./static
COPY templates ./templates
COPY tests ./tests

RUN mkdir -p /app/data/shared_m3u_files

EXPOSE 5000

CMD ["python", "app.py"]
