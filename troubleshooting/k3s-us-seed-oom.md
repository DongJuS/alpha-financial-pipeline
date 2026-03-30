# K3s US 종목 수집 중 OOM Kill → K3s 먹통

> 발생일: 2026-03-30
> 상태: 해결

---

## 증상

US 종목 OHLCV 수집(6,591종목) 중 worker pod OOM Kill(exit 137).
이후 K3s API 서버 응답 불가 (`The connection to the server was refused`).
Colima VM은 살아있으나 K3s 서비스가 죽은 상태.

## 원인

worker 메모리 제한 2Gi에서 6,591종목 수집 시 FDR DataFrame 누적으로 메모리 초과.
K3s API 서버가 자원 부족으로 같이 죽음.

## 해결

1. K3s 서비스 재시작 (VM 안에서):
```bash
colima ssh -- sudo systemctl start k3s
```
**Colima 삭제 불필요.** `systemctl start k3s` 한 줄로 해결.

2. worker 메모리 4Gi로 증가:
```bash
kubectl patch deployment worker -n alpha-trading --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"4Gi"}]'
```

## 데이터 손실

없음. PVC에 저장된 PostgreSQL 데이터 전부 보존됨.
수집 중단 시점(NYSE 1,612종목)까지의 데이터 유지.

## 교훈

- K3s에서 대량 배치 작업은 Job으로 분리하거나, 메모리 limit을 넉넉히 설정
- `colima ssh -- sudo systemctl start k3s`로 K3s만 재시작 가능 (delete 불필요)

---
