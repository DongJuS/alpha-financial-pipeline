/**
 * ui/src/components/StrategyDashboard.tsx
 * 전략별 모드/성과/승격 상태/가상 자금 잔고 종합 대시보드
 */
import { useMemo, useState } from "react";
import {
  useStrategyDashboard,
  type StrategyDashboardItem,
  type StrategyPerformance,
  type VirtualBalance,
} from "@/hooks/useSignals";
import { formatPct } from "@/utils/api";

const STRATEGY_LABELS: Record<string, string> = {
  A: "Tournament",
  B: "Consensus",
  RL: "RL Trading",
  S: "Search",
  L: "Long-term",
};

const STRATEGY_COLORS: Record<string, string> = {
  A: "#1f63f7",
  B: "#0cb58f",
  RL: "#f04452",
  S: "#c27b0a",
  L: "#6d5efc",
};

const MODE_LABELS: Record<string, { label: string; bg: string; text: string }> = {
  real: { label: "실전", bg: "rgba(240,68,82,0.12)", text: "#f04452" },
  paper: { label: "모의", bg: "rgba(31,99,247,0.12)", text: "#1f63f7" },
  virtual: { label: "가상", bg: "rgba(12,181,143,0.12)", text: "#0cb58f" },
};

function formatWon(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--원";
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

function formatCompactWon(value: number): string {
  if (Math.abs(value) >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(1)}억원`;
  }
  if (Math.abs(value) >= 10_000) {
    return `${(value / 10_000).toFixed(0)}만원`;
  }
  return formatWon(value);
}

function PromotionBadge({
  readiness,
}: {
  readiness: StrategyDashboardItem["promotion_readiness"];
}) {
  const entries = Object.entries(readiness);
  if (entries.length === 0) return null;

  return (
    <div className="mt-3 space-y-2">
      {entries.map(([path, info]) => {
        const [from, , to] = path.split("_");
        const ready = info.ready;
        return (
          <div
            key={path}
            className="flex items-center gap-2 rounded-xl px-3 py-2 text-xs"
            style={{
              background: ready
                ? "rgba(12,181,143,0.10)"
                : "rgba(148,163,184,0.10)",
            }}
          >
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{
                background: ready ? "#0cb58f" : "#94a3b8",
              }}
            />
            <span
              className="font-semibold"
              style={{ color: ready ? "#0cb58f" : "#64748b" }}
            >
              {from} → {to}
            </span>
            <span style={{ color: "#94a3b8" }}>
              {ready ? "승격 가능" : `미충족 ${info.failures.length}건`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function PerformanceRow({ perf }: { perf: StrategyPerformance }) {
  const modeStyle = MODE_LABELS[perf.mode] ?? MODE_LABELS.virtual;
  const isPositive = perf.return_pct >= 0;

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-white/60 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-bold"
          style={{ background: modeStyle.bg, color: modeStyle.text }}
        >
          {modeStyle.label}
        </span>
        <span
          className="text-xs"
          style={{ color: "var(--text-secondary)" }}
        >
          {perf.trading_days}일 · {perf.total_trades}건
        </span>
      </div>
      <div className="flex items-center gap-3">
        <span
          className="text-sm font-bold"
          style={{ color: isPositive ? "var(--profit)" : "var(--loss)" }}
        >
          {formatPct(perf.return_pct)}
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          MDD {formatPct(perf.max_drawdown_pct)}
        </span>
        {perf.sharpe_ratio != null && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            SR {perf.sharpe_ratio.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  );
}

function VirtualBalanceCard({ balance }: { balance: VirtualBalance }) {
  const isPositive = balance.unrealized_pnl >= 0;
  const equityPct = balance.initial_capital > 0
    ? ((balance.total_equity - balance.initial_capital) / balance.initial_capital) * 100
    : 0;
  const isEquityPositive = equityPct >= 0;

  return (
    <div
      className="mt-3 rounded-2xl border p-4"
      style={{
        borderColor: "rgba(12,181,143,0.20)",
        background: "rgba(12,181,143,0.04)",
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <p
          className="text-xs font-semibold uppercase tracking-wider"
          style={{ color: "#0cb58f" }}
        >
          Virtual Balance
        </p>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {balance.position_count}종목 보유
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] uppercase" style={{ color: "var(--text-muted)" }}>
            총 자산
          </p>
          <p className="mt-1 text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {formatCompactWon(balance.total_equity)}
          </p>
          <span
            className="text-xs font-semibold"
            style={{ color: isEquityPositive ? "var(--profit)" : "var(--loss)" }}
          >
            {isEquityPositive ? "+" : ""}{equityPct.toFixed(2)}%
          </span>
        </div>
        <div>
          <p className="text-[10px] uppercase" style={{ color: "var(--text-muted)" }}>
            평가손익
          </p>
          <p
            className="mt-1 text-lg font-bold"
            style={{ color: isPositive ? "var(--profit)" : "var(--loss)" }}
          >
            {formatCompactWon(balance.unrealized_pnl)}
          </p>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            ({formatPct(balance.unrealized_pnl_pct)})
          </span>
        </div>
      </div>

      <div className="mt-3 flex justify-between text-xs" style={{ color: "var(--text-secondary)" }}>
        <span>현금 {formatCompactWon(balance.cash_balance)}</span>
        <span>포지션 {formatCompactWon(balance.position_market_value)}</span>
        <span>초기 {formatCompactWon(balance.initial_capital)}</span>
      </div>
    </div>
  );
}

function StrategyCard({ item }: { item: StrategyDashboardItem }) {
  const color = STRATEGY_COLORS[item.strategy_id] ?? "#6d5efc";
  const label = STRATEGY_LABELS[item.strategy_id] ?? item.strategy_id;

  return (
    <article
      className="rounded-[28px] border border-white/75 bg-white/78 p-5 transition-all hover:-translate-y-0.5 hover:shadow-[0_20px_36px_rgba(15,23,42,0.06)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div
            className="flex h-11 w-11 items-center justify-center rounded-2xl text-base font-black text-white"
            style={{ background: color }}
          >
            {item.strategy_id}
          </div>
          <div>
            <p
              className="text-sm font-bold tracking-tight"
              style={{ color: "var(--text-primary)" }}
            >
              Strategy {item.strategy_id}
            </p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {label}
            </p>
          </div>
        </div>
        <span
          className="rounded-full px-2.5 py-1 text-[10px] font-bold"
          style={{
            background: "var(--bg-input)",
            color: "var(--text-muted)",
          }}
        >
          {formatCompactWon(item.allocated_capital)}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {item.active_modes.map((mode) => {
          const modeStyle = MODE_LABELS[mode] ?? MODE_LABELS.virtual;
          return (
            <span
              key={mode}
              className="rounded-full px-2.5 py-1 text-[10px] font-bold"
              style={{ background: modeStyle.bg, color: modeStyle.text }}
            >
              {modeStyle.label}
            </span>
          );
        })}
      </div>

      {item.performance.length > 0 && (
        <div className="mt-4 space-y-1.5">
          {item.performance.map((perf) => (
            <PerformanceRow key={`${perf.strategy_id}-${perf.mode}`} perf={perf} />
          ))}
        </div>
      )}

      {item.performance.length === 0 && (
        <p
          className="mt-4 text-xs leading-5"
          style={{ color: "var(--text-secondary)" }}
        >
          거래 기록이 아직 없습니다.
        </p>
      )}

      <PromotionBadge readiness={item.promotion_readiness} />

      {item.virtual_balance && (
        <VirtualBalanceCard balance={item.virtual_balance} />
      )}
    </article>
  );
}

export default function StrategyDashboard() {
  const { data, isLoading } = useStrategyDashboard();

  const strategies = useMemo(
    () => data?.strategies ?? [],
    [data]
  );

  if (isLoading) {
    return (
      <div className="card">
        <span className="eyebrow">Strategy overview</span>
        <h2
          className="mt-3 text-[24px] font-bold tracking-tight"
          style={{ color: "var(--text-primary)" }}
        >
          전략별 운용 현황
        </h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-[320px] skeleton" />
          ))}
        </div>
      </div>
    );
  }

  const totalVirtualEquity = strategies.reduce(
    (sum, s) => sum + (s.virtual_balance?.total_equity ?? 0),
    0
  );
  const totalVirtualCapital = strategies.reduce(
    (sum, s) =>
      sum +
      (s.active_modes.includes("virtual") ? s.allocated_capital : 0),
    0
  );
  const totalVirtualPnl = totalVirtualCapital > 0
    ? ((totalVirtualEquity - totalVirtualCapital) / totalVirtualCapital) * 100
    : 0;

  return (
    <section className="card">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="eyebrow">Strategy overview</span>
          <h2
            className="mt-3 text-[24px] font-bold tracking-tight"
            style={{ color: "var(--text-primary)" }}
          >
            전략별 운용 현황
          </h2>
          <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
            각 전략의 모드, 성과, 승격 상태, 가상 자금을 한 번에 모니터링합니다.
          </p>
        </div>
        {totalVirtualCapital > 0 && (
          <div className="flex items-center gap-3">
            <span className="chip">
              가상 총 자산 {formatCompactWon(totalVirtualEquity)}
            </span>
            <span
              className="chip"
              style={{
                color: totalVirtualPnl >= 0 ? "var(--profit)" : "var(--loss)",
              }}
            >
              {totalVirtualPnl >= 0 ? "+" : ""}{totalVirtualPnl.toFixed(2)}%
            </span>
          </div>
        )}
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {strategies.map((item) => (
          <StrategyCard key={item.strategy_id} item={item} />
        ))}
      </div>

      {data?.last_updated && (
        <p className="mt-4 text-right text-xs" style={{ color: "var(--text-muted)" }}>
          마지막 업데이트: {data.last_updated.replace("T", " ").slice(0, 19)}
        </p>
      )}
    </section>
  );
}
