"""
src/services/model_config.py — LLM 모델/페르소나 역할 설정 서비스
"""

from __future__ import annotations

from src.db.queries import (
    list_model_role_configs,
    update_model_role_config,
    upsert_model_role_config,
)
from src.llm.claude_client import ClaudeClient
from src.llm.gemini_client import GeminiClient
from src.llm.gpt_client import GPTClient

SUPPORTED_MODEL_OPTIONS = [
    # ── Claude (CLI) ────────────────────────────────────────────
    {"model": "claude-opus-4-6", "provider": "claude", "label": "Claude Opus 4.6", "description": "최상위 추론 · 에이전트 팀 · 1M 컨텍스트"},
    {"model": "claude-sonnet-4-6", "provider": "claude", "label": "Claude Sonnet 4.6", "description": "Opus급 지능 · Sonnet 가격 · 일상 분석 최적"},
    {"model": "claude-haiku-4-5-20251001", "provider": "claude", "label": "Claude Haiku 4.5", "description": "빠른 응답 · 저비용 · 단순 작업에 적합"},
    {"model": "claude-sonnet-4-5-20250514", "provider": "claude", "label": "Claude Sonnet 4.5", "description": "이전 세대 Sonnet · 코딩 특화"},
    {"model": "claude-opus-4-5-20251114", "provider": "claude", "label": "Claude Opus 4.5", "description": "이전 세대 Opus · 안정적 추론"},
    {"model": "claude-3-5-sonnet-latest", "provider": "claude", "label": "Claude 3.5 Sonnet", "description": "레거시 호환 · 복합 추론"},
    # ── GPT (OpenAI API Key / Codex CLI fallback) ──────────────
    {"model": "gpt-5.4", "provider": "gpt", "label": "GPT-5.4", "description": "Codex 기본 최신 모델 · ChatGPT 로그인 CLI fallback 지원"},
    {"model": "gpt-5.4-mini", "provider": "gpt", "label": "GPT-5.4 Mini", "description": "경량 Codex 모델 · ChatGPT 로그인 CLI fallback 지원"},
    {"model": "gpt-4o", "provider": "gpt", "label": "GPT-4o", "description": "최신 멀티모달 · 고성능 추론 · 128K 컨텍스트"},
    {"model": "gpt-4o-mini", "provider": "gpt", "label": "GPT-4o Mini", "description": "경량 고속 · 저비용 · 일상 분석 최적"},
    {"model": "gpt-4-turbo", "provider": "gpt", "label": "GPT-4 Turbo", "description": "이전 세대 Turbo · 안정적 추론"},
    # ── Gemini (OAuth/ADC) ──────────────────────────────────────
    {"model": "gemini-3.1-pro-preview", "provider": "gemini", "label": "Gemini 3.1 Pro", "description": "최신 최상위 · 복합 추론 · 에이전트 최적화"},
    {"model": "gemini-3.1-flash-lite-preview", "provider": "gemini", "label": "Gemini 3.1 Flash Lite", "description": "3.1 경량 · 최저비용 · 대량 처리"},
    {"model": "gemini-3-flash-preview", "provider": "gemini", "label": "Gemini 3.0 Flash", "description": "고속 사고 모델 · 에이전트 · 코딩"},
    {"model": "gemini-2.5-pro-preview-06-05", "provider": "gemini", "label": "Gemini 2.5 Pro", "description": "2세대 Pro · 복합 추론 · 100만 토큰 컨텍스트"},
    {"model": "gemini-2.5-flash-preview-05-20", "provider": "gemini", "label": "Gemini 2.5 Flash", "description": "2세대 Flash · 사고 모드 · 빠른 응답"},
    {"model": "gemini-2.0-flash", "provider": "gemini", "label": "Gemini 2.0 Flash", "description": "안정 Flash · 에이전트 경험 최적화"},
    {"model": "gemini-2.0-flash-lite", "provider": "gemini", "label": "Gemini 2.0 Flash Lite", "description": "초경량 · 최저비용 · 대량 처리"},
    {"model": "gemini-1.5-pro", "provider": "gemini", "label": "Gemini 1.5 Pro", "description": "레거시 호환 · 검증된 추론 성능"},
    {"model": "gemini-1.5-flash", "provider": "gemini", "label": "Gemini 1.5 Flash", "description": "레거시 Flash · 빠른 응답"},
]

DEFAULT_MODEL_ROLE_CONFIGS = [
    {"config_key": "strategy_a_predictor_1", "strategy_code": "A", "role": "predictor", "role_label": "Predictor 1", "agent_id": "predictor_1", "llm_model": "claude-opus-4-6", "persona": "가치 투자형", "execution_order": 1},
    {"config_key": "strategy_a_predictor_2", "strategy_code": "A", "role": "predictor", "role_label": "Predictor 2", "agent_id": "predictor_2", "llm_model": "gemini-3.1-pro-preview", "persona": "기술적 분석형", "execution_order": 2},
    {"config_key": "strategy_a_predictor_3", "strategy_code": "A", "role": "predictor", "role_label": "Predictor 3", "agent_id": "predictor_3", "llm_model": "gemini-3.1-pro-preview", "persona": "모멘텀형", "execution_order": 3},
    {"config_key": "strategy_a_predictor_4", "strategy_code": "A", "role": "predictor", "role_label": "Predictor 4", "agent_id": "predictor_4", "llm_model": "gemini-3.1-pro-preview", "persona": "역추세형", "execution_order": 4},
    {"config_key": "strategy_a_predictor_5", "strategy_code": "A", "role": "predictor", "role_label": "Predictor 5", "agent_id": "predictor_5", "llm_model": "claude-haiku-4-5-20251001", "persona": "거시경제형", "execution_order": 5},
    {"config_key": "strategy_b_proposer", "strategy_code": "B", "role": "proposer", "role_label": "Proposer", "agent_id": "consensus_proposer", "llm_model": "claude-opus-4-6", "persona": "핵심 매매 가설을 세우는 수석 분석가", "execution_order": 1},
    {"config_key": "strategy_b_challenger_1", "strategy_code": "B", "role": "challenger", "role_label": "Challenger 1", "agent_id": "consensus_challenger_1", "llm_model": "gemini-3.1-pro-preview", "persona": "가설의 약점을 빠르게 파고드는 반론가", "execution_order": 2},
    {"config_key": "strategy_b_challenger_2", "strategy_code": "B", "role": "challenger", "role_label": "Challenger 2", "agent_id": "consensus_challenger_2", "llm_model": "gemini-3-flash-preview", "persona": "거시 변수와 대안을 점검하는 반론가", "execution_order": 3},
    {"config_key": "strategy_b_synthesizer", "strategy_code": "B", "role": "synthesizer", "role_label": "Synthesizer", "agent_id": "consensus_synthesizer", "llm_model": "claude-opus-4-6", "persona": "토론을 종합해 최종 결론을 내리는 조정자", "execution_order": 4},
]

