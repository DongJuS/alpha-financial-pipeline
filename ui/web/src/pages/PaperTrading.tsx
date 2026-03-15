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
  useAccountSnapshots,
  useBrokerOrders,
  usePaperTradingOverview,
  usePerformance,
  usePerformanceSeries,
  usePortfolio,
  useTradeHistory,
  useTradingAccountOverview,
  type BrokerOrderItem,
  type PerformanceMetrics,
} from "@/hooks/usePortfolio";
import { formatKRW, formatMDD, formatPct } from "@/utils/api";

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

function orderStatusLabel(status: BrokerOrderItem["status"]): string {
  if (status === "FILLED") return "체결 완료";
  if (status === "REJECTED") return "거부";
  if (status === "CANCELLED") return "취소";
  return "대기";
}

function orderStatusClass(status: BrokerOrderItem["status"]): string {
  if (status === "FILLED") return "badge-buy";
  if (status === "REJECTED" || status === "CANCELLED") return "badge-sell";
  return "badge-hold";
}

function snapshotLabel(snapshotAt: string | null, index: number): string {
  if (!snapshotAt) return index === 0 ? "현재" : `계산 ${index + 1}`;
  return snapshotAt.slice(5, 16).replace("T", " ");
}

export default function PaperTrading() {
  const [period, setPeriod] = useState<PerformanceMetrics["period"]>("monthly");

  const { data: overview, isLoading: overviewLoading } = usePaperTradingOverview();
  const { data: account, isLoading: accountLoading } = useTradingAccountOverview("paper");
  const { data: snapshots, isLoading: snapshotsLoading } = useAccountSnapshots("paper", 30);
  const { data: brokerOrders, isLoading: brokerOrdersLoading } = useBrokerOrders("paper", 20);
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio("paper");
  const { data: perf, isLoading: perfLoading } = usePerformance(period, "paper");
  const { data: series, isLoading: seriesLoading } = usePerformanceSeries(period, "paper");
  const { data: history, isLoading: historyLoading } = useTradeHistory(1, 50, "paper");

  const performanceChartData = useMemo(
    () =>
      (series?.points ?? []).map((point) => ({
        ...point,
        label: compactDate(point.date),
      })),
    [series]
  );

  const snapshotChartData = useMemo(
    () =>
      [...(snapshots?.points ?? [])]
        .reverse()
        .map((point, index) => ({
          ...point,
          label: snapshotLabel(point.snapshot_at, index),
        })),
    [snapshots]
  );

  const positions = portfolio?.positions ?? [];
  const orderRows = brokerOrders?.data ?? [];

  const recentStrategyMix = useMemo(() => {
    const counts = new Map<string, number>();
    (history?.data ?? []).forEach((item) => {
      const key = item.signal_source ?? "UNKNOWN";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
  }, [history?.data]);

  const orderSummary = useMemo(() => {
    const summary = {
      filled: 0,
      rejected: 0,
      pending: 0,
      cancelled: 0,
    };

    orderRows.forEach((item) => {
      if (item.status === "FILLED") summary.filled += 1;
      else if (item.status === "REJECTED") summary.rejected += 1;
      else if (item.status === "CANCELLED") summary.cancelled += 1;
      else summary.pending += 1;
    });

    const terminalCount = summary.filled + summary.rejected + summary.cancelled;
    return {
      ...summary,
      fillRatePct: terminalCount > 0 ? (summary.filled / terminalCount) * 100 : null,
    };
  }, [orderRows]);

  const latestOrder = orderRows[0] ?? null;
  const positiveTotalPnl = (account?.total_pnl ?? 0) >= 0;
  const positiveReturn = (perf?.return_pct ?? 0) >= 0;

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="max-w-[780px]">
            <span className="eyebrow">KIS paper trading</span>
            <h1 className="mt-4 text-[32px] font-extrabold tracking-[-0.04em]" style={{ color: "var(--text-primary)" }}>
              모의 투자
            </h1>
            <p className="mt-3 text-sm leading-6 md:text-base" style={{ color: "var(--text-secondary)" }}>
              한국투자증권 KIS 모의투자 계좌의 예수금, 주문가능금액, 평가금액, 주문 상태, 체결 이력을
              토스형 정보 위계로 다시 정리했습니다.
            </p>

            <div className="mt-5 flex flex-wrap gap-2">
              <span className="chip">{overview?.broker ?? "한국투자증권 KIS"}</span>
              <span className="chip">{overview?.account_label ?? "KIS 모의투자 계좌"}</span>
              <span className="chip">{overview?.current_mode_is_paper ? "현재도 페이퍼 모드" : "실거래 모드와 분리 조회"}</span>
              <span className="chip">
                마지막 스냅샷 {account?.last_snapshot_at ? formatDateTime(account.last_snapshot_at) : "계산 기준"}
              </span>
            </div>
          </div>

          <article className="card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="kpi-label">계좌 브리프</p>
                <h2 className="mt-2 text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {account?.account_label ?? "KIS 모의투자 계좌"}
                </h2>
              </div>
              <span className={positiveTotalPnl ? "badge-buy" : "badge-sell"}>
                {accountLoading ? "집계 중" : `누적 ${formatPct(account?.total_pnl_pct ?? 0)}`}
              </span>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="inner-card">
                <p className="kpi-label">총 자산</p>
                <p className="mt-2 text-[26px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {accountLoading ? "—" : formatKRW(account?.total_equity ?? 0)}
                </p>
              </div>
              <div className="inner-card">
                <p className="kpi-label">주문 가능 금액</p>
                <p className="mt-2 text-[26px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {accountLoading ? "—" : formatKRW(account?.buying_power ?? 0)}
                </p>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="inner-card">
                <p className="kpi-label">보유 종목</p>
                <p className="mt-2 text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {accountLoading ? "—" : `${account?.position_count ?? 0}개`}
                </p>
              </div>
              <div className="inner-card">
                <p className="kpi-label">체결 수</p>
                <p className="mt-2 text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {overviewLoading ? "—" : `${overview?.trade_count_120d ?? 0}건`}
                </p>
              </div>
              <div className="inner-card">
                <p className="kpi-label">운용 일수</p>
                <p className="mt-2 text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {overviewLoading ? "—" : `${overview?.active_days_120d ?? 0}일`}
                </p>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <article className="card">
          <p className="kpi-label">총 자산</p>
          <p className="number-lg mt-2">{accountLoading ? "—" : formatKRW(account?.total_equity ?? 0)}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            예수금 + 평가금액
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">예수금</p>
          <p className="number-lg mt-2">{accountLoading ? "—" : formatKRW(account?.cash_balance ?? 0)}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            체결 반영 후 현금 잔고
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">주문 가능 금액</p>
          <p className="number-lg mt-2">{accountLoading ? "—" : formatKRW(account?.buying_power ?? 0)}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            현재 주문 가능한 최대 금액
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">평가 금액</p>
          <p className="number-lg mt-2">{accountLoading ? "—" : formatKRW(account?.position_market_value ?? 0)}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            보유 종목 시가 평가
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">누적 손익</p>
          <p className={`number-lg mt-2 ${positiveTotalPnl ? "text-profit" : "text-loss"}`}>
            {accountLoading ? "—" : formatKRW(account?.total_pnl ?? 0)}
          </p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            실현 + 평가 손익
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">보유 종목</p>
          <p className="number-lg mt-2">{accountLoading ? "—" : `${account?.position_count ?? 0}개`}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            최근 체결 {overview?.trade_count_120d ?? 0}건
          </p>
        </article>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <section className="card">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                계좌 자산 흐름
              </h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                총 자산과 예수금이 최근 스냅샷 기준으로 어떻게 움직였는지 확인합니다.
              </p>
            </div>
            <span className="chip">{snapshotChartData.length ? `${snapshotChartData.length}개 포인트` : "현재 기준"}</span>
          </div>

          {snapshotsLoading ? (
            <div className="h-80 skeleton" />
          ) : snapshotChartData.length === 0 ? (
            <div className="flex h-80 items-center justify-center rounded-[28px] border border-dashed border-[var(--line-strong)] bg-white/55 px-6 text-center">
              <p className="text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
                아직 계좌 스냅샷이 없습니다. 주문이 실행되거나 계좌 상태가 동기화되면 그래프가 표시됩니다.
              </p>
            </div>
          ) : (
            <div className="chart-container h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={snapshotChartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--chart-axis)" }} />
                  <YAxis tick={{ fontSize: 11, fill: "var(--chart-axis)" }} />
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    formatter={(value: number, name: string) => {
                      const label = name === "total_equity" ? "총 자산" : name === "cash_balance" ? "예수금" : "평가 금액";
                      return [formatKRW(Number(value)), label];
                    }}
                  />
                  <Line type="monotone" dataKey="total_equity" stroke="var(--brand-500)" strokeWidth={2.4} dot={false} />
                  <Line type="monotone" dataKey="cash_balance" stroke="#0F766E" strokeWidth={1.9} dot={false} />
                  <Line
                    type="monotone"
                    dataKey="position_market_value"
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
                  주문 상태
                </h2>
                <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                  브로커 주문 요청 기준 상태 분포
                </p>
              </div>
              <span className="chip">최근 20건</span>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="inner-card">
                <p className="kpi-label">체결 완료</p>
                <p className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-profit">{orderSummary.filled}건</p>
              </div>
              <div className="inner-card">
                <p className="kpi-label">거부 / 취소</p>
                <p className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-loss">
                  {orderSummary.rejected + orderSummary.cancelled}건
                </p>
              </div>
              <div className="inner-card">
                <p className="kpi-label">대기</p>
                <p className="mt-2 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {orderSummary.pending}건
                </p>
              </div>
              <div className="inner-card">
                <p className="kpi-label">체결률</p>
                <p className="mt-2 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  {orderSummary.fillRatePct == null ? "—" : formatPct(orderSummary.fillRatePct)}
                </p>
              </div>
            </div>

            <div className="mt-4 space-y-3">
              <div className="inner-card">
                <p className="kpi-label">최근 주문</p>
                {brokerOrdersLoading ? (
                  <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                    집계 중
                  </p>
                ) : latestOrder ? (
                  <>
                    <div className="mt-2 flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                          {latestOrder.name}
                        </p>
                        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                          {latestOrder.ticker} · {formatDateTime(latestOrder.requested_at)}
                        </p>
                      </div>
                      <span className={orderStatusClass(latestOrder.status)}>{orderStatusLabel(latestOrder.status)}</span>
                    </div>
                    <p className="mt-3 text-xs leading-5" style={{ color: "var(--text-secondary)" }}>
                      {latestOrder.side} {latestOrder.requested_quantity.toLocaleString()}주 · 요청가 {formatKRW(latestOrder.requested_price)}
                    </p>
                  </>
                ) : (
                  <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                    아직 생성된 브로커 주문이 없습니다.
                  </p>
                )}
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
                    <span className="text-loss">{formatMDD(overview.latest_run.max_drawdown_pct ?? 0)}</span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-sm">
                    <span style={{ color: "var(--text-secondary)" }}>Sharpe</span>
                    <span style={{ color: "var(--text-primary)" }}>
                      {overview.latest_run.sharpe_ratio != null ? overview.latest_run.sharpe_ratio.toFixed(2) : "—"}
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
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
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

          {seriesLoading ? (
            <div className="h-80 skeleton" />
          ) : performanceChartData.length === 0 ? (
            <div className="flex h-80 items-center justify-center rounded-[28px] border border-dashed border-[var(--line-strong)] bg-white/55 px-6 text-center">
              <p className="text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
                아직 모의투자 수익률 시계열이 없습니다. 체결 이력이 쌓이면 그래프가 표시됩니다.
              </p>
            </div>
          ) : (
            <div className="chart-container h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={performanceChartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
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

        <section className="card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                성과 메모
              </h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                최근 선택한 기간 기준 핵심 성과 요약
              </p>
            </div>
            <span className={positiveReturn ? "badge-buy" : "badge-sell"}>
              {perfLoading ? "집계 중" : `${PERIOD_LABELS[period]} ${formatPct(perf?.return_pct ?? 0)}`}
            </span>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="inner-card">
              <p className="kpi-label">누적 수익률</p>
              <p className={`mt-2 text-[24px] font-bold tracking-[-0.03em] ${positiveReturn ? "text-profit" : "text-loss"}`}>
                {perfLoading ? "—" : formatPct(perf?.return_pct ?? 0)}
              </p>
            </div>
            <div className="inner-card">
              <p className="kpi-label">MDD</p>
              <p className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-loss">
                {perfLoading ? "—" : formatMDD(perf?.max_drawdown_pct ?? 0)}
              </p>
            </div>
            <div className="inner-card">
              <p className="kpi-label">Sharpe</p>
              <p className="mt-2 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                {perf?.sharpe_ratio != null ? perf.sharpe_ratio.toFixed(2) : "—"}
              </p>
            </div>
            <div className="inner-card">
              <p className="kpi-label">총 거래 수</p>
              <p className="mt-2 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                {perfLoading ? "—" : `${perf?.total_trades ?? 0}건`}
              </p>
            </div>
          </div>

          <div className="mt-4 inner-card">
            <div className="flex items-center justify-between text-sm">
              <span style={{ color: "var(--text-secondary)" }}>마지막 체결 시각</span>
              <span style={{ color: "var(--text-primary)" }}>{formatDateTime(overview?.last_executed_at)}</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-sm">
              <span style={{ color: "var(--text-secondary)" }}>벤치마크</span>
              <span style={{ color: "var(--text-primary)" }}>
                {perf?.kospi_benchmark_pct != null ? formatPct(perf.kospi_benchmark_pct) : "—"}
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-sm">
              <span style={{ color: "var(--text-secondary)" }}>활성 운용 일수</span>
              <span style={{ color: "var(--text-primary)" }}>{overview?.active_days_120d ?? 0}일</span>
            </div>
          </div>
        </section>
      </div>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
            보유 포지션
          </h2>
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
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
            주문 요청 및 체결
          </h2>
          <span className="chip">브로커 주문 20건</span>
        </div>

        {brokerOrdersLoading ? (
          <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-11 skeleton" />)}</div>
        ) : orderRows.length ? (
          <div className="overflow-x-auto" style={{ background: "rgba(255,255,255,0.78)", borderRadius: "24px" }}>
            <table className="table-dark w-full min-w-[1080px]">
              <thead>
                <tr>
                  <th className="px-3 pb-2 pt-3 text-left text-xs" style={{ color: "var(--text-tertiary)" }}>요청 시각</th>
                  <th className="px-3 pb-2 pt-3 text-left text-xs" style={{ color: "var(--text-tertiary)" }}>종목</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>구분</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>요청 수량</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>요청가</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>체결 수량</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>평균 체결가</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>상태</th>
                  <th className="px-3 pb-2 pt-3 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>전략</th>
                </tr>
              </thead>
              <tbody>
                {orderRows.map((item) => (
                  <tr key={item.client_order_id} style={{ borderTop: "1px solid var(--line-soft)" }}>
                    <td className="px-3 py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {formatDateTime(item.requested_at)}
                    </td>
                    <td className="px-3 py-2">
                      <p className="font-semibold" style={{ color: "var(--text-primary)" }}>{item.name}</p>
                      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{item.ticker}</p>
                    </td>
                    <td className={`px-3 py-2 text-right font-semibold ${item.side === "BUY" ? "text-profit" : "text-loss"}`}>
                      {item.side}
                    </td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>{item.requested_quantity.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>{formatKRW(item.requested_price)}</td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>{item.filled_quantity.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>
                      {item.avg_fill_price != null ? formatKRW(item.avg_fill_price) : "-"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className={orderStatusClass(item.status)}>{orderStatusLabel(item.status)}</span>
                    </td>
                    <td className="px-3 py-2 text-right" style={{ color: "var(--text-tertiary)" }}>
                      {item.signal_source ?? "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            아직 브로커 주문 요청이 없습니다.
          </p>
        )}
      </section>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
            모의투자 최근 체결
          </h2>
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
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            모의투자 체결 이력이 없습니다.
          </p>
        )}
      </section>
    </div>
  );
}
