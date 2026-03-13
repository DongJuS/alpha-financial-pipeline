/**
 * ui/src/pages/Settings.tsx
 * Settings page with cleaner controls and clearer risk/conversion sections.
 */
import { useEffect, useState } from "react";

import {
  usePortfolioConfig,
  useReadiness,
  useUpdatePortfolioConfig,
  useUpdateTradingMode,
  type PortfolioConfig,
} from "@/hooks/usePortfolio";
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
  type NotificationPreferences,
} from "@/hooks/useNotifications";

type ConfigForm = Omit<PortfolioConfig, "is_paper_trading">;

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
  }, [config]);

  useEffect(() => {
    if (!pref) return;
    setNotifForm(pref);
  }, [pref]);

  return (
    <div className="page-shell max-w-5xl space-y-4">
      <section className="rounded-[30px] bg-[#F2F4F6] px-6 py-6 shadow-[0_12px_28px_rgba(25,31,40,0.06)] md:px-7">
        <p className="text-[13px] font-semibold text-[#8B95A1]">시스템 설정</p>
        <h1 className="mt-1 text-[32px] font-extrabold tracking-[-0.03em] text-[#191F28]">리스크 및 운영</h1>
        <p className="mt-2 text-sm text-[#8B95A1]">전략 비중, 알림 정책, 실거래 전환을 안전하게 관리합니다.</p>
      </section>

      <section className="card space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-[#191F28]">전략/리스크 설정</h2>
          {config?.is_paper_trading ? (
            <span className="chip">PAPER</span>
          ) : (
            <span className="rounded-full bg-[#FFECEC] px-2.5 py-1 text-[11px] font-semibold text-[#C92A2A]">REAL</span>
          )}
        </div>

        <div className="rounded-2xl bg-white px-4 py-4">
          <label className="block text-sm font-semibold text-[#191F28]">전략 블렌드 비율</label>
          <p className="mt-1 text-xs text-[#8B95A1]">0.0 = Strategy A 100% · 1.0 = Strategy B 100%</p>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={form.strategy_blend_ratio}
            onChange={(e) => setForm((prev) => ({ ...prev, strategy_blend_ratio: Number(e.target.value) }))}
            className="mt-3 w-full accent-brand"
            disabled={configLoading}
          />
          <div className="mt-2 flex justify-between text-xs text-[#8B95A1]">
            <span>Tournament (A)</span>
            <span>{Math.round(form.strategy_blend_ratio * 100)}%</span>
            <span>Debate (B)</span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded-2xl bg-white px-4 py-3">
            <label className="mb-1 block text-sm font-semibold text-[#191F28]">최대 단일 종목 비중 (%)</label>
            <input
              type="number"
              value={form.max_position_pct}
              min={1}
              max={100}
              onChange={(e) => setForm((prev) => ({ ...prev, max_position_pct: Number(e.target.value) }))}
              className="bg-[#F2F4F6]"
              disabled={configLoading}
            />
          </div>
          <div className="rounded-2xl bg-white px-4 py-3">
            <label className="mb-1 block text-sm font-semibold text-[#191F28]">일손실 서킷브레이커 (%)</label>
            <input
              type="number"
              value={form.daily_loss_limit_pct}
              min={1}
              max={100}
              onChange={(e) => setForm((prev) => ({ ...prev, daily_loss_limit_pct: Number(e.target.value) }))}
              className="bg-[#F2F4F6]"
              disabled={configLoading}
            />
          </div>
        </div>

        <button className="btn-primary disabled:opacity-60" disabled={configMutation.isPending} onClick={() => configMutation.mutate(form)}>
          {configMutation.isPending ? "저장 중..." : "전략 설정 저장"}
        </button>
      </section>

      <section className="card space-y-3">
        <h2 className="text-base font-bold text-[#191F28]">Telegram 알림 설정</h2>

        {[
          { key: "morning_brief", label: "아침 브리핑 (08:30)" },
          { key: "trade_alerts", label: "거래 체결 알림" },
          { key: "circuit_breaker", label: "서킷브레이커 발동 알림" },
          { key: "daily_report", label: "일일 결산 리포트 (16:30)" },
          { key: "weekly_summary", label: "주간 성과 요약 (금요일 17:00)" },
        ].map(({ key, label }) => (
          <label key={key} className="flex items-center justify-between rounded-2xl bg-white px-4 py-3">
            <span className="text-sm text-[#191F28]">{label}</span>
            <input
              type="checkbox"
              checked={Boolean(notifForm[key as keyof NotificationPreferences])}
              disabled={prefLoading}
              onChange={(e) => setNotifForm((prev) => ({ ...prev, [key]: e.target.checked }))}
              className="h-5 w-5 accent-brand rounded"
            />
          </label>
        ))}

        <button className="btn-primary disabled:opacity-60" disabled={prefMutation.isPending} onClick={() => prefMutation.mutate(notifForm)}>
          {prefMutation.isPending ? "저장 중..." : "알림 설정 저장"}
        </button>
      </section>

      <section className="card space-y-4">
        <h2 className="text-base font-bold text-[#191F28]">실거래 전환</h2>
        <p className="text-xs text-[#8B95A1]">전환 시 confirmation code와 readiness 통과가 모두 필요합니다.</p>

        {readinessLoading ? (
          <div className="h-24 rounded-2xl bg-white animate-pulse" />
        ) : (
          <div className="rounded-2xl bg-white px-4 py-3">
            <p className={`text-sm font-semibold ${readiness?.ready ? "text-profit" : "text-loss"}`}>
              readiness: {readiness?.ready ? "READY" : "NOT READY"}
            </p>
            <div className="mt-2 max-h-44 space-y-1 overflow-y-auto">
              {(readiness?.checks ?? []).map((check) => (
                <p key={check.key} className={`text-xs ${check.ok ? "text-[#4E5968]" : "text-[#C92A2A]"}`}>
                  [{check.severity}] {check.key} - {check.ok ? "ok" : "fail"}
                </p>
              ))}
            </div>
          </div>
        )}

        <div className="rounded-2xl bg-white px-4 py-3">
          <label className="mb-1 block text-sm font-semibold text-[#191F28]">Confirmation Code</label>
          <input
            type="password"
            value={confirmationCode}
            onChange={(e) => setConfirmationCode(e.target.value)}
            className="bg-[#F2F4F6]"
            placeholder="REAL_TRADING_CONFIRMATION_CODE"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            className="inline-flex items-center justify-center rounded-full bg-[#E03131] px-4 py-2.5 text-sm font-semibold text-white transition-transform hover:scale-105 disabled:opacity-60"
            disabled={modeMutation.isPending}
            onClick={() =>
              modeMutation.mutate({
                is_paper: false,
                confirmation_code: confirmationCode,
              })
            }
          >
            실거래 전환
          </button>
          <button
            className="btn-secondary disabled:opacity-60"
            disabled={modeMutation.isPending}
            onClick={() =>
              modeMutation.mutate({
                is_paper: true,
                confirmation_code: confirmationCode,
              })
            }
          >
            페이퍼 복귀
          </button>
        </div>
      </section>
    </div>
  );
}
