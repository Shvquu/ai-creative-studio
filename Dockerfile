# AI Creative Studio backend + dashboard (CPU image; GPU work happens in ComfyUI).
FROM node:22-bookworm-slim AS dashboard
WORKDIR /app/apps/dashboard
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/dashboard/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ACS__SERVER__HOST=0.0.0.0
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY mcp_server ./mcp_server
RUN pip install --no-cache-dir -e .
COPY configs ./configs
COPY engines/comfyui/workflows ./engines/comfyui/workflows
COPY engines/blender/scripts ./engines/blender/scripts
COPY workflows ./workflows
COPY scripts ./scripts
COPY --from=dashboard /app/apps/dashboard/dist ./apps/dashboard/dist
VOLUME ["/app/assets", "/app/data"]
EXPOSE 8420
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://127.0.0.1:8420/api/health || exit 1
CMD ["python", "-m", "backend.cli", "serve"]
