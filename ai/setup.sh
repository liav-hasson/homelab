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
echo ""
echo "* NOTE: The script may take a few minutes to finish."

# =============================================================================
#   Pre-script setup 
# =============================================================================
echo ""
echo "Running pre-script setup..."
echo "============================================"

# Allow COMFY_DIR to be a local path for local testing
# Default terminal spawn is `/workspace/runpod-slim/`
# The script must be executed one directory above ComfyUI (if COMFY_DIR not set)
if [[ -z "$COMFY_DIR" ]]; then
  echo "NOTE: COMFY_DIR is not set. Defaulting to ./ComfyUI"
  COMFY_DIR=ComfyUI
else
  echo "Received COMFY_DIR environment variable: \"$COMFY_DIR\""
fi

# CIVITAI_KEY must be provided via environment variable 
if [[ -z "$CIVITAI_KEY" ]]; then
  echo "ERROR: CIVITAI_KEY environment variable is required"
  echo "Usage: CIVITAI_KEY=your-api-key COMFY_DIR=path/to/comfy bash setup.sh"
  exit 1
else
  echo "Received CIVITAI_KEY environment variable: \"${CIVITAI_KEY:0:5}...\""
fi

# create necessary sub directories and environment vars
CURL_OPTS=(-L --progress-bar --retry 3 --retry-delay 10 -C -) # common curl flags
COMFY_DIR="$(cd "$COMFY_DIR" && pwd)"                         # make sure to use absolute path

MODELS_DIR="$COMFY_DIR/models"
MANAGER_CONFIG_DIR="$COMFY_DIR/user/__manager"
MANAGER_CONFIG="$MANAGER_CONFIG_DIR/config.ini"

mkdir -pv "$COMFY_DIR"/{models/{checkpoints,vae,custom_nodes},custom_nodes,user/__manager}

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
#   CHECKPOINTS 
# =============================================================================
echo ""
echo "Downloading base model..."
echo "============================================"

if ! skip_if_exists "$MODELS_DIR/checkpoints/model.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -H "Authorization: Bearer $CIVITAI_KEY" \
    -o "$MODELS_DIR/checkpoints/model.safetensors" \
    "https://civitai.com/api/download/models/1190596?type=Model&format=SafeTensor&size=full&fp=bf16" || {
      echo "ERROR: Failed to download checkpoint (NoobAI-XL vPred 1.0)"
      exit 1
    }
  echo "✓ Installed checkpoint: NoobAI-XL vPred 1.0"
fi
# NOTE - Grabbed the install URL from browser console when clicked download

# =============================================================================
#   VAE
# =============================================================================
echo ""
echo "Downloading VAE: sdxl-vae-fp16-fix..."
echo "============================================"

if ! skip_if_exists "$MODELS_DIR/vae/sdxl.vae.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/vae/sdxl.vae.safetensors" \
    "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors" || {
      echo "ERROR: Failed to download VAE (sdxl-vae-fp16-fix)"
      exit 1
    }
  echo "✓ Installed VAE: sdxl-vae-fp16-fix"
fi

# =============================================================================
#   CUSTOM NODES
# =============================================================================
echo ""
echo "Downloading custom nodes..."
echo "============================================"

# 1. ComfyUI Manager — lets you install more nodes from the UI
if ! skip_if_exists "$COMFY_DIR/custom_nodes/ComfyUI-Manager"; then
  git clone https://github.com/ltdrdata/ComfyUI-Manager.git "$COMFY_DIR/custom_nodes/ComfyUI-Manager"
  echo "✓ Installed ComfyUI-Manager"
fi

# Set ComfyUI-Manager security level to weak so git URL installs are allowed via UI
# Since v3.38, config.ini lives in ComfyUI/user/__manager/ (not in custom_nodes)
# "Install via git URL" is a high-risk feature, requires security_level = weak
if [[ -f "$MANAGER_CONFIG" ]]; then
  sed -i 's/security_level = .*/security_level = weak/' "$MANAGER_CONFIG"
else
  echo -e "[default]\nsecurity_level = weak" > "$MANAGER_CONFIG"
fi
echo "✓ ComfyUI-Manager: security level set to weak (allows git URL installs)"

# ComfyUI-Impact-Pack — FaceDetailer and hand detection nodes (ADetailer equivalent for ComfyUI)
if ! skip_if_exists "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack"; then
  git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack"
  pip install -r "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack/requirements.txt" -q
  (cd "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack" && python3 install.py)
  echo "✓ Installed ComfyUI-Impact-Pack (FaceDetailer)"
fi

# =============================================================================
#   DONE
# =============================================================================
echo ""
echo "============================================"
echo "  ComfyUI is ready. Happy generating!"
echo "============================================"
