FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend /app/backend

RUN if [ -f requirements.txt ]; then \
      pip install --no-cache-dir -r requirements.txt; \
    elif [ -f pyproject.toml ]; then \
      pip install --no-cache-dir .; \
    else \
      pip install --no-cache-dir fastapi "uvicorn[standard]" psycopg[binary] redis; \
    fi

EXPOSE 8000

CMD ["sh", "-c", "uvicorn ${BACKEND_APP_MODULE:-app.main:app} --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]
