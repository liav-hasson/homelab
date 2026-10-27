# LLM Proxy operations

LiteLLM holds every Usage Code (virtual key) and its spend; there is no admin UI or key service. All key management
is manual, through the API with the master key. Requirements: `docs/spec/llm-proxy.md` in the ankilabs docs.

## Access

```sh
kubectl -n ankilabs port-forward svc/llm-proxy 4000:80
export M=$(kubectl -n ankilabs get secret llm-proxy-admin -o jsonpath='{.data.LITELLM_MASTER_KEY}' | base64 -d)
```

Port-forwarding is not subject to the NetworkPolicy, which admits only AI Card Actions and Authorization.

## Usage Codes

Issue one code per person. `models` must list logical model names explicitly: an empty list allows every model.

```sh
curl -s localhost:4000/key/generate -H "Authorization: Bearer $M" -H 'Content-Type: application/json' \
  -d '{"key_alias":"<person>","max_budget":5,"models":["ankilabs-medium","ankilabs-tts"]}'
```

| Task | Request (`POST`, master key) |
| --- | --- |
| Check spend | `GET /key/info?key=<code>` (`spend`, `max_budget`, `blocked`) |
| Renew an exhausted code (same code, another $5) | `/key/update` with `{"key":"<code>","max_budget":<current + 5>}` |
| Block or unblock | `/key/block` or `/key/unblock` with `{"key":"<code>"}` |
| Replace a leaked code | Issue a new code with the same alias, then block the old one |

## Authorization service key

Authorization reads key information with its own key, never the master key. The key's value is generated into
`../authorization/secrets.yaml` (Secret `authorization-llm-proxy`); register that same value in LiteLLM once, after
Flux has applied the Secret:

```sh
S=$(kubectl -n ankilabs get secret authorization-llm-proxy -o jsonpath='{.data.LLM_PROXY_KEY}' | base64 -d)
curl -s localhost:4000/key/generate -H "Authorization: Bearer $M" -H 'Content-Type: application/json' \
  -d "{\"key\":\"$S\",\"key_alias\":\"authorization-service\",\"max_budget\":0,\"models\":[\"no-models\"],\"allowed_routes\":[\"/key/info\"]}" >/dev/null
curl -s "localhost:4000/key/info?key=$S" -H "Authorization: Bearer $M" | grep -o '"allowed_routes":\[[^]]*\]'; unset S
```

Verify with `/key/info` as above. Running the registration again fails harmlessly with `400` (key aliases must be
unique) and leaves the stored key unchanged. To rotate, generate a new value into the Secret, register it under a new
alias, restart Authorization, then delete the old key.

## Secrets

`secrets.yaml` holds four Secrets: `llm-proxy-providers` (provider API keys), `llm-proxy-elevenlabs`
(`ELEVENLABS_API_KEY`, for text-to-speech), `llm-proxy-admin` (master and salt keys), and `llm-proxy-database`
(the `litellm` Postgres role's password). Edit with `sops secrets.yaml`. A Secret change does not restart the pod: run
`kubectl -n ankilabs rollout restart deploy/llm-proxy` afterwards.
Never change `LITELLM_SALT_KEY`: it encrypts data in LiteLLM's database.

The chart's bootstrap Job creates the `litellm` role and database before every install and upgrade, and resets the
role's password to the Secret's value, so rotating that password is a Secret edit only.

## Models

Models are Helm values (`config.model_list` in `release.yaml`): a logical `model_name` maps to a provider model and
its default `reasoning_effort`. Keep logical names stable; renaming one means updating every key's `models`
allowlist. A provider model missing from LiteLLM's bundled cost map is priced at $0 and never draws down a budget, so
give it explicit `input_cost_per_token` and `output_cost_per_token`.

## Text-to-speech

`ankilabs-tts` is ElevenLabs `eleven_multilingual_v2`, served on `/v1/audio/speech` and charged to the same $5
budget as the chat models. Its price comes only from the bundled cost map: LiteLLM ignores a custom
`input_cost_per_character` for speech (LiteLLM #44200).

- Codes issued before text-to-speech need the model added: `/key/update` with
  `{"key":"<code>","models":["ankilabs-medium","ankilabs-tts"]}` (the list replaces the old one).
- After adding the real key and before turning on `ai_speech`, make one speech call with a code and check that
  `GET /key/info?key=<code>` shows `spend` above 0. A spend of 0 means budgets do not limit speech; leave the flag
  off. `dev/litellm-checks.sh` checks the same thing when `ELEVENLABS_API_KEY` is set.

## Upgrades

The image is pinned by hand. Before bumping it, take a dump of the `litellm` database, then run the same tag in the
dev stack and pass `dev/litellm-checks.sh`.
