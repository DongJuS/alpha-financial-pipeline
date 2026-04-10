/**
 * ui/src/pages/Backtest.tsx
 * Backtest 실행 목록 페이지
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBacktestRuns, type BacktestRunSummary } from "@/hooks/useBacktest";
import { formatPct, formatMDD } from "@/utils/api";

const STRATEGY_OPTIONS = ["All", "RL", "A", "B", "BLEND"] as const;

function StrategyBadge({ strategy }: { strategy: string }) {
  const style =
    strategy === "RL"
      ? { background: "var(--brand-bg)", color: "var(--brand-500)" }
      : strategy === "A"
        ? { background: "var(--green-bg)", color: "var(--green)" }
        : strategy === "B"
          ? { background: "var(--warning-bg)", color: "var(--warning)" }
          : { background: "var(--profit-bg)", color: "var(--profit)" };
  return (
    <span className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold" style={style}>
      {strategy}
    </span>
  );
}

function ReturnCell({ value }: { value: number }) {
  const color = value >= 0 ? "var(--profit)" : "var(--loss)";
  return <span style={{ color, fontWeight: 600 }}>{formatPct(value)}</span>;
}

function RunRow({ run, onClick }: { run: BacktestRunSummary; onClick: () => void }) {
  return (
    <tr
      className="cursor-pointer transition-colors hover:bg-[var(--bg-hover)]"
      onClick={onClick}
    >
      <td className="px-4 py-3 text-sm font-medium" style={{ color: "var(--text-primary)" }}>
        {run.ticker}
      </td>
      <td className="px-4 py-3">
        <StrategyBadge strategy={run.strategy} />
      </td>
      <td className="px-4 py-3 text-sm" style={{ color: "var(--text-secondary)" }}>
        {run.test_start} ~ {run.test_end}
      </td>
      <td className="px-4 py-3 text-right text-sm">
        <ReturnCell value={run.total_return_pct} />
      </td>
      <td className="px-4 py-3 text-right text-sm font-medium" style={{ color: "var(--text-primary)" }}>
        {run.sharpe_ratio.toFixed(2)}
      </td>
      <td className="px-4 py-3 text-right text-sm" style={{ color: "var(--loss)" }}>
        {formatMDD(run.max_drawdown_pct)}
      </td>
      <td className="px-4 py-3 text-right text-sm" style={{ color: "var(--text-secondary)" }}>
        {(run.win_rate * 100).toFixed(1)}%
      </td>
      <td className="px-4 py-3 text-right text-sm" style={{ color: "var(--text-tertiary)" }}>
        {run.total_trades}
      </td>
      <td className="px-4 py-3 text-right text-xs" style={{ color: "var(--text-faint)" }}>
        {run.created_at.slice(0, 10)}
      </td>
    </tr>
  );
}

export default function Backtest() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [strategy, setStrategy] = useState<string>("All");

  const filterStrategy = strategy === "All" ? undefined : strategy;
  const { data, isLoading, isError } = useBacktestRuns(page, 20, filterStrategy);

  const runs = data?.data ?? [];
  const meta = data?.meta ?? { page: 1, per_page: 20, total: 0 };
  const totalPages = Math.max(1, Math.ceil(meta.total / meta.per_page));

  return (
    <div className="page-shell space-y-5">
      {/* Hero */}
      <section className="hero-section">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>
              전략 검증
            </p>
            <h1
              className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]"
              style={{ color: "var(--text-primary)" }}
            >
              백테스트
            </h1>
            <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
              과거 데이터로 전략 성과를 검증합니다. RL / Strategy A / Strategy B 결과를 비교하세요.
            </p>
          </div>

          {/* Strategy filter */}
          <div className="flex items-center gap-1.5">
            {STRATEGY_OPTIONS.map((opt) => (
              <button
                key={opt}
                onClick={() => {
                  setStrategy(opt);
                  setPage(1);
                }}
                className="rounded-2xl px-3 py-1.5 text-sm font-semibold transition-all"
                style={
                  strategy === opt
                    ? { background: "linear-gradient(135deg, var(--brand-500), #4b9dff)", color: "#fff" }
                    : { background: "rgba(255,255,255,0.72)", color: "var(--text-secondary)" }
                }
              >
                {opt}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Table */}
      <section className="card overflow-hidden p-0">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--brand-500)] border-t-transparent" />
          </div>
        ) : isError ? (
          <div className="py-20 text-center text-sm" style={{ color: "var(--text-muted)" }}>
            백테스트 데이터를 불러오지 못했습니다.
          </div>
        ) : runs.length === 0 ? (
          <div className="py-20 text-center text-sm" style={{ color: "var(--text-muted)" }}>
            아직 백테스트 실행 기록이 없습니다.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--line-soft)" }}>
                  {["종목", "전략", "테스트 기간", "수익률", "샤프", "MDD", "승률", "매매", "생성일"].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-4 py-3 text-xs font-semibold"
                        style={{ color: "var(--text-faint)" }}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: "var(--line-soft)" }}>
                {runs.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    onClick={() => navigate(`/backtest/${run.id}`)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div
            className="flex items-center justify-between border-t px-4 py-3"
            style={{ borderColor: "var(--line-soft)" }}
          >
            <span className="text-xs" style={{ color: "var(--text-faint)" }}>
              {meta.total}건 중 {(page - 1) * meta.per_page + 1}~
              {Math.min(page * meta.per_page, meta.total)}
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="rounded-xl px-3 py-1.5 text-sm font-semibold transition-colors disabled:opacity-40"
                style={{ color: "var(--brand-500)" }}
              >
                이전
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="rounded-xl px-3 py-1.5 text-sm font-semibold transition-colors disabled:opacity-40"
                style={{ color: "var(--brand-500)" }}
              >
                다음
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
