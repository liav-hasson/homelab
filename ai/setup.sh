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
  echo "NOTE: COMFY_DIR is not set. Defaulting to ./workspace/runpod-slim/ComfyUI"
  COMFY_DIR=/workspace/runpod-slim/ComfyUI
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

mkdir -pv "$COMFY_DIR"/{models/{checkpoints,vae,loras,upscale_models,controlnet,ultralytics/bbox},custom_nodes,user/__manager}

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
echo "Downloading VAEs..."
echo "============================================"

echo "Downloading VAE: sdxl-vae-fp16-fix..."
if ! skip_if_exists "$MODELS_DIR/vae/sdxl.vae.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/vae/sdxl.vae.safetensors" \
    "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors" \
  && echo "✓ Installed VAE: sdxl-vae-fp16-fix" \
  || mark_failed "VAE: sdxl-vae-fp16-fix"
fi

echo ""
echo "Downloading VAE: SDXL Anime VAE Dec-only B3..."
if ! skip_if_exists "$MODELS_DIR/vae/SDXL Anime VAE Dec-only B3.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/vae/SDXL Anime VAE Dec-only B3.safetensors" \
    "https://huggingface.co/Anzhc/Anzhcs-VAEs/resolve/main/SDXL%20Anime%20VAE%20Dec-only%20B3.safetensors" \
  && echo "✓ Installed VAE: SDXL Anime VAE Dec-only B3" \
  || mark_failed "VAE: SDXL Anime VAE Dec-only B3"
fi

# =============================================================================
#   CUSTOM NODES
# =============================================================================
echo ""
echo "Downloading custom nodes..."
echo "============================================"

# Helper: clone a node repo and optionally install requirements
# Usage: install_node "name" "git_url" [has_requirements] [has_install_py]
install_node() {
  local name="$1" url="$2" has_reqs="${3:-false}" has_install="${4:-false}"
  local dir_name
  dir_name="$(basename "$url" .git)"

  echo ""
  echo "Installing $name..."
  if skip_if_exists "$COMFY_DIR/custom_nodes/$dir_name"; then
    return 0
  fi

  if ! git clone "$url" "$COMFY_DIR/custom_nodes/$dir_name"; then
    mark_failed "Custom Node: $name"
    return 1
  fi

  if [[ "$has_reqs" == "true" ]] && [[ -f "$COMFY_DIR/custom_nodes/$dir_name/requirements.txt" ]]; then
    pip install -r "$COMFY_DIR/custom_nodes/$dir_name/requirements.txt" -q \
      || mark_failed "Custom Node (deps): $name"
  fi

  if [[ "$has_install" == "true" ]] && [[ -f "$COMFY_DIR/custom_nodes/$dir_name/install.py" ]]; then
    (cd "$COMFY_DIR/custom_nodes/$dir_name" && python3 install.py) \
      || mark_failed "Custom Node (install): $name"
  fi

  echo "✓ Installed $name"
}

# --- Core management ---
install_node "ComfyUI-Manager" \
  "https://github.com/ltdrdata/ComfyUI-Manager.git"

# Set ComfyUI-Manager security level to weak so git URL installs are allowed via UI
if [[ -f "$MANAGER_CONFIG" ]]; then
  sed -i 's/security_level = .*/security_level = weak/' "$MANAGER_CONFIG"
  echo "✓ ComfyUI-Manager: security level set to weak"
fi

# --- Impact Pack suite (FaceDetailer, UltralyticsDetectorProvider) ---
install_node "ComfyUI-Impact-Pack" \
  "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git" true true

install_node "ComfyUI-Impact-Subpack" \
  "https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git" true true

# --- Workflow utility nodes ---
install_node "ComfyUI-Custom-Scripts (pysssss)" \
  "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git"

install_node "rgthree-comfy" \
  "https://github.com/rgthree/rgthree-comfy.git" true

install_node "ComfyUI-Easy-Use" \
  "https://github.com/yolain/ComfyUI-Easy-Use.git" true

install_node "ComfyUI-Crystools" \
  "https://github.com/crystian/ComfyUI-Crystools.git" true

install_node "ComfyUI_UltimateSDUpscale" \
  "https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git"

install_node "Comfyroll Studio" \
  "https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes.git"

install_node "ComfyUI-Image-Saver" \
  "https://github.com/alexopus/ComfyUI-Image-Saver.git" true

install_node "ComfyUI-EasyColorCorrector" \
  "https://github.com/regiellis/ComfyUI-EasyColorCorrector.git" true

# --- Nodes required by new workflow subgraphs ---
install_node "cg-use-everywhere (Anything Everywhere)" \
  "https://github.com/chrisgoringe/cg-use-everywhere.git"

install_node "ComfyUI_Mira (Logic NOT)" \
  "https://github.com/mirabarukaso/ComfyUI_Mira.git" true

install_node "ComfyUI-KJNodes (Text Concatenate)" \
  "https://github.com/kijai/ComfyUI-KJNodes.git" true

install_node "comfyui-lopi999-nodes" \
  "https://github.com/LaVie024/comfyui-lopi999-nodes.git" true

# =============================================================================
#   UPSCALE MODELS
# =============================================================================
echo ""
echo "Downloading upscale models..."
echo "============================================"

echo "Downloading 2x-AnimeSharpV4_RCAN..."
if ! skip_if_exists "$MODELS_DIR/upscale_models/2x-AnimeSharpV4_RCAN.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/upscale_models/2x-AnimeSharpV4_RCAN.safetensors" \
    "https://huggingface.co/Kim2091/2x-AnimeSharpV4/resolve/main/2x-AnimeSharpV4_RCAN.safetensors" \
  && echo "✓ Installed 2x-AnimeSharpV4_RCAN" \
  || mark_failed "Upscaler: 2x-AnimeSharpV4_RCAN"
fi

# =============================================================================
#   CONTROLNET MODELS
# =============================================================================
echo ""
echo "Downloading ControlNet models..."
echo "============================================"

echo "Downloading noob-sdxl-controlnet-tile..."
if ! skip_if_exists "$MODELS_DIR/controlnet/noob-sdxl-controlnet-tile.safetensors"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/controlnet/noob-sdxl-controlnet-tile.safetensors" \
    "https://huggingface.co/Eugeoter/noob-sdxl-controlnet-tile/resolve/main/noob-sdxl-controlnet-tile.safetensors" \
  && echo "✓ Installed noob-sdxl-controlnet-tile" \
  || mark_failed "ControlNet: noob-sdxl-controlnet-tile"
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
echo ""
echo "Downloading hand_yolov8n.pt..."
if ! skip_if_exists "$MODELS_DIR/ultralytics/bbox/hand_yolov8n.pt"; then
  curl "${CURL_OPTS[@]}" \
    -o "$MODELS_DIR/ultralytics/bbox/hand_yolov8n.pt" \
    "https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8n.pt" \
  && echo "✓ Installed hand_yolov8n.pt" \
  || mark_failed "YOLO: hand_yolov8n.pt"
fi

# =============================================================================
#   RESTART COMFYUI
# =============================================================================
# ComfyUI auto-starts when the pod boots, before this script runs.
# Custom nodes installed after that initial start are invisible until restart.
echo ""
echo "Restarting ComfyUI to load custom nodes..."
echo "============================================"
if pkill -f "python.*main.py" 2>/dev/null; then
  sleep 2
  cd "$COMFY_DIR"
  nohup python main.py --listen 0.0.0.0 >> /workspace/comfyui.log 2>&1 &
  echo "✓ ComfyUI restarted — refresh your browser tab"
else
  echo "NOTE: ComfyUI was not running — custom nodes will load on next start"
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