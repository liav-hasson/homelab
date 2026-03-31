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

echo "============================================"
echo "  Starting ComfyUI Setup Script..."
echo "============================================"

# =============================================================================
# 1. Pre-script setup 
# =============================================================================
echo ""
echo "Running pre-script setup..."
echo "============================================"

# set COMFY_DIR to a local path for local testing only
if [[ -z "$COMFY_DIR" ]]; then
  echo "NOTE: COMFY_DIR is not set. Defaulting to /workspace/ComfyUI"
  COMFY_DIR=/workspace/ComfyUI
else
  echo "Received COMFY_DIR environment variable: \"$COMFY_DIR\""
fi
COMFY_DIR="$(cd "$COMFY_DIR" && pwd)" # make sure to use absolute path

# CIVITAI_KEY must be provided via environment variable 
if [[ -z "$CIVITAI_KEY" ]]; then
  echo "ERROR: CIVITAI_KEY environment variable is required"
  echo "Usage: CIVITAI_KEY=your-api-key COMFY_DIR=path/to/comfy bash setup.sh"
  exit 1
else
  echo "Received CIVITAI_KEY environment variable: \"${CIVITAI_KEY:0:5}...\""
fi

# create necessary sub directories
mkdir -pv "$COMFY_DIR"/{models/{checkpoints,vae,custom_nodes},custom_nodes,user}
MODELS_DIR="$COMFY_DIR/models"

# Curl options for consistent retries and resume capability
CURL_OPTS=(-L --progress-bar --retry 3 --retry-delay 10 -C -)

# =============================================================================
# UTILITY FUNCTION: Skip installation if file exists
# =============================================================================

skip_if_exists() {
  local install_path="$1"
  
  if [[ -e "$install_path" ]]; then
    echo "✓ Already exists, Skipping installation..."
    return 0  # signal to skip this installation
  else
    echo "✗ Not found, installing..."
  fi
  
  return 1  # signal to proceed with installation
}

# =============================================================================
# 1. CHECKPOINTS (base models)
# =============================================================================
echo ""
echo "Downloading base model..."
echo "============================================"

if ! skip_if_exists "$MODELS_DIR/checkpoints/model.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -H "Authorization: Bearer $CIVITAI_KEY" \
    -o "$MODELS_DIR/checkpoints/model.safetensors" \
    "https://civitai.com/api/download/models/1190596?type=Model&format=SafeTensor&size=full&fp=bf16" || {
      echo "ERROR: Failed to download checkpoint"
      exit 1
    }
  echo "✓ Installed base model"
fi
# NOTE - Grabbed the install URL from browser console when clicked download

# =============================================================================
# 2. VAE
# =============================================================================
echo ""
echo "Downloading VAE: sdxl-vae-fp16-fix..."
echo "============================================"

if ! skip_if_exists "$MODELS_DIR/vae/sdxl.vae.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/vae/sdxl.vae.safetensors" \
    "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors" || {
      echo "ERROR: Failed to download VAE"
      exit 1
    }
  echo "✓ Installed VAE"
fi

# =============================================================================
# 3. LORAS (uncomment when needed)
# =============================================================================

# Example: curl "${CURL_OPTS[@]}" \
#   -H "Authorization: Bearer $CIVITAI_KEY" \
#   -o "$MODELS_DIR/loras/my_lora.safetensors" \
#   "https://civitai.com/api/download/models/XXXXXX"

# =============================================================================
# 4. UPSCALERS (uncomment when needed)
# =============================================================================

# Example: 4x-UltraSharp — great general purpose upscaler
# curl "${CURL_OPTS[@]}" \
#   -o "$MODELS_DIR/upscale_models/4x-UltraSharp.pth" \
#   "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth"

# =============================================================================
# 5. CONTROLNET MODELS (uncomment when needed)
# =============================================================================

# Example: ControlNet for SDXL — pose/depth/canny etc.
# curl "${CURL_OPTS[@]}" \
#   -o "$MODELS_DIR/controlnet/control-lora-canny-rank256.safetensors" \
#   "https://huggingface.co/stabilityai/control-lora/resolve/main/control-LoRAs-rank256/control-lora-canny-rank256.safetensors"

# =============================================================================
# 6. CUSTOM NODES
# =============================================================================
echo ""
echo "Downloading custom nodes..."
echo "============================================"

# ComfyUI Manager — lets you install more nodes from the UI
if ! skip_if_exists "$COMFY_DIR/custom_nodes/ComfyUI-Manager"; then
  git clone https://github.com/ltdrdata/ComfyUI-Manager.git "$COMFY_DIR/custom_nodes/"
  echo "✓ Installed custom nodes"
fi

# =============================================================================
# 7. COMFYUI CONFIG
# =============================================================================
echo ""
echo "Pulling ComfyUI config from GitHub repo..."
echo "============================================"

if ! skip_if_exists "$COMFY_DIR/user/comfyui-config.json"; then
  curl "${CURL_OPTS[@]}" \
    -o "$COMFY_DIR/user/comfyui-config.json" \
    "https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/comfyui-config.json" || {
      echo "ERROR: Failed to download config"
      exit 1
    }
  echo "✓ Installed comfyui config"
fi

# =============================================================================
# DONE
# =============================================================================
echo ""
echo "============================================"
echo "  ComfyUI is ready. Happy generating!"
echo "============================================"