SUPPORTED_MODEL_VALUES = {item["model"] for item in SUPPORTED_MODEL_OPTIONS}


async def ensure_model_role_configs() -> list[dict]:
    rows = await list_model_role_configs()
    existing_keys = {row["config_key"] for row in rows}
    missing = [item for item in DEFAULT_MODEL_ROLE_CONFIGS if item["config_key"] not in existing_keys]
    for item in missing:
        await upsert_model_role_config(**item)
    return await list_model_role_configs()


async def get_strategy_a_profiles(*, enabled_only: bool = True) -> list[dict]:
    rows = await ensure_model_role_configs()
    return [
        row for row in rows
        if row["strategy_code"] == "A" and (not enabled_only or row.get("is_enabled", True))
    ]


async def get_strategy_b_roles(*, enabled_only: bool = True) -> list[dict]:
    rows = await ensure_model_role_configs()
    return [
        row for row in rows
        if row["strategy_code"] == "B" and (not enabled_only or row.get("is_enabled", True))
    ]


async def update_model_role_configs(items: list[dict]) -> list[dict]:
    allowed_keys = {item["config_key"] for item in DEFAULT_MODEL_ROLE_CONFIGS}
    for item in items:
        if item["config_key"] not in allowed_keys:
            raise ValueError(f"알 수 없는 config_key: {item['config_key']}")
        if item["llm_model"] not in SUPPORTED_MODEL_VALUES:
            raise ValueError(f"지원하지 않는 모델: {item['llm_model']}")
        persona = str(item["persona"]).strip()
        if not persona:
            raise ValueError("persona는 비워둘 수 없습니다.")
        await update_model_role_config(
            config_key=item["config_key"],
            llm_model=item["llm_model"],
            persona=persona,
            is_enabled=bool(item.get("is_enabled", True)),
        )
    return await ensure_model_role_configs()


def provider_name_for_model(model: str) -> str:
    text = model.lower()
    if "claude" in text:
        return "claude"
    if "gpt" in text:
        return "gpt"
    if "gemini" in text:
        return "gemini"
    raise ValueError(f"지원하지 않는 provider 모델명입니다: {model}")


def provider_status() -> list[dict]:
    """각 LLM 프로바이더의 연결 상태를 반환한다.

    개별 프로바이더 초기화 실패가 전체 목록을 막지 않도록
    각각 독립적으로 try-except 처리한다.
    """
    results: list[dict] = []

    # ── Claude ──
    try:
        claude = ClaudeClient(model="claude-opus-4-6")
        if claude._cli_command:
            claude_mode = "CLI"
        elif claude._client is not None:
            claude_mode = "SDK (API Key)"
        else:
            claude_mode = "미연결"
        results.append({
            "provider": "claude",
            "mode": claude_mode,
            "default_model": "claude-opus-4-6",
            "configured": claude.is_configured,
        })
    except Exception:
        results.append({
            "provider": "claude",
            "mode": "미연결",
            "default_model": "claude-opus-4-6",
            "configured": False,
        })

    # ── GPT ──
    try:
        gpt = GPTClient(model="gpt-4o-mini")
        if gpt.auth_mode == "codex_cli":
            gpt_mode = "Codex CLI (ChatGPT)"
        elif gpt.auth_mode == "api_key":
            gpt_mode = "API Key"
        else:
            gpt_mode = "미연결"
        results.append({
            "provider": "gpt",
            "mode": gpt_mode,
            "default_model": gpt.effective_model,
            "configured": gpt.is_configured,
        })
    except Exception:
        results.append({
            "provider": "gpt",
            "mode": "미연결",
            "default_model": "gpt-4o-mini",
            "configured": False,
        })

    # ── Gemini ──
    try:
        gemini = GeminiClient(model="gemini-3.1-pro-preview")
        gemini_mode = gemini.auth_mode or "미연결"
        if gemini_mode == "oauth":
            gemini_mode = "OAuth (ADC)"
        elif gemini_mode == "api_key":
            gemini_mode = "API Key"
        results.append({
            "provider": "gemini",
            "mode": gemini_mode,
            "default_model": "gemini-3.1-pro-preview",
            "configured": gemini.is_configured,
        })
    except Exception:
        results.append({
            "provider": "gemini",
            "mode": "미연결",
            "default_model": "gemini-3.1-pro-preview",
            "configured": False,
        })

    return results
