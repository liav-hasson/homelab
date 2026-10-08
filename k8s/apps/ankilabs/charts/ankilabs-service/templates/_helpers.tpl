{{- define "ankilabs-service.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "ankilabs-service.selectorLabels" . }}
app.kubernetes.io/part-of: ankilabs
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.image.tag }}
app.kubernetes.io/version: {{ . | quote }}
{{- end }}
{{- end }}

{{- define "ankilabs-service.selectorLabels" -}}
app.kubernetes.io/name: {{ .Release.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "ankilabs-service.image" -}}
{{- $image := required "image.repository is required" .Values.image.repository -}}
{{- $tag := required "image.tag is required" .Values.image.tag -}}
{{- if .Values.image.digest -}}
{{ printf "%s:%s@%s" $image $tag .Values.image.digest }}
{{- else -}}
{{ printf "%s:%s" $image $tag }}
{{- end -}}
{{- end }}
