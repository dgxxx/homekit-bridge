FROM python:3.12-slim

# Keep image lean: no build cache, single RUN layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

# Install the package (production deps only, no dev extras)
RUN pip install --no-cache-dir .

CMD ["python", "-m", "homekit_bridge"]
