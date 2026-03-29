{{/*
공통 레이블
*/}}
{{- define "alpha-trading.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
컴포넌트별 셀렉터 레이블
*/}}
{{- define "alpha-trading.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
데이터베이스 URL 생성
*/}}
{{- define "alpha-trading.databaseUrl" -}}
postgresql://{{ .Values.postgres.user }}:{{ .Values.postgres.password }}@postgres:5432/{{ .Values.postgres.database }}
{{- end }}
