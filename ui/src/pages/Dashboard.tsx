/**
 * ui/src/pages/Dashboard.tsx — 홈 대시보드 (포트폴리오 요약 + 성과 추이 + 시그널 + 에이전트 상태)
 */
import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { usePortfolio, usePerformance, usePerformanceSeries } from "@/hooks/usePortfolio";
import { useCombinedSignals } from "@/hooks/useSignals";
import AgentStatusBar from "@/components/AgentStatusBar/AgentStatusBar";
import SignalCard from "@/components/SignalCard/SignalCard";
import { formatKRW, formatPct } from "@/utils/api";

function compactDate(value: string): string {
  return value.slice(5);
}

export default function Dashboard() {
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio();
  const { data: signalData, isLoading: signalLoading } = useCombinedSignals();
  const { data: perf, isLoading: perfLoading } = usePerformance("monthly");
  const { data: perfSeries, isLoading: seriesLoading } = usePerformanceSeries("monthly");

  const chartData = useMemo(
    () =>
      (perfSeries?.points ?? []).map((point) => ({
        ...point,
        label: compactDate(point.date),
      })),
    [perfSeries]
  );

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">대시보드</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {new Date().toLocaleDateString("ko-KR", {
              year: "numeric",
              month: "long",
              day: "numeric",
              weekday: "long",
            })}
          </p>
        </div>
        {portfolio?.is_paper && (
          <span className="px-3 py-1 rounded-full bg-blue-100 text-blue-700 text-xs font-semibold">
            📄 페이퍼 트레이딩
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="card">
          <p className="text-xs text-gray-500 font-medium">총 평가금액</p>
          <p className="number-lg mt-1">{portfolioLoading ? "—" : formatKRW(portfolio?.total_value ?? 0)}</p>
        </div>

        <div className="card">
          <p className="text-xs text-gray-500 font-medium">평가손익</p>
          {portfolioLoading ? (
            <p className="number-lg mt-1 text-gray-400">—</p>
          ) : (
            <>
              <p
                className={`number-lg mt-1 ${(portfolio?.total_pnl ?? 0) >= 0 ? "text-positive" : "text-negative"}`}
              >
                {formatKRW(portfolio?.total_pnl ?? 0)}
              </p>
              <p
                className={`text-sm font-medium mt-0.5 ${(portfolio?.total_pnl_pct ?? 0) >= 0 ? "text-positive" : "text-negative"}`}
              >
                {formatPct(portfolio?.total_pnl_pct ?? 0)}
              </p>
            </>
          )}
        </div>

        <div className="card">
          <p className="text-xs text-gray-500 font-medium">30일 수익률</p>
          <p className={`number-lg mt-1 ${((perf?.return_pct ?? 0) >= 0 ? "text-positive" : "text-negative")}`}>
            {perfLoading ? "—" : formatPct(perf?.return_pct ?? 0)}
          </p>
          <p className="text-xs text-gray-500 mt-1">KOSPI: {perf?.kospi_benchmark_pct == null ? "—" : formatPct(perf.kospi_benchmark_pct)}</p>
        </div>

        <div className="card">
          <p className="text-xs text-gray-500 font-medium">보유 종목 수</p>
          <p className="number-lg mt-1">
            {portfolioLoading ? "—" : portfolio?.positions.length ?? 0}
            <span className="text-base font-normal text-gray-400 ml-1">종목</span>
          </p>
          <p className="text-xs text-gray-500 mt-1">거래 {perf?.total_trades ?? 0}건</p>
        </div>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-800">누적 성과 추이 (30일)</h2>
          <p className="text-xs text-gray-500">실현손익 기준</p>
        </div>
        {seriesLoading || chartData.length === 0 ? (
          <div className="h-64 bg-gray-50 rounded-xl animate-pulse" />
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="%" />
                <Tooltip
                  formatter={(value: number) => `${Number(value).toFixed(2)}%`}
                  labelFormatter={(label) => `날짜: ${label}`}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="portfolio_return_pct"
                  name="Portfolio"
                  stroke="#2563EB"
                  strokeWidth={2.2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="benchmark_return_pct"
                  name="KOSPI Proxy"
                  stroke="#6B7280"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <AgentStatusBar />

      <div>
        <h2 className="text-base font-semibold text-gray-800 mb-3">
          오늘의 시그널 {!signalLoading && `(${signalData?.signals.length ?? 0}건)`}
        </h2>
        {signalLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="card h-24 animate-pulse bg-gray-50" />
            ))}
          </div>
        ) : signalData?.signals.length === 0 ? (
          <div className="card text-center py-10 text-gray-400">
            <p>아직 오늘의 시그널이 없습니다.</p>
            <p className="text-xs mt-1">08:55 KST 이후 업데이트됩니다.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {signalData?.signals.map((signal, idx) => (
              <SignalCard key={`${signal.ticker}-${idx}`} signal={signal} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
