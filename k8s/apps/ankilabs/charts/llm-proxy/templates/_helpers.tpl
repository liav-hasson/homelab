{{- define "llm-proxy.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "llm-proxy.selectorLabels" . }}
app.kubernetes.io/part-of: ankilabs
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
{{- end }}

{{- define "llm-proxy.selectorLabels" -}}
app.kubernetes.io/name: {{ .Release.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "llm-proxy.image" -}}
{{- if not .Values.image.tag }}{{ fail "image.tag is required" }}{{ end }}
{{- if .Values.image.digest -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}@{{ .Values.image.digest }}
{{- else -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end }}
{{- end }}

{{- define "llm-proxy.dbPasswordEnv" -}}
{{- if not .Values.database.passwordSecret.name }}{{ fail "database.passwordSecret.name is required" }}{{ end -}}
- name: LITELLM_DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.passwordSecret.name }}
      key: {{ .Values.database.passwordSecret.key }}
{{- end }}
