/**
 * ui/src/pages/Settings.tsx
 * Settings page — Toss Invest dark theme.
 */
import { useEffect, useState } from "react";

import {
  usePortfolioConfig,
  useReadiness,
  useUpdatePortfolioConfig,
  useUpdateTradingMode,
  type MarketSessionStatus,
  type PortfolioConfig,
} from "@/hooks/usePortfolio";
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
  type NotificationPreferences,
} from "@/hooks/useNotifications";

type ConfigForm = Pick<PortfolioConfig, "strategy_blend_ratio" | "max_position_pct" | "daily_loss_limit_pct">;
type ExecutionForm = Pick<PortfolioConfig, "enable_paper_trading" | "enable_real_trading" | "primary_account_scope">;

function marketStatusLabel(status?: MarketSessionStatus): string {
  switch (status) {
    case "open":
      return "정규장 주문 가능";
    case "pre_open":
      return "장 시작 전";
    case "after_hours":
      return "장 마감 후";
    case "holiday":
      return "휴장일";
    case "weekend":
      return "주말";
    default:
      return "시장 종료";
  }
}

export default function Settings() {
  const { data: config, isLoading: configLoading } = usePortfolioConfig();
  const { data: readiness, isLoading: readinessLoading } = useReadiness();
  const { data: pref, isLoading: prefLoading } = useNotificationPreferences();

  const configMutation = useUpdatePortfolioConfig();
  const modeMutation = useUpdateTradingMode();
  const prefMutation = useUpdateNotificationPreferences();

  const [form, setForm] = useState<ConfigForm>({
    strategy_blend_ratio: 0.5,
    max_position_pct: 20,
    daily_loss_limit_pct: 3,
  });
  const [executionForm, setExecutionForm] = useState<ExecutionForm>({
    enable_paper_trading: true,
    enable_real_trading: false,
    primary_account_scope: "paper",
  });
  const [notifForm, setNotifForm] = useState<NotificationPreferences>({
    morning_brief: true,
    trade_alerts: true,
    circuit_breaker: true,
    daily_report: true,
    weekly_summary: true,
  });
  const [confirmationCode, setConfirmationCode] = useState("");

  useEffect(() => {
    if (!config) return;
    setForm({
      strategy_blend_ratio: Number(config.strategy_blend_ratio ?? 0.5),
      max_position_pct: Number(config.max_position_pct ?? 20),
      daily_loss_limit_pct: Number(config.daily_loss_limit_pct ?? 3),
    });
    setExecutionForm({
      enable_paper_trading: Boolean(config.enable_paper_trading ?? true),
      enable_real_trading: Boolean(config.enable_real_trading ?? false),
      primary_account_scope: config.primary_account_scope ?? "paper",
    });
  }, [config]);

  useEffect(() => {
    if (!pref) return;
    setNotifForm(pref);
  }, [pref]);

  return (
    <div className="page-shell max-w-5xl space-y-5">
      {/* Hero */}
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>시스템 설정</p>
        <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
          리스크 및 운영
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          전략 비중, 알림 정책, 실거래 전환을 안전하게 관리합니다.
        </p>
      </section>

      {/* Strategy/Risk Config */}
      <section className="card space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>전략/리스크 설정</h2>
          <span className="chip">
            {config?.enable_paper_trading && config?.enable_real_trading
              ? `PAPER + REAL (${config.primary_account_scope.toUpperCase()} primary)`
              : config?.enable_real_trading
                ? "REAL"
                : "PAPER"}
          </span>
        </div>

        <div className="rounded-xl px-4 py-4" style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}>
          <label className="block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>전략 블렌드 비율</label>
          <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>0.0 = Strategy A 100% · 1.0 = Strategy B 100%</p>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={form.strategy_blend_ratio}
            onChange={(e) => setForm((prev) => ({ ...prev, strategy_blend_ratio: Number(e.target.value) }))}
            className="mt-3 w-full accent-[#3182F6]"
            disabled={configLoading}
          />
          <div className="mt-2 flex justify-between text-xs" style={{ color: "var(--text-secondary)" }}>
            <span>Tournament (A)</span>
            <span style={{ color: "var(--brand-500)" }}>{Math.round(form.strategy_blend_ratio * 100)}%</span>
            <span>Debate (B)</span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded-xl px-4 py-3" style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}>
            <label className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>최대 단일 종목 비중 (%)</label>
            <input
              type="number"
              value={form.max_position_pct}
              min={1}
              max={100}
              onChange={(e) => setForm((prev) => ({ ...prev, max_position_pct: Number(e.target.value) }))}
              disabled={configLoading}
            />
          </div>
          <div className="rounded-xl px-4 py-3" style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}>
            <label className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>일손실 서킷브레이커 (%)</label>
            <input
              type="number"
              value={form.daily_loss_limit_pct}
              min={1}
              max={100}
              onChange={(e) => setForm((prev) => ({ ...prev, daily_loss_limit_pct: Number(e.target.value) }))}
              disabled={configLoading}
            />
          </div>
        </div>

        <button className="btn-primary disabled:opacity-50" disabled={configMutation.isPending} onClick={() => configMutation.mutate(form)}>
          {configMutation.isPending ? "저장 중..." : "전략 설정 저장"}
        </button>
      </section>

      {/* Notification Config */}
      <section className="card space-y-3">
        <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>Telegram 알림 설정</h2>

        {[
          { key: "morning_brief", label: "아침 브리핑 (08:30)" },
          { key: "trade_alerts", label: "거래 체결 알림" },
          { key: "circuit_breaker", label: "서킷브레이커 발동 알림" },
          { key: "daily_report", label: "일일 결산 리포트 (16:30)" },
          { key: "weekly_summary", label: "주간 성과 요약 (금요일 17:00)" },
        ].map(({ key, label }) => (
          <label
            key={key}
            className="flex items-center justify-between rounded-xl px-4 py-3"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}
          >
            <span className="text-sm" style={{ color: "var(--text-primary)" }}>{label}</span>
            <input
              type="checkbox"
              checked={Boolean(notifForm[key as keyof NotificationPreferences])}
              disabled={prefLoading}
              onChange={(e) => setNotifForm((prev) => ({ ...prev, [key]: e.target.checked }))}
              className="h-5 w-5 rounded accent-[#3182F6]"
            />
          </label>
        ))}

        <button className="btn-primary disabled:opacity-50" disabled={prefMutation.isPending} onClick={() => prefMutation.mutate(notifForm)}>
          {prefMutation.isPending ? "저장 중..." : "알림 설정 저장"}
        </button>
      </section>

      {/* Execution Config */}
      <section className="card space-y-4">
        <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>실행 계좌 관리</h2>
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          paper와 real을 동시에 운용할 수 있습니다. real 활성화에는 confirmation code와 readiness 통과가 필요합니다.
        </p>

        {config?.market_hours_enforced ? (
          <div
            className="rounded-xl px-4 py-4"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  정규장 외 분석만 허용
                </p>
                <p className="mt-1 text-xs leading-5" style={{ color: "var(--text-secondary)" }}>
                  paper와 real 주문은 한국 정규장 09:00~15:30 KST 거래일에만 실행됩니다. 장 시작 전, 장 마감 후,
                  주말, 휴장일에는 수집과 분석, 리포트만 계속 수행합니다.
                </p>
              </div>
              <span className="chip">{marketStatusLabel(config.market_status)}</span>
            </div>
          </div>
        ) : null}

        {readinessLoading ? (
          <div className="h-24 skeleton" />
        ) : (
          <div className="rounded-xl px-4 py-3" style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}>
            <p className={`text-sm font-semibold ${readiness?.ready ? "text-profit" : "text-loss"}`}>
              readiness: {readiness?.ready ? "READY" : "NOT READY"}
            </p>
            <div className="mt-2 max-h-44 space-y-1 overflow-y-auto">
              {(readiness?.checks ?? []).map((check) => (
                <p
                  key={check.key}
                  className="text-xs"
                  style={{ color: check.ok ? "var(--text-secondary)" : "var(--loss)" }}
                >
                  [{check.severity}] {check.key} - {check.ok ? "ok" : "fail"}
                </p>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <label
            className="flex items-center justify-between rounded-xl px-4 py-3"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}
          >
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>모의투자 실행</p>
              <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>internal 또는 KIS paper backend로 주문을 계속 실행합니다.</p>
            </div>
            <input
              type="checkbox"
              checked={executionForm.enable_paper_trading}
              onChange={(e) => setExecutionForm((prev) => ({ ...prev, enable_paper_trading: e.target.checked }))}
              className="h-5 w-5 rounded accent-[#3182F6]"
            />
          </label>
          <label
            className="flex items-center justify-between rounded-xl px-4 py-3"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}
          >
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>실거래 실행</p>
              <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>KIS 실거래 주문을 함께 실행합니다. readiness 통과와 확인 코드가 필요합니다.</p>
            </div>
            <input
              type="checkbox"
              checked={executionForm.enable_real_trading}
              onChange={(e) => setExecutionForm((prev) => ({ ...prev, enable_real_trading: e.target.checked }))}
              className="h-5 w-5 rounded accent-[#EF4444]"
            />
          </label>
        </div>

        <div className="rounded-xl px-4 py-3" style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}>
          <label className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Primary View Scope</label>
          <p className="mb-3 text-xs" style={{ color: "var(--text-secondary)" }}>
            `current` 모드와 기본 대시보드에서 우선 보여줄 계좌를 선택합니다.
          </p>
          <select
            value={executionForm.primary_account_scope}
            onChange={(e) =>
              setExecutionForm((prev) => ({
                ...prev,
                primary_account_scope: e.target.value as ExecutionForm["primary_account_scope"],
              }))
            }
          >
            <option value="paper">paper</option>
            <option value="real">real</option>
          </select>
        </div>

        <div className="rounded-xl px-4 py-3" style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}>
          <label className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Confirmation Code</label>
          <input
            type="password"
            value={confirmationCode}
            onChange={(e) => setConfirmationCode(e.target.value)}
            placeholder="REAL_TRADING_CONFIRMATION_CODE"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            className="inline-flex items-center justify-center rounded-xl px-5 py-2.5 text-sm font-semibold text-white transition-all disabled:opacity-50"
            style={{ background: executionForm.enable_real_trading ? "var(--loss)" : "var(--brand-500)" }}
            disabled={modeMutation.isPending}
            onClick={() =>
              modeMutation.mutate({
                enable_paper_trading: executionForm.enable_paper_trading,
                enable_real_trading: executionForm.enable_real_trading,
                primary_account_scope: executionForm.primary_account_scope,
                confirmation_code: confirmationCode,
              })
            }
          >
            {modeMutation.isPending ? "저장 중..." : "실행 계좌 저장"}
          </button>
        </div>
      </section>
    </div>
  );
}
