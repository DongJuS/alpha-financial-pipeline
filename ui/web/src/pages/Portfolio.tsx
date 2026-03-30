/**
 * ui/src/pages/Portfolio.tsx
 * Portfolio overview — Toss Invest dark theme.
 */
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  usePerformance,
  usePerformanceSeries,
  usePortfolio,
  useTradingAccountOverview,
  useTradeHistory,
  type PerformanceMetrics,
} from "@/hooks/usePortfolio";
import { formatKRW, formatMDD, formatPct } from "@/utils/api";

const PERIOD_OPTIONS: PerformanceMetrics["period"][] = ["daily", "weekly", "monthly", "all"];

function compactDate(value: string): string {
  if (!value) return "—";
  return value.slice(5);
}

const TOOLTIP_STYLE = {
  background: "rgba(255,255,255,0.96)",
  border: "1px solid rgba(148,163,184,0.2)",
  borderRadius: "20px",
  color: "#111827",
  fontSize: "12px",
  boxShadow: "0 20px 36px rgba(15,23,42,0.12)",
};

export default function Portfolio() {
  const [period, setPeriod] = useState<PerformanceMetrics["period"]>("monthly");
  const { data: portfolio, isLoading } = usePortfolio();
  const { data: accountOverview, isLoading: accountLoading } = useTradingAccountOverview();
  const { data: perf, isLoading: perfLoading } = usePerformance(period);
  const { data: series, isLoading: seriesLoading } = usePerformanceSeries(period);
  const { data: history, isLoading: historyLoading } = useTradeHistory(1, 30);

  const chartData = useMemo(
    () =>
      (series?.points ?? []).map((point) => ({
        ...point,
        label: compactDate(point.date),
      })),
    [series]
  );
  const positions = portfolio?.positions ?? [];
  const totalAsset = accountOverview?.total_equity ?? portfolio?.total_value ?? 0;
  const totalPnl = accountOverview?.total_pnl ?? portfolio?.total_pnl ?? 0;
  const accountScope = accountOverview?.account_scope ?? (portfolio?.is_paper ? "paper" : "real");

  return (
    <div className="page-shell space-y-5">
      {/* Hero */}
      <section className="hero-section">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>내 계좌</p>
            <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
              포트폴리오
            </h1>
            <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
              성과와 포지션을 한 화면에서 확인하고 리스크를 조절합니다.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {PERIOD_OPTIONS.map((item) => (
              <button
                key={item}
                onClick={() => setPeriod(item)}
                className="rounded-full px-3 py-1.5 text-xs font-semibold transition-all"
                style={{
                  background: period === item ? "var(--brand-500)" : "rgba(255,255,255,0.72)",
                  color: period === item ? "#fff" : "var(--text-secondary)",
                  boxShadow: period === item ? "0 12px 24px rgba(31,99,247,0.18)" : "none",
                }}
              >
                {item}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <span className="px-3 py-1.5 text-xs font-semibold" style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", borderRadius: "4px" }}>
            총 자산 {accountLoading && !portfolio ? "집계 중" : formatKRW(totalAsset)}
          </span>
          <span className="px-3 py-1.5 text-xs font-semibold" style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", borderRadius: "4px" }}>
            누적 손익 {accountLoading && !portfolio ? "집계 중" : formatKRW(totalPnl)}
          </span>
          <span className="chip">{accountScope === "paper" ? "페이퍼 트레이딩" : "실거래"}</span>
        </div>
      </section>

      {/* KPI Grid */}
      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article className="card">
          <p className="kpi-label">실현 수익률</p>
          <p className={`number-lg mt-1 ${(perf?.return_pct ?? 0) >= 0 ? "text-profit" : "text-loss"}`}>
            {perfLoading ? "—" : formatPct(perf?.return_pct ?? 0)}
          </p>
          <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>매도 완료 기준</p>
        </article>
        <article className="card">
          <p className="kpi-label">최대 낙폭 (MDD)</p>
          <p className="number-lg mt-1 text-loss">
            {perfLoading ? "—" : formatMDD(perf?.max_drawdown_pct ?? 0)}
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">Sharpe Ratio</p>
          <p className="number-lg mt-1" style={{ color: "var(--text-primary)" }}>
            {perfLoading ? "—" : perf?.sharpe_ratio == null ? "—" : perf.sharpe_ratio.toFixed(2)}
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">승률</p>
          <p className="number-lg mt-1" style={{ color: "var(--text-primary)" }}>
            {perfLoading ? "—" : (perf?.win_rate === 0 && perf?.total_trades === 0) || perf?.win_rate == null ? "—" : perf.win_rate === 0 ? "매도 없음" : `${Math.round(perf.win_rate * 100)}%`}
          </p>
          <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>거래 {(perf?.total_trades ?? 0).toLocaleString()}건</p>
        </article>
      </section>

      {/* Chart */}
      <section className="card">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>누적 수익률 추이</h2>
          <span className="px-2.5 py-1 text-[11px] font-semibold" style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", borderRadius: "4px" }}>
            vs KOSPI Proxy
          </span>
        </div>

        {seriesLoading || chartData.length === 0 ? (
          <div className="h-72 skeleton" />
        ) : (
          <div className="chart-container h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--chart-axis)" }} />
                <YAxis tick={{ fontSize: 11, fill: "var(--chart-axis)" }} unit="%" />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value: number) => `${Number(value).toFixed(2)}%`} />
                <Line type="monotone" dataKey="portfolio_return_pct" stroke="var(--brand-500)" strokeWidth={2.4} dot={false} />
                <Line
                  type="monotone"
                  dataKey="benchmark_return_pct"
                  stroke="#94A3B8"
                  strokeWidth={1.7}
                  dot={false}
                  strokeDasharray="4 4"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* Positions */}
      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>보유 포지션</h2>
          <span className="px-2.5 py-1 text-[11px] font-semibold" style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", borderRadius: "4px" }}>
            {positions.length.toLocaleString()}개 종목
          </span>
        </div>

        {isLoading ? (
          <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-11 skeleton" />)}</div>
        ) : positions.length === 0 ? (
          <p className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>보유 중인 종목이 없습니다.</p>
        ) : (
          <div className="overflow-x-auto" style={{ background: "rgba(255,255,255,0.78)", borderRadius: "24px" }}>
            <table className="table-dark w-full min-w-[780px]">
              <thead>
                <tr>
                  <th className="px-3 pb-2 pt-3 text-left text-xs" style={{ color: "var(--text-tertiary)" }}>종목</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>수량</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>평균가</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>현재가</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>평가손익</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>비중</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr key={pos.ticker} style={{ borderTop: "1px solid var(--line-soft)" }}>
                    <td className="px-3 py-3">
                      <p className="font-semibold" style={{ color: "var(--text-primary)" }}>{pos.name}</p>
                      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{pos.ticker}</p>
                    </td>
                    <td className="px-3 py-3 text-right" style={{ color: "var(--text-secondary)" }}>{pos.quantity.toLocaleString()}</td>
                    <td className="px-3 py-3 text-right" style={{ color: "var(--text-secondary)" }}>{formatKRW(pos.avg_price)}</td>
                    <td className="px-3 py-3 text-right" style={{ color: "var(--text-secondary)" }}>{formatKRW(pos.current_price)}</td>
                    <td className={`px-3 py-3 text-right font-semibold ${pos.unrealized_pnl >= 0 ? "text-profit" : "text-loss"}`}>
                      {formatKRW(pos.unrealized_pnl)}
                    </td>
                    <td className="px-3 py-3 text-right" style={{ color: "var(--text-secondary)" }}>{pos.weight_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Trade History */}
      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>최근 거래 이력</h2>
          <span className="px-2.5 py-1 text-[11px] font-semibold" style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", borderRadius: "4px" }}>
            최신 30건
          </span>
        </div>

        {historyLoading ? (
          <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-11 skeleton" />)}</div>
        ) : history?.data.length ? (
          <div className="overflow-x-auto" style={{ background: "rgba(255,255,255,0.78)", borderRadius: "24px" }}>
            <table className="table-dark w-full min-w-[920px]">
              <thead>
                <tr>
                  <th className="px-3 pb-2 pt-3 text-left text-xs" style={{ color: "var(--text-tertiary)" }}>시각</th>
                  <th className="px-3 pb-2 pt-3 text-left text-xs" style={{ color: "var(--text-tertiary)" }}>종목</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>구분</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>수량</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>단가</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>금액</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>전략</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((item, idx) => (
                  <tr key={`${item.executed_at}-${item.ticker}-${idx}`} style={{ borderTop: "1px solid var(--line-soft)" }}>
                    <td className="px-3 py-2 text-xs" style={{ color: "var(--text-secondary)" }}>{item.executed_at.replace("T", " ")}</td>
                    <td className="px-3 py-2">
                      <p className="font-semibold" style={{ color: "var(--text-primary)" }}>{item.name}</p>
                      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{item.ticker}</p>
                    </td>
                    <td className={`px-3 py-2 text-right font-semibold ${item.side === "BUY" ? "text-profit" : "text-loss"}`}>{item.side}</td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>{item.quantity.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>{formatKRW(item.price)}</td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>{formatKRW(item.amount)}</td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-tertiary)" }}>{item.signal_source ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>거래 이력이 없습니다.</p>
        )}
      </section>
    </div>
  );
}
