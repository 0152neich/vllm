ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY resources ./resources
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .

USER nobody
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
