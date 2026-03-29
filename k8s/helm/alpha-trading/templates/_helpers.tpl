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
데이터베이스 URL 생성 (Bitnami PostgreSQL 서비스명 사용)
*/}}
{{- define "alpha-trading.databaseUrl" -}}
postgresql://{{ .Values.infra.postgres.user }}:$(POSTGRES_PASSWORD)@{{ .Values.infra.postgres.host }}:{{ .Values.infra.postgres.port }}/{{ .Values.infra.postgres.database }}
{{- end }}

{{/*
Redis URL 생성 (Bitnami Redis 서비스명 사용)
*/}}
{{- define "alpha-trading.redisUrl" -}}
redis://{{ .Values.infra.redis.host }}:{{ .Values.infra.redis.port }}/0
{{- end }}

{{/*
S3 Endpoint URL 생성 (Bitnami MinIO 서비스명 사용)
*/}}
{{- define "alpha-trading.s3EndpointUrl" -}}
http://{{ .Values.infra.minio.host }}:{{ .Values.infra.minio.port }}
{{- end }}
