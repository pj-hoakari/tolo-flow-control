# syntax=docker/dockerfile:1.29@sha256:572cebbc2b15e6f84c077742952674889cb63cd5e9b80abdffcbe587b6f19183
FROM ghcr.io/astral-sh/uv:0.13.8-trixie-slim@sha256:2e5596835973a75bed0d37a980625b5089e87ffbd1026f11012ca0fe254ccac5 AS builder

ENV UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY .python-version pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


FROM gcr.io/distroless/cc-debian13:nonroot@sha256:cc66d222f0a7ec996b78a99fe76a969bc80b539a5016ad866c14d1949bc6d0ab

COPY --from=builder /python /python
COPY --from=builder /app/.venv /app/.venv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

USER nonroot:nonroot

ENTRYPOINT ["/app/.venv/bin/python", "-m", "flow_control.rpc"]
