# Usage guide and utils

## Startup guide

### Test script locally

```bash
# Create a local test workspace
mkdir -p ~/comfyui-test && cd ~/comfyui-test

# Download the script
curl -o ./setup.sh https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/setup.sh

# Run the script with env vars
CIVITAI_KEY=your-api-key COMFY_DIR=test-dir bash setup.sh
```

### Start a pod with the init script

1. Set env vars in the pod's template edit section (`CIVITAI_KEY` is mandatory).
2. Make sure to start the pod with `/workspace` as the root.
3. Start the pod and run:

    ```bash
    cd /workspace && \
    curl -o ./setup.sh https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/setup.sh && \
    bash setup.sh
    ```

4. Monitor the script's execution (takes a few minutes).
