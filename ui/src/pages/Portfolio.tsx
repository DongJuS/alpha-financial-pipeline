/**
 * ui/src/pages/Portfolio.tsx
 * Portfolio overview with Toss-like readability and spacing.
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
  useTradeHistory,
  type PerformanceMetrics,
} from "@/hooks/usePortfolio";
import { formatKRW, formatPct } from "@/utils/api";

const PERIOD_OPTIONS: PerformanceMetrics["period"][] = ["daily", "weekly", "monthly", "all"];

function compactDate(value: string): string {
  return value.slice(5);
}

export default function Portfolio() {
  const [period, setPeriod] = useState<PerformanceMetrics["period"]>("monthly");
  const { data: portfolio, isLoading } = usePortfolio();
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

  return (
    <div className="page-shell space-y-4">
      <section className="rounded-[30px] bg-[#F2F4F6] px-6 py-6 shadow-[0_12px_28px_rgba(25,31,40,0.06)] md:px-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[13px] font-semibold text-[#8B95A1]">내 계좌</p>
            <h1 className="mt-1 text-[32px] font-extrabold tracking-[-0.03em] text-[#191F28]">포트폴리오</h1>
            <p className="mt-2 text-sm text-[#8B95A1]">성과와 포지션을 한 화면에서 확인하고 리스크를 조절합니다.</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {PERIOD_OPTIONS.map((item) => (
              <button
                key={item}
                onClick={() => setPeriod(item)}
                className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition-transform hover:scale-105 ${
                  period === item ? "bg-[#0019FF] text-white" : "bg-white text-[#4E5968]"
                }`}
              >
                {item}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <span className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#191F28]">
            총 자산 {portfolio ? formatKRW(portfolio.total_value) : "집계 중"}
          </span>
          <span className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#191F28]">
            누적 손익 {portfolio ? formatKRW(portfolio.total_pnl) : "집계 중"}
          </span>
          <span className="rounded-full bg-[#EAF1FF] px-3 py-1.5 text-xs font-semibold text-[#0019FF]">
            {portfolio?.is_paper ? "페이퍼 트레이딩" : "실거래"}
          </span>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article className="card">
          <p className="kpi-label">수익률</p>
          <p className={`number-lg mt-1 ${(perf?.return_pct ?? 0) >= 0 ? "text-profit" : "text-loss"}`}>
            {perfLoading ? "—" : formatPct(perf?.return_pct ?? 0)}
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">최대 낙폭 (MDD)</p>
          <p className="number-lg mt-1 text-loss">{perfLoading ? "—" : formatPct(perf?.max_drawdown_pct ?? 0)}</p>
        </article>
        <article className="card">
          <p className="kpi-label">Sharpe Ratio</p>
          <p className="number-lg mt-1 text-[#191F28]">
            {perfLoading ? "—" : perf?.sharpe_ratio == null ? "—" : perf.sharpe_ratio.toFixed(3)}
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">승률</p>
          <p className="number-lg mt-1 text-[#191F28]">{perfLoading ? "—" : `${Math.round((perf?.win_rate ?? 0) * 100)}%`}</p>
          <p className="mt-1 text-xs text-[#8B95A1]">거래 {(perf?.total_trades ?? 0).toLocaleString()}건</p>
        </article>
      </section>

      <section className="card">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-base font-bold text-[#191F28]">누적 수익률 추이</h2>
          <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-[#8B95A1]">vs KOSPI Proxy</span>
        </div>

        {seriesLoading || chartData.length === 0 ? (
          <div className="h-72 rounded-2xl bg-white animate-pulse" />
        ) : (
          <div className="h-72 rounded-2xl bg-white px-2 py-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E8EBEF" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#8B95A1" }} />
                <YAxis tick={{ fontSize: 11, fill: "#8B95A1" }} unit="%" />
                <Tooltip formatter={(value: number) => `${Number(value).toFixed(2)}%`} />
                <Line type="monotone" dataKey="portfolio_return_pct" stroke="#0019FF" strokeWidth={2.2} dot={false} />
                <Line type="monotone" dataKey="benchmark_return_pct" stroke="#94A3B8" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold text-[#191F28]">보유 포지션</h2>
          <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-[#8B95A1]">
            {positions.length.toLocaleString()}개 종목
          </span>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-11 rounded-2xl bg-white animate-pulse" />
            ))}
          </div>
        ) : positions.length === 0 ? (
          <p className="py-8 text-center text-sm text-[#8B95A1]">보유 중인 종목이 없습니다.</p>
        ) : (
          <div className="overflow-x-auto rounded-2xl bg-white px-3 py-2">
            <table className="w-full min-w-[780px] text-sm">
              <thead>
                <tr className="text-left text-xs text-[#8B95A1]">
                  <th className="pb-2">종목</th>
                  <th className="pb-2 text-right">수량</th>
                  <th className="pb-2 text-right">평균가</th>
                  <th className="pb-2 text-right">현재가</th>
                  <th className="pb-2 text-right">평가손익</th>
                  <th className="pb-2 text-right">비중</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EEF1F5]">
                {positions.map((pos) => (
                  <tr key={pos.ticker}>
                    <td className="py-3">
                      <p className="font-semibold text-[#191F28]">{pos.name}</p>
                      <p className="text-xs text-[#8B95A1]">{pos.ticker}</p>
                    </td>
                    <td className="py-3 text-right text-[#4E5968]">{pos.quantity.toLocaleString()}</td>
                    <td className="py-3 text-right text-[#4E5968]">{formatKRW(pos.avg_price)}</td>
                    <td className="py-3 text-right text-[#4E5968]">{formatKRW(pos.current_price)}</td>
                    <td className={`py-3 text-right font-semibold ${pos.unrealized_pnl >= 0 ? "text-profit" : "text-loss"}`}>
                      {formatKRW(pos.unrealized_pnl)}
                    </td>
                    <td className="py-3 text-right text-[#8B95A1]">{pos.weight_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold text-[#191F28]">최근 거래 이력</h2>
          <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-[#8B95A1]">최신 30건</span>
        </div>

        {historyLoading ? (
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-11 rounded-2xl bg-white animate-pulse" />
            ))}
          </div>
        ) : history?.data.length ? (
          <div className="overflow-x-auto rounded-2xl bg-white px-3 py-2">
            <table className="w-full min-w-[920px] text-sm">
              <thead>
                <tr className="text-left text-xs text-[#8B95A1]">
                  <th className="pb-2">시각</th>
                  <th className="pb-2">종목</th>
                  <th className="pb-2 text-right">구분</th>
                  <th className="pb-2 text-right">수량</th>
                  <th className="pb-2 text-right">단가</th>
                  <th className="pb-2 text-right">금액</th>
                  <th className="pb-2 text-right">전략</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EEF1F5]">
                {history.data.map((item, idx) => (
                  <tr key={`${item.executed_at}-${item.ticker}-${idx}`}>
                    <td className="py-2 text-xs text-[#8B95A1]">{item.executed_at.replace("T", " ")}</td>
                    <td className="py-2">
                      <p className="font-semibold text-[#191F28]">{item.name}</p>
                      <p className="text-xs text-[#8B95A1]">{item.ticker}</p>
                    </td>
                    <td className={`py-2 text-right font-semibold ${item.side === "BUY" ? "text-profit" : "text-loss"}`}>{item.side}</td>
                    <td className="py-2 text-right text-[#4E5968]">{item.quantity.toLocaleString()}</td>
                    <td className="py-2 text-right text-[#4E5968]">{formatKRW(item.price)}</td>
                    <td className="py-2 text-right text-[#4E5968]">{formatKRW(item.amount)}</td>
                    <td className="py-2 text-right text-[#8B95A1]">{item.signal_source ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-[#8B95A1]">거래 이력이 없습니다.</p>
        )}
      </section>
    </div>
  );
}
