# Oracle Cloud Always Free — 인스턴스 생성 가이드

> Oracle Ampere A1 (4 OCPU ARM, 24GB RAM, 200GB) 인스턴스 생성 절차.
> 용량 부족으로 즉시 생성이 안 되므로 크론으로 자동 재시도한다.

---

## 현재 상태 (2026-04-17)

- [x] Oracle Cloud 계정 생성
- [x] PAYG 전환 + 카드 등록
- [x] OCI CLI 설치 + API Key 등록
- [x] VCN 생성 (alpha-vcn, 춘천 리전)
- [x] 인스턴스 생성 크론 등록 (5분 간격)
- [x] 인스턴스 생성 성공 (134.185.110.214, reserved IP)
- [x] 서버 세팅 (Docker + Compose)
- [x] 데이터 이전 + 서비스 기동 (Gate B smoke/health/R2 green)
- [ ] 모니터링 bootstrap (`scripts/oci/setup_monitoring.sh`)
- [ ] Budget Alert 설정

---

## 환경 정보

| 항목 | 값 |
|------|-----|
| 리전 | ap-chuncheon-1 (춘천) |
| Shape | VM.Standard.A1.Flex |
| OS | Ubuntu 24.04 aarch64 |
| SSH Key | `~/.ssh/id_ed25519.pub` |
| OCI Config | `~/.oci/config` |

---

## 크론 모니터링

```bash
# 최근 로그 확인
tail -5 /tmp/oci_retry.log

# 실시간 감시
tail -f /tmp/oci_retry.log

# 크론 등록 확인
crontab -l
```

- 5분마다 자동 실행
- 성공 시 `/tmp/oci_instance_created.txt`에 OCID 기록 → 이후 실행 자동 스킵
- **Mac 잠자기 모드에서는 크론이 안 돌아감** — `caffeinate -s` 또는 뚜껑 열어두기
- **네트워크 연결 필수** — 끊겨 있으면 타임아웃 후 다음 주기에 재시도

---

## 크론 관리

```bash
# 크론 중지 (필요 시)
crontab -r

# 크론 재등록
crontab -e
# 아래 한 줄 추가:
# */5 * * * * OCI_COMPARTMENT_ID="..." OCI_AVAILABILITY_DOMAIN="..." OCI_SUBNET_ID="..." OCI_IMAGE_ID="..." /path/to/scripts/oci_instance_retry.sh >> /tmp/oci_retry.log 2>&1
```

---

## 인스턴스 생성 성공 후

1. 공개 IP 확인:
   ```bash
   oci compute instance list-vnics --instance-id "$(cat /tmp/oci_instance_created.txt)" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['public-ip'])"
   ```

2. SSH 접속:
   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@<공개IP>
   ```

3. 서버 세팅 → `docs/` 내 클라우드 마이그레이션 문서 참조:
   - `.agent/discussions/20260411-cloud-migration-execution-plan.md` (Phase 1~4)

4. 크론 제거:
   ```bash
   crontab -r
   ```

---

## 2주 후에도 실패 시

Hetzner CAX21 (€7.99/월)로 fallback.
상세: `.agent/discussions/20260413-cloud-infra-oracle-vs-hetzner.md`

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| "Out of host capacity" | 춘천 리전 용량 부족 | 정상 — 크론이 재시도 |
| "connection timed out" | 네트워크 끊김 | 네트워크 연결 확인 |
| 로그에 새 줄이 안 찍힘 | Mac 잠자기 또는 크론 미등록 | `crontab -l` 확인, `caffeinate -s` |
| SSH key 에러 | 키 파일 경로 불일치 | `scripts/oci_instance_retry.sh`의 `SSH_KEY_FILE` 확인 |

---

## 호스트 모니터링 + Budget 부트스트랩

앱 내부 알림(Telegram)만으로는 잡지 못하는 계층을 OCI 자체 알람으로 커버한다:
CPU/메모리/디스크 고점 + 과금 발생. 스크립트 하나로 멱등 세팅한다.

**사전 준비**
1. OCI CLI 설정 완료 (`oci setup config`).
2. 필요한 OCID 확보:
   - Compartment OCID — `oci iam compartment list --all --compartment-id-in-subtree true`
   - Tenancy OCID — `oci iam tenancy list` 또는 `~/.oci/config`의 `tenancy=` 값
   - Instance OCID — `oci compute instance list -c $OCI_COMPARTMENT_OCID`
3. 알림 수신 이메일 (최초 1회 subscription 확인 메일 클릭 필요).
4. `jq` 설치 (macOS: `brew install jq`).

**실행**

```bash
export OCI_COMPARTMENT_OCID=ocid1.compartment.oc1..xxx
export OCI_TENANCY_OCID=ocid1.tenancy.oc1..xxx
export OCI_INSTANCE_OCID=ocid1.instance.oc1.ap-seoul-1..xxx
export OCI_ALERT_EMAIL=ops@example.com
./scripts/oci/setup_monitoring.sh
```

**생성되는 리소스**

| 리소스 | 이름 | 임계값 기본 |
|---|---|---|
| ONS topic | `alpha-ops-alerts` | — |
| Email subscription | `$OCI_ALERT_EMAIL` | (수신함에서 Confirm 클릭 1회) |
| CPU alarm | `alpha-cpu-high` | CpuUtilization > 90% (5분 지속) |
| Memory alarm | `alpha-memory-high` | MemoryUtilization > 90% (5분 지속) |
| Disk alarm | `alpha-disk-high` | FilesystemUtilization > 80% (5분 지속) |
| Monthly budget | `alpha-monthly-budget` | $1/월 (OCI 최소값) |
| Alert rule | `alpha-any-spend` | >=1% (≈$0.01) 지출 시 이메일 |

임계값 커스터마이즈는 환경변수로: `OCI_CPU_THRESHOLD`, `OCI_MEM_THRESHOLD`,
`OCI_DISK_THRESHOLD`, `OCI_BUDGET_THRESHOLD`.

**참고 — Oracle Cloud Agent 플러그인**

Compute alarm은 OS 내부 Oracle Cloud Agent가 `oci_computeagent` 네임스페이스로
메트릭을 publish해야 동작한다. 콘솔 → Instance → Oracle Cloud Agent 탭에서
"Compute Instance Monitoring" 플러그인이 Enabled인지 확인한다(대부분 기본 ON).

**검증**

```bash
# 알람 목록에 3개가 뜨는지
oci monitoring alarm list -c $OCI_COMPARTMENT_OCID --all | jq -r '.data[]."display-name"'
# budget
oci budgets budget list -c $OCI_TENANCY_OCID --target-type COMPARTMENT \
    | jq -r '.data[] | "\(."display-name") \(.amount)"'
```

*Last updated: 2026-04-17*
