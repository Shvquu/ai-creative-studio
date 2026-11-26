# ComfyUI with NVIDIA CUDA PyTorch (cu130, per ComfyUI docs/installation.md).
# Models are mounted from the host (never baked into the image).
FROM python:3.12-slim-bookworm
ARG COMFYUI_REF=master
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu130
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${COMFYUI_REF} https://github.com/Comfy-Org/ComfyUI.git /comfyui
WORKDIR /comfyui
RUN pip install --no-cache-dir torch torchvision torchaudio --extra-index-url ${TORCH_INDEX} \
    && pip install --no-cache-dir -r requirements.txt
EXPOSE 8188
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://127.0.0.1:8188/system_stats || exit 1
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
