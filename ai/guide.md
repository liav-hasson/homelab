# Usage guide and utils

## Startup guide

### Test script locally

```bash
# Create a local test workspace
mkdir -p ~/comfyui-test

# Download the script
curl -o ~/comfyui-test/setup.sh https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/setup.sh

# Override the path and run
COMFY_DIR=~/comfyui-test bash ~/comfyui-test/setup.sh
```

### Start a pod with the init script

1. **Get the scripts `githubusercontent` url**: `https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/BRANCH/PATH/TO/FILE`

    ```txt
    https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/setup.sh
    ```

