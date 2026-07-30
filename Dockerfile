FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

COPY pyproject.toml README.md ./
RUN mkdir -p app && touch app/__init__.py
RUN pip install --no-cache-dir .

COPY app ./app
COPY database ./database
COPY config ./config
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
