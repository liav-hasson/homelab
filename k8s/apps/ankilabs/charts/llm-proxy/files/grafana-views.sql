-- Read-only views Grafana queries in LiteLLM's database, recreated after every install and upgrade.
-- They live in their own schema because LiteLLM's migrations own `public`. They expose Usage Code metadata and spend
-- only, never the key hash (`token`, `api_key`), prompts, responses or request metadata. A view runs with its owner's
-- rights, so the Grafana login (psql variable `grafana_role`) needs no grant on LiteLLM's tables.
CREATE SCHEMA IF NOT EXISTS grafana;
GRANT USAGE ON SCHEMA grafana TO :"grafana_role";

-- One row per Usage Code. Authorization's own key is not a Usage Code.
CREATE OR REPLACE VIEW grafana.usage_codes WITH (security_barrier) AS
SELECT
    t.key_alias,
    t.created_at,
    t.spend,
    t.max_budget,
    t.max_budget - t.spend AS remaining,
    coalesce(t.blocked, false) AS blocked,
    t.models,
    t.expires,
    (SELECT max(s."startTime") FROM public."LiteLLM_SpendLogs" AS s WHERE s.api_key = t.token) AS last_request_at
FROM public."LiteLLM_VerificationToken" AS t
WHERE t.key_alias IS DISTINCT FROM 'authorization-service';

-- One row per request LiteLLM logged; times are UTC.
CREATE OR REPLACE VIEW grafana.spend_logs AS
SELECT
    s."startTime" AS start_time,
    s."endTime" AS end_time,
    s.request_duration_ms AS duration_ms,
    s.call_type,
    s.model_group,
    s.model,
    s.status,
    s.spend,
    s.prompt_tokens,
    s.completion_tokens,
    s.total_tokens,
    t.key_alias
FROM public."LiteLLM_SpendLogs" AS s
LEFT JOIN public."LiteLLM_VerificationToken" AS t ON t.token = s.api_key;

GRANT SELECT ON grafana.usage_codes, grafana.spend_logs TO :"grafana_role";
