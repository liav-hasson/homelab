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

COMFY_DIR="/workspace/ComfyUI"
MODELS_DIR="$COMFY_DIR/models"

echo "============================================"
echo "  ComfyUI Setup Script Starting..."
echo "============================================"


# =============================================================================
# 1. CHECKPOINTS (base models)
# =============================================================================

echo "Downloading base model: WAI-illustrious-SDXL..."

mkdir -p "$MODELS_DIR/checkpoints"

wget -q --show-progress \
  -O "$MODELS_DIR/checkpoints/illustriousXL.safetensors" \
  "https://civitai.com/api/download/models/827184"

# --- Add more checkpoints below as needed ---
# wget -q --show-progress \
#   -O "$MODELS_DIR/checkpoints/another_model.safetensors" \
#   "https://civitai.com/api/download/models/XXXXXX"


# =============================================================================
# 2. VAE
# =============================================================================

echo "Downloading VAE: sdxl-vae-fp16-fix..."

mkdir -p "$MODELS_DIR/vae"

wget -q --show-progress \
  -O "$MODELS_DIR/vae/sdxl.vae.safetensors" \
  "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors"

# --- Add more VAEs below as needed ---
# wget -q --show-progress \
#   -O "$MODELS_DIR/vae/other_vae.safetensors" \
#   "https://huggingface.co/AUTHOR/REPO/resolve/main/FILE.safetensors"


# =============================================================================
# 3. LORAS  (uncomment and fill in when you have some)
# =============================================================================

# mkdir -p "$MODELS_DIR/loras"

# wget -q --show-progress \
#   -O "$MODELS_DIR/loras/my_lora.safetensors" \
#   "https://civitai.com/api/download/models/XXXXXX"

# wget -q --show-progress \
#   -O "$MODELS_DIR/loras/another_lora.safetensors" \
#   "https://civitai.com/api/download/models/YYYYYY"


# =============================================================================
# 4. UPSCALERS  (uncomment when needed)
# =============================================================================

# mkdir -p "$MODELS_DIR/upscale_models"

# 4x-UltraSharp — great general purpose upscaler
# wget -q --show-progress \
#   -O "$MODELS_DIR/upscale_models/4x-UltraSharp.pth" \
#   "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth"

# RealESRGAN x4 — good for anime
# wget -q --show-progress \
#   -O "$MODELS_DIR/upscale_models/RealESRGAN_x4plus_anime_6B.pth" \
#   "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"


# =============================================================================
# 5. CONTROLNET MODELS  (uncomment when needed)
# =============================================================================

# mkdir -p "$MODELS_DIR/controlnet"

# ControlNet for SDXL — pose/depth/canny etc.
# wget -q --show-progress \
#   -O "$MODELS_DIR/controlnet/control-lora-canny-rank256.safetensors" \
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

# Replace the URL below with the raw URL to your config file in your GitHub repo
# Example: https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/BRANCH/PATH/TO/FILE

wget -q \
  -O "$COMFY_DIR/extra_model_paths.yaml" \
  "https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/comfyui-config.json"


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
