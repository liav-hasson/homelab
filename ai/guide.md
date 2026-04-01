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

1. Set env var `CIVITAI_KEY` (mandatory): the CivitAI API key.
2. Set env var `COMFY_DIR` (optional): the `ComfyUI/` directory relative path (else, make sure the script runs one dir above `ComfyUI/`).
3. Start the pod and run:

```bash
    curl -o ./setup.sh https://raw.githubusercontent.com/liav-hasson/homelab/main/ai/setup.sh && \
    bash setup.sh
```

3. Monitor the script's execution (can take a few minutes).
4. If unable to load the workflow config, simply drag it manually to the UI.
5. After modifying the workflow config, make sure to export it (and push to github).

### Prompts

#### Prompts structure

**Follow this order**: [subject], [character details], [scene], [quality tags], [aesthetic tags]  
**Example**: masterpiece, best quality, newest, absurdres, highres, very awa,
1girl, long silver hair, blue eyes, school uniform, cherry blossoms,
looking at viewer, soft smile, detailed face, bokeh background

**For negative prompts**: follow official recommended negatives.  
**Example**: nsfw, worst quality, old, early, low quality, lowres, signature,
username, logo, bad hands, mutated hands, mammal, anthro, furry,
ambiguous form, feral, semi-anthro