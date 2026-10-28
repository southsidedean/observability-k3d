{{/*
Labels every object ok3d makes carries, so `kubectl get all -l app.kubernetes.io/part-of=ok3d`
finds them all.
*/}}
{{- define "ok3d.labels" -}}
app.kubernetes.io/part-of: ok3d
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}
