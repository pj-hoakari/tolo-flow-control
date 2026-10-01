# syntax=docker/dockerfile:1.27@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
FROM ghcr.io/astral-sh/uv:0.12.21-trixie-slim@sha256:0b4686f3d71340b38a02d2b73b17620fe18d5c82c0f1c3c3a59996ed6e8e5b98 AS builder

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


FROM gcr.io/distroless/cc-debian13:nonroot@sha256:54df941ed0d06a1bd95ef5e0ce391fd8d9f94b64782dc9a60062727849ee3f97

COPY --from=builder /python /python
COPY --from=builder /app/.venv /app/.venv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

USER nonroot:nonroot

ENTRYPOINT ["/app/.venv/bin/python", "-m", "flow_control.rpc"]
