/**
 * ui/src/pages/BacktestDetail.tsx
 * Backtest 상세 결과 페이지 — 성과 지표 + 포트폴리오 가치 곡선 + 일별 수익률
 */
import { useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { useBacktestDetail, useBacktestDaily } from "@/hooks/useBacktest";
import { formatKRW, formatPct, formatMDD } from "@/utils/api";

const TOOLTIP_STYLE = {
  background: "rgba(255,255,255,0.96)",
  border: "1px solid rgba(148,163,184,0.2)",
  borderRadius: "20px",
  color: "#111827",
  fontSize: "12px",
  boxShadow: "0 20px 36px rgba(15,23,42,0.12)",
};

function compactDate(value: string): string {
  if (!value) return "";
  return value.slice(5);
}

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="card space-y-1">
      <p className="text-xs font-semibold" style={{ color: "var(--text-faint)" }}>
        {label}
      </p>
      <p
        className="text-[22px] font-extrabold tracking-[-0.02em]"
        style={{ color: color ?? "var(--text-primary)" }}
      >
        {value}
      </p>
    </div>
  );
}

export default function BacktestDetail() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const numericId = runId ? Number(runId) : null;

  const { data: detail, isLoading: detailLoading } = useBacktestDetail(numericId);
  const { data: daily, isLoading: dailyLoading } = useBacktestDaily(numericId);

  const chartData = useMemo(
    () =>
      (daily ?? []).map((d) => ({
        ...d,
        label: compactDate(d.date),
        daily_return_display: Number((d.daily_return_pct * 100).toFixed(2)),
      })),
    [daily],
  );

  if (detailLoading) {
    return (
      <div className="page-shell">
        <div className="flex items-center justify-center py-32">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--brand-500)] border-t-transparent" />
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="page-shell">
        <div className="py-32 text-center text-sm" style={{ color: "var(--text-muted)" }}>
          백테스트 결과를 찾을 수 없습니다.
        </div>
      </div>
    );
  }

  const returnColor = detail.total_return_pct >= 0 ? "var(--profit)" : "var(--loss)";

  return (
    <div className="page-shell space-y-5">
      {/* Header */}
      <section className="hero-section">
        <button
          onClick={() => navigate("/backtest")}
          className="mb-3 text-sm font-semibold transition-colors"
          style={{ color: "var(--brand-500)" }}
        >
          &larr; 목록으로
        </button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1
                className="text-[30px] font-extrabold tracking-[-0.03em]"
                style={{ color: "var(--text-primary)" }}
              >
                {detail.ticker}
              </h1>
              <span
                className="inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{ background: "var(--brand-bg)", color: "var(--brand-500)" }}
              >
                {detail.strategy}
              </span>
            </div>
            <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
              학습: {detail.train_start} ~ {detail.train_end} | 테스트: {detail.test_start} ~{" "}
              {detail.test_end}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs font-semibold" style={{ color: "var(--text-faint)" }}>
              총 수익률
            </p>
            <p
              className="text-[28px] font-extrabold tracking-[-0.02em]"
              style={{ color: returnColor }}
            >
              {formatPct(detail.total_return_pct)}
            </p>
          </div>
        </div>
      </section>

      {/* Config summary */}
      <section className="card">
        <h3 className="text-xs font-semibold" style={{ color: "var(--text-faint)" }}>
          실행 설정
        </h3>
        <div className="mt-2 flex flex-wrap gap-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          <span>초기자본: {formatKRW(detail.initial_capital)}</span>
          <span>수수료: {detail.commission_rate_pct}%</span>
          <span>세금: {detail.tax_rate_pct}%</span>
          <span>슬리피지: {detail.slippage_bps}bps</span>
        </div>
      </section>

      {/* Metrics grid */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="연환산 수익률" value={formatPct(detail.annual_return_pct)} color={returnColor} />
        <MetricCard label="샤프 비율" value={detail.sharpe_ratio.toFixed(2)} />
        <MetricCard label="MDD" value={formatMDD(detail.max_drawdown_pct)} color="var(--loss)" />
        <MetricCard label="승률" value={`${(detail.win_rate * 100).toFixed(1)}%`} />
        <MetricCard label="매매 횟수" value={String(detail.total_trades)} />
        <MetricCard label="평균 보유일" value={`${detail.avg_holding_days.toFixed(1)}일`} />
        <MetricCard
          label="Buy & Hold"
          value={formatPct(detail.baseline_return_pct)}
          color={detail.baseline_return_pct >= 0 ? "var(--profit)" : "var(--loss)"}
        />
        <MetricCard
          label="초과 수익률"
          value={formatPct(detail.excess_return_pct)}
          color={detail.excess_return_pct >= 0 ? "var(--green)" : "var(--loss)"}
        />
      </section>

      {/* Portfolio value chart */}
      <section className="card">
        <h3 className="mb-4 text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          포트폴리오 가치 곡선
        </h3>
        {dailyLoading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--brand-500)] border-t-transparent" />
          </div>
        ) : chartData.length === 0 ? (
          <div className="py-16 text-center text-sm" style={{ color: "var(--text-muted)" }}>
            일별 데이터가 없습니다.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "var(--chart-axis)" }}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 11, fill: "var(--chart-axis)" }}
                tickFormatter={(v: number) => `${(v / 1_000_000).toFixed(1)}M`}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number) => [formatKRW(v), "가치"]} />
              <Line
                type="monotone"
                dataKey="portfolio_value"
                stroke="var(--brand-500)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>

      {/* Daily return bar chart */}
      <section className="card">
        <h3 className="mb-4 text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          일별 수익률
        </h3>
        {dailyLoading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--brand-500)] border-t-transparent" />
          </div>
        ) : chartData.length === 0 ? (
          <div className="py-16 text-center text-sm" style={{ color: "var(--text-muted)" }}>
            일별 데이터가 없습니다.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10, fill: "var(--chart-axis)" }}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 10, fill: "var(--chart-axis)" }}
                tickFormatter={(v: number) => `${v.toFixed(1)}%`}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v: number) => [`${v.toFixed(2)}%`, "일별 수익률"]}
              />
              <ReferenceLine y={0} stroke="var(--line-strong)" />
              <Bar
                dataKey="daily_return_display"
                fill="var(--brand-500)"
                radius={[2, 2, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </section>
    </div>
  );
}
