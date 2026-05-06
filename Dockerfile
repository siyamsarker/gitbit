FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    git-lfs \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN git lfs install --system

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["git-mirror"]
CMD ["--help"]
