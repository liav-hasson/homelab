## About
This is a txt2img workflow intended for NoobAI and Illustrious models. It is firstly designed to line up the prompt properly, in this particular order:

`[artist tags], [gentags], [quality tags]`

It is also designed for further image manipulation, before and after, with LoRA and ControlNet, and with FaceDetailer and Upscaler. By default, this just does straight up txt2img. Finally, it saves all image generation metadata (models, prompts, sampler settings, hiresfix, resolution) into an A1111-format PNG chunk using the Image Saver node.

I **highly** recommend turning on fast toggles in rgthree-comfy's settings for this workflow.

Another thing I recommend doing with this workflow when you start out, is to simply just to run one generation, not changing anything in the workflow, so that you can get a sense on how it all works and fits together.

### ASSUMPTIONS TO THE END USER (YOU)
<ol>
<li>
I assume that you are relatively competent enough with ComfyUI and can troubleshoot any issue(s) you have with this workflow by yourself.
<ol><li>This includes not using the Desktop edition of ComfyUI (please use the proper GitHub version or Portable), and that you are competent enough to install and update all custom node suites and update ComfyUI itself.</li></ol></li>
<li>I assume that you are competent with -booru style tags and can make effective usage of them with prompts and artist tags. This workflow assumes you will perform a strict, -booru style tag prompting structure only, as that is how NoobAI and Illustrious models should operate.</li>
<li>I assume that you are working with PROPER models (base NoobAI, base Illustrious, good finetunes like mdnt vpred or ΣΙΗ) and not shitmixes, ESPECIALLY NOT WAI!</li>
</ol>

