# Oracle Cloud Always Free — 인스턴스 생성 가이드

> Oracle Ampere A1 (4 OCPU ARM, 24GB RAM, 200GB) 인스턴스 생성 절차.
> 용량 부족으로 즉시 생성이 안 되므로 크론으로 자동 재시도한다.

---

## 현재 상태 (2026-04-15)

- [x] Oracle Cloud 계정 생성
- [x] PAYG 전환 + 카드 등록
- [ ] Budget Alert $0 설정 (Billing > Budgets)
- [x] OCI CLI 설치 + API Key 등록
- [x] VCN 생성 (alpha-vcn, 춘천 리전)
- [x] 인스턴스 생성 크론 등록 (5분 간격)
- [ ] 인스턴스 생성 성공
- [ ] 서버 세팅 (Docker + Compose)
- [ ] 데이터 이전 + 서비스 기동

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

*Last updated: 2026-04-15*
