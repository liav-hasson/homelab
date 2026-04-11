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

### Troubleshooting

#### If Comfyui crashes

```bash
cd /workspace/runpod-slim/ComfyUI
source .venv-cu128/bin/activate
python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header
```

### Prompts

#### Prompts structure

**Follow this order**: [number of characters], [character name], [artist tags], [scene/environment/camera], [action], [expression], [items], [quality tags]

Use Danbooru-style tags. Artist tags use the `artist:` prefix (e.g., `artist:wlop`).
Remove underscores from Danbooru tags and escape parentheses with backslash: `lucy \(cyberpunk\)`.

#### Positive prompt (NoobAI-XL)

**Do NOT use `score_` tags** with NoobAI/Illustrious — they don't work on this model family. Use NovelAI-style quality tags instead.

```
masterpiece, best quality, newest, absurdres, highres, very awa,
<your subject and scene here>

# Test prompts:
[base], 1girl, long silver hair, blue eyes, looking at viewer, soft smile, close-up portrait, detailed face, rim lighting, white background
[base], 1girl, brown hair, ponytail, school uniform, pleated skirt, full body, standing, arms at sides, simple background, white background
[base], 1girl, blonde hair, holding a book with both hands, reading, sitting at desk, indoors, detailed hands, fingers
[base], 1girl, red hair, short hair, running, dynamic pose, outdoors, wind, motion blur background, city street
[base], 1girl, black hair, long hair, standing in a field of flowers, cherry blossoms, spring, soft sunlight, bokeh, looking at viewer
```

#### Base negative prompt (NoobAI-XL)

The new workflow uses `zero_out_negative_conditioning` (ON by default), which means negative prompts are zeroed out and unused. Keep it on unless you have edge cases where negative prompting helps. If you turn it off, use:

```
nsfw, worst quality, old, early, low quality, lowres, signature, username, logo, bad hands, mutated hands,
mammal, anthro, furry, ambiguous form, feral, semi-anthro
```

### Tips

- When hands are visible in the scene, strengthen with: `(detailed hands:1.2), (anatomically correct:1.1), five fingers`
- `very awa` is a NoobAI-specific aesthetic tag that improves overall quality
- For artist mixes, combine artists with 100+ Danbooru posts before Oct 2024
- Enable text autocomplete in `settings > pysssss` and use a Danbooru CSV for tag autocompletion

#### KSampler settings (NoobAI-XL vPred)

| Parameter | Recommended |
|---|---|
| Steps | 20–35 |
| CFG | 3.5–5.5 |
| Sampler | `euler` / `euler_ancestral` / `euler_cfg_pp` / `res_multistep_ancestral_cfg_pp` |
| Scheduler | `sgm_uniform` / `normal` / `kl_optimal` / `beta` |
| control_after_generate | randomize |

**⚠️ Avoid `karras` scheduler for vPred models** — it causes oversaturation. `dpmpp_2m` may also cause subtle artifacts with vPred; prefer Euler-family samplers.

#### HiresFix settings

| Parameter | Recommended |
|---|---|
| Steps | 15–25 |
| Sampler | `gradient_estimation_cfg_pp` |
| Scheduler | `normal` / `sgm_uniform` |
| Upscale factor | 1.25x–1.75x (2x+ requires RAUNet) |