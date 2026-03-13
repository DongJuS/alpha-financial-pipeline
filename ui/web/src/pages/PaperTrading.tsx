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
  usePaperTradingOverview,
  usePerformance,
  usePerformanceSeries,
  usePortfolio,
  useTradeHistory,
  type PerformanceMetrics,
} from "@/hooks/usePortfolio";
import { formatKRW, formatPct } from "@/utils/api";

const PERIOD_OPTIONS: PerformanceMetrics["period"][] = ["daily", "weekly", "monthly", "all"];
const PERIOD_LABELS: Record<PerformanceMetrics["period"], string> = {
  daily: "일간",
  weekly: "주간",
  monthly: "월간",
  all: "전체",
};

const TOOLTIP_STYLE = {
  background: "rgba(255,255,255,0.96)",
  border: "1px solid rgba(148,163,184,0.2)",
  borderRadius: "20px",
  color: "#111827",
  fontSize: "12px",
  boxShadow: "0 20px 36px rgba(15,23,42,0.12)",
};

function compactDate(value: string): string {
  return value.slice(5);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "기록 없음";
  return value.replace("T", " ").replace("+09:00", "");
}

export default function PaperTrading() {
  const [period, setPeriod] = useState<PerformanceMetrics["period"]>("monthly");

  const { data: overview, isLoading: overviewLoading } = usePaperTradingOverview();
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio("paper");
  const { data: perf, isLoading: perfLoading } = usePerformance(period, "paper");
  const { data: series, isLoading: seriesLoading } = usePerformanceSeries(period, "paper");
  const { data: history, isLoading: historyLoading } = useTradeHistory(1, 50, "paper");

  const chartData = useMemo(
    () =>
      (series?.points ?? []).map((point) => ({
        ...point,
        label: compactDate(point.date),
      })),
    [series]
  );

  const positions = portfolio?.positions ?? [];

  const recentStrategyMix = useMemo(() => {
    const counts = new Map<string, number>();
    (history?.data ?? []).forEach((item) => {
      const key = item.signal_source ?? "UNKNOWN";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
  }, [history?.data]);

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-[780px]">
            <span className="eyebrow">KIS paper trading</span>
            <h1 className="mt-4 text-[32px] font-extrabold tracking-[-0.04em]" style={{ color: "var(--text-primary)" }}>
              모의 투자
            </h1>
            <p className="mt-3 text-sm leading-6 md:text-base" style={{ color: "var(--text-secondary)" }}>
              한국투자증권 KIS 모의투자 계좌에서 발생하는 성과, 포지션, 체결 흐름, 시뮬레이션 결과를
              토스형 정보 위계로 정리했습니다.
            </p>

            <div className="mt-5 flex flex-wrap gap-2">
              <span className="chip">{overview?.broker ?? "한국투자증권 KIS"}</span>
              <span className="chip">{overview?.account_label ?? "KIS 모의투자 계좌"}</span>
              <span className="chip">{overview?.current_mode_is_paper ? "현재도 페이퍼 모드" : "실거래 모드와 분리 조회"}</span>
              {overview?.latest_run && (
                <span className="chip">
                  baseline {overview.latest_run.simulated_days}일 · {formatPct(overview.latest_run.return_pct)}
                </span>
              )}
            </div>
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
                {PERIOD_LABELS[item]}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article className="card">
          <p className="kpi-label">총 자산</p>
          <p className="number-lg mt-2">{portfolioLoading ? "—" : formatKRW(portfolio?.total_value ?? 0)}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            KIS 모의투자 계좌 기준
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">누적 수익률</p>
          <p className={`number-lg mt-2 ${(perf?.return_pct ?? 0) >= 0 ? "text-profit" : "text-loss"}`}>
            {perfLoading ? "—" : formatPct(perf?.return_pct ?? 0)}
          </p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            최근 {PERIOD_LABELS[period]} 기준 실현손익
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">활성 운용 일수</p>
          <p className="number-lg mt-2">{overviewLoading ? "—" : `${overview?.active_days_120d ?? 0}일`}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            최근 120일 내 모의 체결 발생 일수
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">최근 120일 체결 수</p>
          <p className="number-lg mt-2">{overviewLoading ? "—" : `${overview?.trade_count_120d ?? 0}건`}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            거래 종목 {overview?.traded_tickers_120d ?? 0}개
          </p>
        </article>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <section className="card">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                모의 투자 수익률 추이
              </h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                KIS 페이퍼 체결 이력 기반 누적 수익률과 KOSPI 프록시를 비교합니다.
              </p>
            </div>
            <span className="chip">vs KOSPI Proxy</span>
          </div>

          {seriesLoading ? (
            <div className="h-80 skeleton" />
          ) : chartData.length === 0 ? (
            <div className="flex h-80 items-center justify-center rounded-[28px] border border-dashed border-[var(--line-strong)] bg-white/55 px-6 text-center">
              <p className="text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
                아직 모의투자 수익률 시계열이 없습니다. 체결 이력이 쌓이면 그래프가 표시됩니다.
              </p>
            </div>
          ) : (
            <div className="chart-container h-80">
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

        <section className="space-y-4">
          <article className="card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  최근 시뮬레이션
                </h2>
                <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                  baseline 페이퍼 검증 결과
                </p>
              </div>
              {overview?.latest_run && (
                <span
                  className="rounded-full px-3 py-1 text-[11px] font-semibold"
                  style={{
                    background: overview.latest_run.passed ? "var(--green-bg)" : "var(--warning-bg)",
                    color: overview.latest_run.passed ? "var(--green)" : "var(--warning)",
                  }}
                >
                  {overview.latest_run.passed ? "PASS" : "CHECK"}
                </span>
              )}
            </div>

            {overview?.latest_run ? (
              <div className="mt-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="inner-card">
                    <p className="kpi-label">시뮬레이션 일수</p>
                    <p className="mt-2 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                      {overview.latest_run.simulated_days}일
                    </p>
                  </div>
                  <div className="inner-card">
                    <p className="kpi-label">수익률</p>
                    <p
                      className={`mt-2 text-[24px] font-bold tracking-[-0.03em] ${
                        overview.latest_run.return_pct >= 0 ? "text-profit" : "text-loss"
                      }`}
                    >
                      {formatPct(overview.latest_run.return_pct)}
                    </p>
                  </div>
                </div>

                <div className="inner-card">
                  <div className="flex items-center justify-between text-sm">
                    <span style={{ color: "var(--text-secondary)" }}>최대 낙폭</span>
                    <span className="text-loss">{formatPct(overview.latest_run.max_drawdown_pct ?? 0)}</span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-sm">
                    <span style={{ color: "var(--text-secondary)" }}>Sharpe</span>
                    <span style={{ color: "var(--text-primary)" }}>
                      {overview.latest_run.sharpe_ratio != null ? overview.latest_run.sharpe_ratio.toFixed(3) : "—"}
                    </span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-sm">
                    <span style={{ color: "var(--text-secondary)" }}>벤치마크</span>
                    <span style={{ color: "var(--text-primary)" }}>
                      {overview.latest_run.benchmark_return_pct != null
                        ? formatPct(overview.latest_run.benchmark_return_pct)
                        : "—"}
                    </span>
                  </div>
                  <p className="mt-4 text-xs leading-5" style={{ color: "var(--text-secondary)" }}>
                    {overview.latest_run.summary ?? "시뮬레이션 요약이 없습니다."}
                  </p>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
                아직 저장된 페이퍼 시뮬레이션 결과가 없습니다.
              </p>
            )}
          </article>

          <article className="card">
            <h2 className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
              운영 메모
            </h2>
            <div className="mt-4 space-y-3">
              <div className="inner-card">
                <p className="kpi-label">마지막 체결 시각</p>
                <p className="mt-2 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {formatDateTime(overview?.last_executed_at)}
                </p>
              </div>
              <div className="inner-card">
                <p className="kpi-label">최근 전략 소스</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {recentStrategyMix.length ? (
                    recentStrategyMix.map(([key, count]) => (
                      <span key={key} className="chip">
                        {key} {count}건
                      </span>
                    ))
                  ) : (
                    <span className="chip">최근 체결 없음</span>
                  )}
                </div>
              </div>
            </div>
          </article>
        </section>
      </div>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>보유 포지션</h2>
          <span className="chip">{positions.length.toLocaleString()}개 종목</span>
        </div>

        {portfolioLoading ? (
          <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-11 skeleton" />)}</div>
        ) : positions.length === 0 ? (
          <p className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
            모의투자 보유 포지션이 없습니다.
          </p>
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

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>모의투자 최근 체결</h2>
          <span className="chip">최신 50건</span>
        </div>

        {historyLoading ? (
          <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-11 skeleton" />)}</div>
        ) : history?.data.length ? (
          <div className="overflow-x-auto" style={{ background: "rgba(255,255,255,0.78)", borderRadius: "24px" }}>
            <table className="table-dark w-full min-w-[980px]">
              <thead>
                <tr>
                  <th className="px-3 pb-2 pt-3 text-left text-xs" style={{ color: "var(--text-tertiary)" }}>시각</th>
                  <th className="px-3 pb-2 pt-3 text-left text-xs" style={{ color: "var(--text-tertiary)" }}>종목</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>구분</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>수량</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>단가</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>금액</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>전략</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>CB</th>
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
                    <td className="px-3 py-2 text-right">
                      <span className={item.circuit_breaker ? "badge-sell" : "badge-hold"}>
                        {item.circuit_breaker ? "발동" : "-"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>모의투자 체결 이력이 없습니다.</p>
        )}
      </section>
    </div>
  );
}
