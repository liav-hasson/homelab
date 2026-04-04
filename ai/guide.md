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

**Follow this order**: [quality tags], [subject], [character details], [scene], [aesthetic tags]

#### Positive prompt (NoobAI-XL)

```
score_9, score_8_up, score_7_up, masterpiece, best quality, newest, absurdres, highres, very awa, source_anime,
<your subject and scene here>

# Test prompts:
[base], 1girl, long silver hair, blue eyes, looking at viewer, soft smile, close-up portrait, detailed face, rim lighting, white background
[base], 1girl, brown hair, ponytail, school uniform, pleated skirt, full body, standing, arms at sides, simple background, white background
[base], 1girl, blonde hair, holding a book with both hands, reading, sitting at desk, indoors, detailed hands, fingers
[base], 1girl, red hair, short hair, running, dynamic pose, outdoors, wind, motion blur background, city street
[base], 1girl, black hair, long hair, standing in a field of flowers, cherry blossoms, spring, soft sunlight, bokeh, looking at viewer

[base], 1girl, brown hair, ponytail, school uniform, sailor collar, upper body, looking at viewer, slight smile, outdoors, cherry blossoms, bokeh, soft lighting
[base], 1girl, brown hair, ponytail, school uniform, pleated skirt, holding book, both hands, reading, sitting, classroom, window, afternoon light, detailed hands
[base], 1girl, brown hair, ponytail, school uniform, reaching out, palm facing viewer, close-up, expressive eyes, determined expression, simple background, white background
```


#### Base negative prompt (NoobAI-XL)

```
score_4, score_5, score_6, nsfw, worst quality, old, early, low quality, lowres, signature, username, logo,
(bad hands:1.4), (extra fingers:1.4), (missing fingers:1.4), (deformed hands:1.3), (malformed hands:1.3), fused fingers,
mammal, anthro, furry, ambiguous form, feral, semi-anthro
```

#### Tips

- When hands are visible in the scene, strengthen with: `(detailed hands:1.2), (anatomically correct:1.1), five fingers`
- Score tags (`score_9` etc.) are mandatory for NoobAI-XL — they replace `masterpiece`-style tags from older models
- `very awa` is a NoobAI-specific aesthetic tag that improves overall quality

#### KSampler settings (NoobAI-XL vPred)

| Parameter | Value |
|---|---|
| Steps | 32 |
| CFG | 5 |
| Sampler | dpmpp_2m |
| Scheduler | karras |
| control_after_generate | randomize |