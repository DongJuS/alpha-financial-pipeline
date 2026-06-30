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

{{/*
런타임 env override — 모든 alpha 컨테이너에 공통.
Infisical 동기화 시크릿의 DATABASE_URL/REDIS_URL 은 운영 docker compose
시점 hostname (예: alpha-pg-postgresql, localhost) 을 가리키므로 k3s
cluster-local Service 명으로 override 한다. POSTGRES_PASSWORD 는 Infisical
원본을 그대로 사용 (postgres StatefulSet 도 같은 secret 의 같은 키).

env: 는 envFrom 의 동일 키를 덮어쓰므로 (k8s 표준) Infisical 값 위에
안전하게 cluster-local 값 적용.
*/}}
{{- define "alpha-trading.runtimeEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: alpha-trading-secrets
      key: POSTGRES_PASSWORD
- name: DATABASE_URL
  value: {{ include "alpha-trading.databaseUrl" . | quote }}
- name: REDIS_URL
  value: {{ include "alpha-trading.redisUrl" . | quote }}
{{- end }}
