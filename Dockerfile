FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN echo "rebuild-20260826-v2" > /tmp/.cache-bust

COPY . .

EXPOSE 8000

CMD sh -c "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"
