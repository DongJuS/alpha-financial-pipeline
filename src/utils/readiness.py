"""
src/utils/readiness.py — 실거래 전환 준비 상태 점검
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.db.queries import fetch_latest_operational_audit, fetch_latest_paper_trading_run
from src.llm.gemini_client import gemini_oauth_available
from src.utils.config import get_settings, kis_account_number_for_scope, kis_app_key_for_scope, kis_app_secret_for_scope
from src.utils.db_client import fetchrow, fetchval
from src.utils.redis_client import get_redis


PLACEHOLDER_PATTERNS = [
    "...",
    "xxx",
    "xxxx",
    "xxxxx",
    "change-this",
    "example",
]


def _is_placeholder(value: str) -> bool:
    lower = value.strip().lower()
    if not lower:
        return True
    return any(p in lower for p in PLACEHOLDER_PATTERNS)


def _is_valid_account_number(value: str) -> bool:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return len(digits) >= 10


async def evaluate_real_trading_readiness() -> dict[str, Any]:
    """실거래 전환 전 필수 조건을 점검합니다."""
    settings = get_settings()
    checks: list[dict[str, Any]] = []
    audit_max_age_days = int(settings.readiness_audit_max_age_days)
    required_paper_days = int(settings.readiness_required_paper_days)
    real_app_key = kis_app_key_for_scope(settings, "real")
    real_app_secret = kis_app_secret_for_scope(settings, "real")
    real_account_number = kis_account_number_for_scope(settings, "real")

    # 1) 필수 자격증명
    cred_pairs = [
        ("KIS_REAL_APP_KEY", real_app_key),
        ("KIS_REAL_APP_SECRET", real_app_secret),
        ("KIS_REAL_ACCOUNT_NUMBER", real_account_number),
        ("JWT_SECRET", settings.jwt_secret),
        ("REAL_TRADING_CONFIRMATION_CODE", settings.real_trading_confirmation_code),
    ]
    for key, value in cred_pairs:
        ok = bool(value and not _is_placeholder(value))
        if key == "KIS_REAL_ACCOUNT_NUMBER":
            ok = ok and _is_valid_account_number(str(value))
        checks.append(
            {
                "key": f"cred:{key}",
                "ok": ok,
                "message": (
                    f"{key} 설정 정상"
                    if ok
                    else (
                        f"{key} 계좌번호 형식 오류"
                        if key == "KIS_REAL_ACCOUNT_NUMBER" and value and not _is_placeholder(str(value))
                        else f"{key} 설정 누락/placeholder"
                    )
                ),
                "severity": "critical",
            }
        )

    # 2) 알림 채널
    telegram_ok = bool(
        settings.telegram_bot_token
        and settings.telegram_chat_id
        and not _is_placeholder(settings.telegram_bot_token)
        and not _is_placeholder(settings.telegram_chat_id)
    )
    checks.append(
        {
            "key": "notif:telegram",
            "ok": telegram_ok,
            "message": "Telegram 알림 채널 설정 " + ("정상" if telegram_ok else "누락/placeholder"),
            "severity": "high",
        }
    )

    # 3) DB 연결
    try:
        db_ok = (await fetchval("SELECT 1")) == 1
    except Exception as e:
        db_ok = False
        db_err = str(e)
    checks.append(
        {
            "key": "infra:db",
            "ok": db_ok,
            "message": "DB 연결 " + ("정상" if db_ok else f"실패 ({db_err})"),
            "severity": "critical",
        }
    )

    # 4) Redis 연결
    try:
        redis = await get_redis()
        redis_ok = bool(await redis.ping())
    except Exception as e:
        redis_ok = False
        redis_err = str(e)
    checks.append(
        {
            "key": "infra:redis",
            "ok": redis_ok,
            "message": "Redis 연결 " + ("정상" if redis_ok else f"실패 ({redis_err})"),
            "severity": "critical",
        }
    )

    # 5) 리스크 설정
    try:
        cfg = await fetchrow(
            """
            SELECT max_position_pct, daily_loss_limit_pct
            FROM portfolio_config
            LIMIT 1
            """
        )
        if cfg:
            max_position_pct = int(cfg["max_position_pct"])
            daily_loss_limit_pct = int(cfg["daily_loss_limit_pct"])
        else:
            max_position_pct = 1000
            daily_loss_limit_pct = 0
    except Exception:
        max_position_pct = 1000
        daily_loss_limit_pct = 0

    risk_ok = (1 <= max_position_pct <= 30) and (1 <= daily_loss_limit_pct <= 10)
    checks.append(
        {
            "key": "risk:limits",
            "ok": risk_ok,
            "message": (
                "리스크 한도 점검 "
                + (
                    f"정상(max_position_pct={max_position_pct}, daily_loss_limit_pct={daily_loss_limit_pct})"
                    if risk_ok
                    else (
                        f"비정상(max_position_pct={max_position_pct}, daily_loss_limit_pct={daily_loss_limit_pct})"
                    )
                )
            ),
            "severity": "critical",
        }
    )

    # 6) 페이퍼 트레이딩 최소 운용 일수
    try:
        paper_stats = await fetchrow(
            """
            SELECT
                COUNT(DISTINCT (executed_at AT TIME ZONE 'Asia/Seoul')::date) AS active_days,
                COUNT(*) AS trade_count
            FROM trade_history
            WHERE is_paper = TRUE
              AND executed_at >= NOW() - INTERVAL '120 day'
            """
        )
        active_days = int(paper_stats["active_days"]) if paper_stats else 0
        trade_count = int(paper_stats["trade_count"]) if paper_stats else 0
    except Exception:
        active_days = 0
        trade_count = 0

    simulation_days = 0
    simulation_passed = False
    try:
        latest_run = await fetch_latest_paper_trading_run("baseline")
        if latest_run:
            simulation_days = int(latest_run.get("simulated_days") or 0)
            simulation_passed = bool(latest_run.get("passed"))
    except Exception:
        simulation_days = 0
        simulation_passed = False

    paper_ok = (active_days >= required_paper_days) or (
        simulation_passed and simulation_days >= required_paper_days
    )
    checks.append(
        {
            "key": "paper:track_record",
            "ok": paper_ok,
            "message": (
                f"페이퍼 운용 일수 점검 정상(active_days={active_days}, required={required_paper_days}, trades={trade_count}, sim_days={simulation_days}, sim_passed={simulation_passed})"
                if paper_ok
                else f"페이퍼 운용 일수 부족(active_days={active_days}, required={required_paper_days}, trades={trade_count}, sim_days={simulation_days}, sim_passed={simulation_passed})"
            ),
            "severity": "critical",
        }
    )

    # 7) 운영 감사 이력 (보안, 리스크 규칙)
    for audit_type, label in [("security", "보안 감사"), ("risk_rules", "리스크 규칙 검증")]:
        try:
            latest = await fetch_latest_operational_audit(audit_type)
            if not latest:
                checks.append(
                    {
                        "key": f"audit:{audit_type}",
                        "ok": False,
                        "message": f"{label} 이력이 없습니다. `python scripts/{'security_audit.py' if audit_type == 'security' else 'validate_risk_rules.py'}` 실행 필요",
                        "severity": "critical",
                    }
                )
                continue

            created_at = latest.get("created_at")
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_hours = (
                (datetime.now(timezone.utc) - created_at).total_seconds() / 3600 if created_at else 999999
            )
            age_days = age_hours / 24
            passed = bool(latest.get("passed"))
            recent = age_days <= audit_max_age_days
            audit_ok = passed and recent

            checks.append(
                {
                    "key": f"audit:{audit_type}",
                    "ok": audit_ok,
                    "message": (
                        f"{label} 정상(passed={passed}, age_hours={age_hours:.1f}, max_age_days={audit_max_age_days})"
                        if audit_ok
                        else f"{label} 미충족(passed={passed}, age_hours={age_hours:.1f}, max_age_days={audit_max_age_days})"
                    ),
                    "severity": "critical",
                }
            )
        except Exception as e:
            checks.append(
                {
                    "key": f"audit:{audit_type}",
                    "ok": False,
                    "message": f"{label} 조회 실패 ({e})",
                    "severity": "critical",
                }
            )

    # 8) LLM 키 최소 1개
    llm_values = [settings.anthropic_api_key, settings.openai_api_key]
    gemini_oauth_ok = gemini_oauth_available()
    llm_ok = any(v and not _is_placeholder(v) for v in llm_values) or gemini_oauth_ok
    checks.append(
        {
            "key": "llm:any",
            "ok": llm_ok,
            "message": (
                "LLM 자격증명 최소 1개 정상"
                if llm_ok
                else "LLM 자격증명 누락/placeholder"
            )
            + (" (Gemini OAuth 포함)" if gemini_oauth_ok else ""),
            "severity": "high",
        }
    )

    # 9) K8s 환경 체크 (K8s에서 실행 중일 때만)
    k8s_checks = await _evaluate_k8s_readiness()
    checks.extend(k8s_checks)

    critical_ok = all(c["ok"] for c in checks if c["severity"] == "critical")
    high_ok = all(c["ok"] for c in checks if c["severity"] in {"critical", "high"})
    return {
        "ready": critical_ok and high_ok,
        "critical_ok": critical_ok,
        "high_ok": high_ok,
        "checks": checks,
    }


async def _evaluate_k8s_readiness() -> list[dict[str, Any]]:
    """K8s 환경에서 실행 중일 때 추가 체크를 수행합니다.

    K8s 밖에서 실행 중이면 빈 리스트를 반환합니다.
    """
    import os
    import shutil

    if not os.environ.get("KUBERNETES_SERVICE_HOST"):
        return []

    checks: list[dict[str, Any]] = []

    # 9a) K8s API 서버 접근 가능 여부
    sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    sa_ok = os.path.isfile(sa_token_path)
    checks.append({
        "key": "k8s:service_account",
        "ok": sa_ok,
        "message": "K8s ServiceAccount 토큰 " + ("마운트 정상" if sa_ok else "누락"),
        "severity": "critical",
    })

    # 9b) 필수 볼륨 마운트 확인
    required_mounts = [
        ("/data/rl/models", "RL 모델 저장소"),
        ("/data/rl/experiments", "RL 실험 저장소"),
    ]
    for mount_path, label in required_mounts:
        exists = os.path.isdir(mount_path)
        checks.append({
            "key": f"k8s:volume:{mount_path}",
            "ok": exists,
            "message": f"{label} ({mount_path}) " + ("마운트 정상" if exists else "누락"),
            "severity": "high",
        })

    # 9c) DNS 해석 가능 여부 (클러스터 내부 서비스)
    import socket

    for svc, label in [("postgres", "PostgreSQL"), ("redis", "Redis"), ("minio", "MinIO")]:
        try:
            socket.getaddrinfo(svc, None)
            dns_ok = True
        except socket.gaierror:
            dns_ok = False
        checks.append({
            "key": f"k8s:dns:{svc}",
            "ok": dns_ok,
            "message": f"{label} DNS 해석 " + ("정상" if dns_ok else "실패"),
            "severity": "critical",
        })

    # 9d) kubectl 사용 가능 여부
    kubectl_ok = shutil.which("kubectl") is not None
    checks.append({
        "key": "k8s:kubectl",
        "ok": kubectl_ok,
        "message": "kubectl " + ("사용 가능" if kubectl_ok else "미설치 (디버깅 제한)"),
        "severity": "low",
    })

    return checks
