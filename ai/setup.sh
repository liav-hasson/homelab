#!/bin/bash
# =============================================================================
# RunPod ComfyUI Setup Script
# =============================================================================
# Usage: paste the raw GitHub URL of this file into RunPod's
#        "On-Start Script" field when launching your pod.
# 
# Assumed base image: comfyui-latest (ComfyUI lives at /workspace/ComfyUI)
# =============================================================================

set -e  # exit on any error

# =============================================================================
# 1. Pre-script setup 
# =============================================================================

echo "============================================"
echo "  ComfyUI Setup Script Starting..."
echo "============================================"
echo ""
echo "Running pre-script setup..."

# set COMFY_DIR to a local path for local testing only
COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"

# create sub directories
MODELS_DIR="$COMFY_DIR/models"
mkdir -pv "$MODELS_DIR"/{checkpoints,vae} # add more when needed (loras, upscale_models, controlnet)

# CIVITAI_KEY must be provided via environment variable 
if [[ -z "$CIVITAI_KEY" ]]; then
  echo "ERROR: CIVITAI_KEY environment variable is required"
  echo "Usage: CIVITAI_KEY=your-api-key COMFY_DIR=path/to/comfy bash setup.sh"
  exit 1
fi

# Curl options for consistent retries and resume capability
CURL_OPTS=(-L --progress-bar --retry 3 --retry-delay 10 -C -)

# =============================================================================
# 1. CHECKPOINTS (base models)
# =============================================================================

echo "Downloading base model..."

curl "${CURL_OPTS[@]}" \
  -H "Authorization: Bearer $CIVITAI_KEY" \
  -o "$MODELS_DIR/checkpoints/model.safetensors" \
  "https://civitai.com/api/download/models/1190596?type=Model&format=SafeTensor&size=full&fp=bf16" || {
    echo "ERROR: Failed to download checkpoint"
    exit 1
  }

# --- Add more checkpoints below as needed ---
# wget -q --show-progress \
#   -O "$MODELS_DIR/checkpoints/another_model.safetensors" \
#   "https://civitai.com/api/download/models/XXXXXX"

# =============================================================================
# 2. VAE
# =============================================================================

echo "Downloading VAE: sdxl-vae-fp16-fix..."

curl "${CURL_OPTS[@]}" \
  -o "$MODELS_DIR/vae/sdxl.vae.safetensors" \
  "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors" || {
    echo "ERROR: Failed to download VAE"
    exit 1
  }

# =============================================================================
# 3. LORAS  (uncomment and fill in when you have some)
# =============================================================================

# curl "${CURL_OPTS[@]}" \
#   -H "Authorization: Bearer $CIVITAI_KEY" \
#   -o "$MODELS_DIR/loras/my_lora.safetensors" \
#   "https://civitai.com/api/download/models/XXXXXX"

# curl "${CURL_OPTS[@]}" \
#   -H "Authorization: Bearer $CIVITAI_KEY" \
#   -o "$MODELS_DIR/loras/another_lora.safetensors" \
#   "https://civitai.com/api/download/models/YYYYYY"


# =============================================================================
# 4. UPSCALERS  (uncomment when needed)
# =============================================================================

# 4x-UltraSharp — great general purpose upscaler
# curl "${CURL_OPTS[@]}" \
#   -o "$MODELS_DIR/upscale_models/4x-UltraSharp.pth" \
#   "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth"

# RealESRGAN x4 — good for anime
# curl "${CURL_OPTS[@]}" \
#   -o "$MODELS_DIR/upscale_models/RealESRGAN_x4plus_anime_6B.pth" \
#   "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"


# =============================================================================
# 5. CONTROLNET MODELS  (uncomment when needed)
# =============================================================================

# ControlNet for SDXL — pose/depth/canny etc.
# curl "${CURL_OPTS[@]}" \
#   -o "$MODELS_DIR/controlnet/control-lora-canny-rank256.safetensors" \
#   "https://huggingface.co/stabilityai/control-lora/resolve/main/control-LoRAs-rank256/control-lora-canny-rank256.safetensors"


# =============================================================================
# 6. CUSTOM NODES  (uncomment when needed)
# =============================================================================

echo "Downloading custom nodes..."

cd "$COMFY_DIR/custom_nodes"

# ComfyUI Manager — lets you install more nodes from the UI
git clone https://github.com/ltdrdata/ComfyUI-Manager.git

# ComfyUI Impact Pack — useful for face detailing etc.
# git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git

# WAS Node Suite — extra utility nodes
# git clone https://github.com/WASasquatch/was-node-suite-comfyui.git

# =============================================================================
# 7. COMFYUI CONFIG
# =============================================================================

echo "Pulling ComfyUI config from GitHub repo..."

curl "${CURL_OPTS[@]}" \
  -o "$COMFY_DIR/extra_model_paths.yaml" \
  "https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/comfyui-config.json" || {
    echo "ERROR: Failed to download config"
    exit 1
  }


# =============================================================================
# DONE
# =============================================================================

echo "All done!"
echo ""
echo "Models downloaded:"
ls -lh "$MODELS_DIR/checkpoints/"
ls -lh "$MODELS_DIR/vae/"
echo ""
echo "ComfyUI is ready. Happy generating!"
