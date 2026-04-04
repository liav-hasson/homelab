#!/bin/bash
# =============================================================================
# RunPod ComfyUI Setup Script
# =============================================================================
# Usage: paste the raw GitHub URL of this file into RunPod's
#        "On-Start Script" field when launching your pod.
# 
# Assumed base image: comfyui-latest (ComfyUI lives at /workspace/ComfyUI)
# =============================================================================

# NOTE: Intentionally no `set -e` — we want to continue on failure and
#       report a summary at the end instead of aborting mid-setup.

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

# Make sure necessary sub directories exist and set environment vars
CURL_OPTS=(-L --progress-bar --retry 3 --retry-delay 10 -C -) # common curl flags
COMFY_DIR="$(cd "$COMFY_DIR" && pwd)"                         # make sure to use absolute path

MODELS_DIR="$COMFY_DIR/models"
MANAGER_CONFIG_DIR="$COMFY_DIR/user/__manager"
MANAGER_CONFIG="$MANAGER_CONFIG_DIR/config.ini"

mkdir -pv "$COMFY_DIR"/{models/{checkpoints,vae,ultralytics/bbox,custom_nodes},custom_nodes,user/__manager}

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

# Tracks any installs that failed during the run
FAILED_INSTALLS=()

# Call at the end of an install block on failure.
# Usage: mark_failed "Human-readable name"
mark_failed() {
  local name="$1"
  echo "✗ FAILED: $name — skipping and continuing..."
  FAILED_INSTALLS+=("$name")
}

# Returns 0 (skip) if the path already exists, 1 (proceed) if it doesn't.
skip_if_exists() {
  local install_path="$1"
  
  if [[ -e "$install_path" ]]; then
    echo "✓ Already exists, skipping installation..."
    return 0  # signal to skip
  else
    echo "✗ Not found, installing..."
    return 1  # signal to proceed
  fi
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
    "https://civitai.com/api/download/models/1190596?type=Model&format=SafeTensor&size=full&fp=bf16" \
  && echo "✓ Installed checkpoint: NoobAI-XL vPred 1.0" \
  || mark_failed "Checkpoint: NoobAI-XL vPred 1.0"
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
    "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors" \
  && echo "✓ Installed VAE: sdxl-vae-fp16-fix" \
  || mark_failed "VAE: sdxl-vae-fp16-fix"
fi

# =============================================================================
#   CUSTOM NODES
# =============================================================================
echo ""
echo "Downloading custom nodes..."
echo "============================================"

# 1. ComfyUI Manager — lets you install more nodes from the UI
echo "Installing ComfyUI-Manager..."
if ! skip_if_exists "$COMFY_DIR/custom_nodes/ComfyUI-Manager"; then
  if git clone https://github.com/ltdrdata/ComfyUI-Manager.git "$COMFY_DIR/custom_nodes/ComfyUI-Manager"; then
    echo "✓ Installed ComfyUI-Manager"

    # Set ComfyUI-Manager security level to weak so git URL installs are allowed via UI
    if [[ -f "$MANAGER_CONFIG" ]]; then
      sed -i 's/security_level = .*/security_level = weak/' "$MANAGER_CONFIG"
    fi
    echo "✓ ComfyUI-Manager: security level set to weak (allows git URL installs)"
  else
    mark_failed "Custom Node: ComfyUI-Manager"
  fi
fi

# 2. ComfyUI-Impact-Pack — FaceDetailer and hand detection nodes
echo ""
echo "Installing ComfyUI-Impact-Pack..."
if ! skip_if_exists "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack"; then
  if git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack" \
    && pip install -r "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack/requirements.txt" -q \
    && (cd "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Pack" && python3 install.py); then
    echo "✓ Installed ComfyUI-Impact-Pack (FaceDetailer)"
  else
    mark_failed "Custom Node: ComfyUI-Impact-Pack"
  fi
fi

# 3. ComfyUI-Impact-Subpack — required for UltralyticsDetectorProvider (YOLO detectors)
#    This is separate from Impact-Pack since v8.0 and must be installed manually.
echo ""
echo "Installing ComfyUI-Impact-Subpack..."
if ! skip_if_exists "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Subpack"; then
  if git clone https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Subpack" \
    && pip install -r "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Subpack/requirements.txt" -q \
    && (cd "$COMFY_DIR/custom_nodes/ComfyUI-Impact-Subpack" && python3 install.py); then
    echo "✓ Installed ComfyUI-Impact-Subpack (UltralyticsDetectorProvider)"
  else
    mark_failed "Custom Node: ComfyUI-Impact-Subpack"
  fi
fi

# =============================================================================
#   ULTRALYTICS DETECTION MODELS (YOLO)
# =============================================================================
echo ""
echo "Downloading YOLO detection models..."
echo "============================================"

# Face detector — used by FaceDetailer for face region detection + refinement
echo "Downloading face_yolov8n.pt..."
if ! skip_if_exists "$MODELS_DIR/ultralytics/bbox/face_yolov8n.pt"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/ultralytics/bbox/face_yolov8n.pt" \
    "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8n.pt" \
  && echo "✓ Installed face_yolov8n.pt" \
  || mark_failed "YOLO: face_yolov8n.pt"
fi

# Hand detector — used by FaceDetailer (hand pass) to detect and refine hands/fingers
echo "Downloading hand_yolov8n.pt..."
if ! skip_if_exists "$MODELS_DIR/ultralytics/bbox/hand_yolov8n.pt"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/ultralytics/bbox/hand_yolov8n.pt" \
    "https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8n.pt" \
  && echo "✓ Installed hand_yolov8n.pt" \
  || mark_failed "YOLO: hand_yolov8n.pt"
fi

# =============================================================================
#   SUMMARY
# =============================================================================
echo ""
echo "============================================"
if [[ ${#FAILED_INSTALLS[@]} -eq 0 ]]; then
  echo "  ✓ All installs completed successfully."
  echo "  ComfyUI is ready. Happy generating!"
else
  echo "  NOTE: Setup finished with ${#FAILED_INSTALLS[@]} failed install(s):"
  for item in "${FAILED_INSTALLS[@]}"; do
    echo "    - $item"
  done
  echo ""
  echo "  ComfyUI may still work — check above for details."
fi
echo "============================================"