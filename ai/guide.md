# Usage guide and utils

## Startup guide

### Test script locally

```bash
# Create a local test workspace
mkdir -p ~/comfyui-test && cd ~/comfyui-test

# Download the script
curl -o ./setup.sh https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/setup.sh

# Run the script with env vars
CIVITAI_KEY=your-api-key COMFY_DIR=./ bash setup.sh
```

### Start a pod with the init script
