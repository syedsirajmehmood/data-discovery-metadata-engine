FROM python:3.11-slim AS base

# psycopg2-binary avoids needing build-essential/libpq-dev in the runtime
# image; kept here only in case a future dependency needs a compiler.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY connectors /app/connectors
COPY agent /app/agent

RUN pip install --no-cache-dir .

# Local, data-plane-only state (cursors, dead-letter queue) -- never sent
# to the control plane. Mount a volume here in production so it survives
# pod restarts.
RUN mkdir -p /app/data/cursors /app/data/dead_letter
VOLUME ["/app/data"]

ENV DP_CURSOR_DIR=/app/data/cursors \
    DP_DEAD_LETTER_DIR=/app/data/dead_letter \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "agent.main"]
