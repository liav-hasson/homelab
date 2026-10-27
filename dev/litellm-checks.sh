#!/usr/bin/env bash
# LiteLLM behaviour AnkiLabs relies on (docs/spec/llm-proxy.md#verified-behaviour). Run before bumping the image:
#   docker compose -f dev/compose.yaml up -d litellm   # after changing its image tag
#   dev/litellm-checks.sh
# Uses the dev stack's mock model and master key; it never calls a real provider, except for the text-to-speech checks,
# which run only when ELEVENLABS_API_KEY is set (for the dev stack too) and spend one short real ElevenLabs request.
set -u
P=${LITELLM_URL:-http://localhost:4000}
M=${LITELLM_MASTER_KEY:-sk-dev-master}
MODEL=${LITELLM_MODEL:-ankilabs-default}
FAILED=0

check() { # name, expected, actual
  if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1: expected '$2', got '$3'"; FAILED=1; fi
}
# Prints "<http status> <error type or field value>" for a request; $1 = field to read from a 200 body.
call() {
  local field=$1; shift
  curl -s -w '\n%{http_code}' "$@" | python3 -c '
import json, sys
*body, status = sys.stdin.read().split("\n")
try:
    d = json.loads("\n".join(body))
except ValueError:
    d = {}
err = d.get("error") if isinstance(d.get("error"), dict) else None
if err:
    print(status, err.get("type"))
elif sys.argv[1] == "-":
    print(status)
else:
    v = d
    for k in sys.argv[1].split("."):
        v = v.get(k) if isinstance(v, dict) else None
    print(status, v)' "$field"
}
admin() { curl -s "$P/$1" -H "Authorization: Bearer $M" -H 'Content-Type: application/json' -d "$2"; }
new_key() { admin key/generate "$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])'; }
chat() { call - "$P/v1/chat/completions" -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
  -d "{\"model\":\"${2:-$MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"; }

USER_KEY=$(new_key "{\"key_alias\":\"checks-user\",\"max_budget\":0.5,\"models\":[\"$MODEL\"]}")
SVC_KEY=$(new_key '{"key_alias":"checks-authorization","max_budget":0,"models":["no-models"],"allowed_routes":["/key/info"]}')

check "user key reads its own info" "200 checks-user" "$(call info.key_alias "$P/key/info" -H "Authorization: Bearer $USER_KEY")"
check "user key cannot generate keys" "401" "$(call - "$P/key/generate" -H "Authorization: Bearer $USER_KEY" -H 'Content-Type: application/json' -d '{}' | cut -d' ' -f1)"
check "service key reads a user key" "200 checks-user" "$(call info.key_alias "$P/key/info?key=$USER_KEY" -H "Authorization: Bearer $SVC_KEY")"
check "service key: unknown code" "404 not_found_error" "$(call - "$P/key/info?key=sk-not-a-key" -H "Authorization: Bearer $SVC_KEY")"
check "service key cannot run inference" "403" "$(chat "$SVC_KEY" | cut -d' ' -f1)"
check "service key cannot update keys" "403" "$(call - "$P/key/update" -H "Authorization: Bearer $SVC_KEY" -H 'Content-Type: application/json' -d "{\"key\":\"$USER_KEY\",\"max_budget\":100}" | cut -d' ' -f1)"
check "invalid code on inference" "401 token_not_found_in_db" "$(chat sk-not-a-key)"
check "model outside allowlist" "403 key_model_access_denied" "$(chat "$USER_KEY" not-an-allowed-model)"

admin key/block "{\"key\":\"$USER_KEY\"}" >/dev/null
check "blocked code visible to service key" "200 True" "$(call info.blocked "$P/key/info?key=$USER_KEY" -H "Authorization: Bearer $SVC_KEY")"
check "blocked code on inference" "401 auth_error" "$(chat "$USER_KEY")"
admin key/unblock "{\"key\":\"$USER_KEY\"}" >/dev/null

# The dev mock model is priced so that a couple of calls exhaust a $0.50 budget.
for _ in 1 2 3 4 5 6 7 8 9 10; do [ "$(chat "$USER_KEY")" = "200" ] || break; sleep 2; done
check "exhausted code on inference" "422 budget_exceeded" "$(chat "$USER_KEY")"
check "exhausted code still readable" "200 checks-user" "$(call info.key_alias "$P/key/info?key=$USER_KEY" -H "Authorization: Bearer $SVC_KEY")"

admin key/update "{\"key\":\"$USER_KEY\",\"max_budget\":5}" >/dev/null
sleep 2
check "raising max_budget reopens the code" "200" "$(chat "$USER_KEY")"

# Text-to-speech through ElevenLabs. Budgets apply only if LiteLLM records spend for speech, which comes from its
# bundled cost map alone (custom per-character prices are ignored, LiteLLM #44200): spend 0 means free audio.
if [ -n "${ELEVENLABS_API_KEY:-}" ]; then
  TTS=${LITELLM_TTS_MODEL:-ankilabs-tts}
  VOICE=${ELEVENLABS_VOICE_ID:-EXAVITQu4vr4xnSDxMaL}
  speech_body="{\"model\":\"$TTS\",\"input\":\"Hola, buenos dias.\",\"voice\":\"$VOICE\",\"response_format\":\"mp3\"}"
  positive() { python3 -c 'import sys
try: print("yes" if float(sys.argv[1]) > 0 else "no")
except ValueError: print("no")' "${1:-0}"; }
  # Prints "<http status> <error type>" for a speech request that should fail; $1 = key.
  speak_error() { call - "$P/v1/audio/speech" -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
    -d "$speech_body"; }

  # Any spend at all exhausts this budget, so the second call must be refused.
  TTS_KEY=$(new_key "{\"key_alias\":\"checks-tts\",\"max_budget\":0.000001,\"models\":[\"$TTS\"]}")
  out=$(curl -s -o /dev/null -D - -w '\n%{http_code} %{content_type} %{size_download}' "$P/v1/audio/speech" \
    -H "Authorization: Bearer $TTS_KEY" -H 'Content-Type: application/json' -d "$speech_body" | tr -d '\r')
  read -r status content_type size <<<"$(tail -n 1 <<<"$out")"
  cost=$(grep -i '^x-litellm-response-cost:' <<<"$out" | awk '{print $2}')
  check "speech returns MP3 audio" "200 audio/mpeg" "$status $content_type"
  check "speech audio is not empty" "yes" "$(positive "$size")"
  check "speech reports a cost (x-litellm-response-cost > 0)" "yes" "$(positive "$cost")"
  spend=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    spend=$(call info.spend "$P/key/info" -H "Authorization: Bearer $TTS_KEY" | cut -d' ' -f2)
    [ "$(positive "$spend")" = yes ] && break
    sleep 2
  done
  check "speech draws down the code's budget (/key/info spend > 0)" "yes" "$(positive "$spend")"
  if [ "$(positive "$spend")" != yes ]; then
    echo "FAIL  !!! LiteLLM recorded no spend for $TTS: budgets do NOT limit text-to-speech. Do not enable ai_speech."
  fi
  check "speech: model outside allowlist" "403 key_model_access_denied" "$(speak_error "$USER_KEY")"
  check "speech: exhausted code" "422 budget_exceeded" "$(speak_error "$TTS_KEY")"
  admin key/delete "{\"keys\":[\"$TTS_KEY\"]}" >/dev/null
else
  echo "SKIP  text-to-speech checks: ELEVENLABS_API_KEY is not set"
fi

# /key/info carries codes in its query string; LiteLLM's access log must redact it. Needs the dev container.
CONTAINER=${LITELLM_CONTAINER:-ankilabs-dev-litellm-1}
if command -v docker >/dev/null && [ -n "$(docker ps -q -f "name=^${CONTAINER}$")" ]; then
  leaked=absent
  docker logs "$CONTAINER" 2>&1 | grep -qF "${USER_KEY#sk-}" && leaked=present
  check "codes never reach LiteLLM's logs" "absent" "$leaked"
fi

admin key/delete "{\"keys\":[\"$USER_KEY\",\"$SVC_KEY\"]}" >/dev/null
exit $FAILED