### ACTUALLY GOOD MODELS
* [NoobAI vPred Base v1.0](https://civitai.com/models/833294/noobai-xl-nai-xl)
* [NoobAI vPred 28r](https://huggingface.co/abfauhwf/testmodels/blob/main/noob_v_28r_checkpoint-e4_s23000.safetensors)
* [ChenkinNoob](https://huggingface.co/ChenkinNoob/ChenkinNoob-XL-V0.2/resolve/main/ChenkinNoob-XL-V0.2.safetensors)
* [MDNT NAI-XL vPred](https://civitai.com/models/1209786/mdntnai-xlvpred)
* [ΣΙΗ](https://civitai.com/models/1217645)
* [LunarCherryMix🍒](https://civitai.com/models/1412760)
* [Seele](https://civitai.com/models/1445275/seele-noobai-sdxl)

### ETC. MODELS USED
* [SDXL Anime VAE Dec-only B3](https://huggingface.co/Anzhc/Anzhcs-VAEs/resolve/main/SDXL%20Anime%20VAE%20Dec-only%20B3.safetensors)
* [2x-AnimeSharpV4_RCAN](https://huggingface.co/Kim2091/2x-AnimeSharpV4/blob/main/2x-AnimeSharpV4_RCAN.safetensors)
* [noob-sdxl-controlnet-tile](https://huggingface.co/Eugeoter/noob-sdxl-controlnet-tile/blob/main/noob-sdxl-controlnet-tile.safetensors)

## Prompts
As stated before, I assume that you are prompting in -booru tags only. I recommend going to `settings > pysssss` and turning on text autocomplete, using a Danbooru or e621 csv to obtain tags for autocompletion. Stick to using minimal quality tags, as too much can bias the model's outputs, and also ruins some artist mixes.

The same applies to negative prompts. You will *not* make outputs better by slapping on 10,000 quality tags and other various pieces of horseshit into the negative prompt. By default, I have left `zero_out_negative_conditioning` as ON. I recommend keeping it this way unless if you absolutely need to use the negative prompt for any edge cases where it can be helpful. You can also turn it off and leave the negative prompt blank, both will produce slightly different outputs.

**Do not use `score_` tags with NoobAI/Illustrious. They DO NOT WORK!** NoobAI/Illustrious use NovelAI-style quality tags.

For the gentags, you can perform wildcards, and insert wildcards. To do wildcards within the node, simply do, for example:
`{cat girl|fox girl|wolf girl}`, And the output will be only one of the three, such as just `cat girl` or just `fox girl`.

For artist mixes, there is the large text switch node that allows for us to index through any of 10 artist mixes, such as setting it to 5 for the fifth artist mix in the list, and so on. There is also a bank of some other mixes to put into the multiline string fields of the switch. My suggestion is to just play around with these mixes, don't use LoRA or anything else, let the model's actual built-in knowledge guide it to different styles on it's own. If you would like to produce your own artist mixes, go onto Danbooru/e621 and select any artist tag that has at least over 100 posts prior to October 2024 Chenkin may support more recent artists, up to 2025, but I'm uncertain of the specifics.

## Model Patches
There is the **Model Patches** subgraph node in the Model Setup group, which contains five core model patch nodes to utilize, which on the face of it, can be turned on or off. Enter the subgraph to change more specific settings with the model patches.

## Sampler Settings
I have setup, by default, some "sane" settings for all the ksamplers, but I will go over them in more detail here. These are just suggestions, but based on my heavy usage of NoobAI, they seem to be some of the best options overall that I'd recommend to newcomers or for people who aren't certain what settings to use.

I recommend sticking between 20-35 steps for the Initial KSampler (unless if you are using a low-step LoRA), and sticking between 15-25 steps for HiresFix. For hiresfix, keep the upscale factor between 1.25x to 1.75x, as 2x or higher causes issues, requiring the usage of RAUNet instead. You may also just use the latent HiresFix node and set the upscale to 1.00x to have a simple two-pass KSampler process instead of also increasing resolution.

### Sampler Choice
For the initial KSampler, I recommend any one of these:
* `euler` / `euler_ancestral` (and their `cfg_pp` variants)
* `res_multistep_ancestral_cfg_pp`
* `dpmpp_2s_ancestral_cfg_pp` (note: second-order sampler, will take 2x as long per step, also note that it takes a bit of a higher `cfg` than most `cfg_pp` samplers, probably around 2.5)
* `sa_solver_pece`
* `res_2s_ode` (requires the `RES4LYF` node suite, also a second-order sampler)
* `gradient_estimation_cfg_pp`
* `seeds_2` (also a second-order sampler)

All of these samplers are fairly good for Noob, and each sort of offer their own flair. Euler and Euler Ancestral are the normal go-to choices and work rather well. I found myself liking the colors that RES Multistep CFG++ provides, and DPM++ 2s a CFG++ by default has a foggy texture, works best if CFG is turned up a bit more or latent hiresfix is used instead of img upscale hiresfix. `sa_solver_pece` seems to increase the consistency of anatomy.

For hiresfix, I recommend just sticking with `gradient_estimation_cfg_pp` or it's non-CFG++ variant. Works very well for hiresfix overall.

### Scheduler Choice
I recommend any one of these schedulers for the initial KSampler:
* `sgm_uniform` / `normal` (both are about the same scheduler but SGM Uniform does not use the model to get sigmas)
* `kl_optimal` (very good for v-prediction)
* `beta` (seems to play very nicely with any ancestral sampler)
* `zeta` (a bit of an experimental choice, but seems to work well)

I absolutely do NOT recommend using `karras` for v-prediction models at all. `exponential` may work sometimes but isn't very good as a scheduler for Noob/Illustrious as the ones mentioned here. `linear_quadratic` spends too much time in high sigmas for SDXL's liking, so it produces very foggy images. For Hiresfix, I just recommend sticking with `normal` or `sgm_uniform`. Note however that `linear_quadratic` may work better for RF models.

### HiresFix
This is where things get a little complicated to explain, but I'll try my best. There are two different ways of doing HiresFix, upscaling the latent itself, and then upscaling the image from the initial KSampler to then upscale that, essentially an img2img pass. Both have their benefits and drawbacks, latent upscale more directly changes the image. It is quicker and more VRAM-efficient because it doesn't need to VAE decode > upscale image > VAE Encode, but image upscale HiresFix may introduce less artifacting and is more deterministic, not changing up the image as much as latent HiresFix. Feel free to just play around and switch between the two.

You may have noticed the `use_global_seed` boolean widget on the subgraph node for HiresFix. This is intentional; using a different seed for HiresFix is like using a variation seed, it doesn't drastically change the image, but it changes up some details and such. I'd recommend using it if you find an image that is *almost* perfect save for one or a few details, where you can then use the same global seed, but iterate with different HiresFix seeds.