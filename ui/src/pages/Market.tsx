/**
 * ui/src/pages/Market.tsx
 * Market page with cleaner Toss-like chart controls and hierarchy.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/utils/api";

type IndexPayload = {
  kospi: { value: number; change_pct: number };
  kosdaq: { value: number; change_pct: number };
};

type TickerItem = {
  ticker: string;
  name: string;
  market: string;
};

type OhlcvItem = {
  timestamp_kst: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change_pct: number;
};

type RealtimePoint = {
  timestamp_kst: string;
  current_price: number;
  volume: number | null;
  change_pct: number | null;
  source: string | null;
};

type RealtimePayload = {
  ticker: string;
  name: string;
  points: RealtimePoint[];
};

type ChartSource = "db" | "opensource";

function useMarketIndex() {
  return useQuery({
    queryKey: ["market", "index"],
    queryFn: async () => {
      const { data } = await api.get<IndexPayload>("/market/index");
      return data;
    },
    refetchInterval: 30_000,
  });
}

function useTickerList() {
  return useQuery({
    queryKey: ["market", "tickers"],
    queryFn: async () => {
      const { data } = await api.get<{ data: TickerItem[] }>("/market/tickers", {
        params: { page: 1, per_page: 50 },
      });
      return data.data;
    },
    refetchInterval: 120_000,
  });
}

function useOhlcv(ticker: string | null, source: ChartSource) {
  return useQuery({
    queryKey: ["market", "ohlcv", source, ticker],
    enabled: !!ticker,
    queryFn: async () => {
      const path = source === "opensource" ? `/market/opensource/ohlcv/${ticker}` : `/market/ohlcv/${ticker}`;
      const { data } = await api.get<{ ticker: string; name: string; data: OhlcvItem[] }>(path, {
        params: source === "opensource" ? { days: 120 } : {},
      });
      return data;
    },
    refetchInterval: source === "opensource" ? 60_000 : 30_000,
  });
}

function useRealtimeSeries(ticker: string | null) {
  return useQuery({
    queryKey: ["market", "realtime", ticker],
    enabled: !!ticker,
    queryFn: async () => {
      const { data } = await api.get<RealtimePayload>(`/market/realtime/${ticker}`, {
        params: { limit: 120 },
      });
      return data;
    },
    refetchInterval: 5_000,
  });
}

function shortTime(ts: string): string {
  return ts.slice(5, 16).replace("T", " ");
}

function shortClock(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(11, 19);
  return d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export default function Market() {
  const { data: index, isLoading: indexLoading } = useMarketIndex();
  const { data: tickers, isLoading: tickersLoading } = useTickerList();

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartSource, setChartSource] = useState<ChartSource>("db");
  const activeTicker = selectedTicker ?? tickers?.[0]?.ticker ?? null;

  const { data: ohlcv, isLoading: ohlcvLoading } = useOhlcv(activeTicker, chartSource);
  const { data: realtime, isLoading: realtimeLoading } = useRealtimeSeries(activeTicker);

  const chartData = useMemo(
    () =>
      (ohlcv?.data ?? [])
        .slice()
        .reverse()
        .map((item) => ({
          ...item,
          label: shortTime(item.timestamp_kst),
          oc_mid: (item.open + item.close) / 2,
        })),
    [ohlcv]
  );

  const realtimeData = useMemo(
    () =>
      (realtime?.points ?? []).map((item) => ({
        ...item,
        label: shortClock(item.timestamp_kst),
      })),
    [realtime]
  );

  return (
    <div className="page-shell space-y-4">
      <section className="rounded-[30px] bg-[#F2F4F6] px-6 py-6 shadow-[0_12px_28px_rgba(25,31,40,0.06)] md:px-7">
        <p className="text-[13px] font-semibold text-[#8B95A1]">시장 데이터</p>
        <h1 className="mt-1 text-[32px] font-extrabold tracking-[-0.03em] text-[#191F28]">마켓 센터</h1>
        <p className="mt-2 text-sm text-[#8B95A1]">내부 수집 데이터와 오픈소스 데이터를 하나의 흐름으로 비교합니다.</p>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {["kospi", "kosdaq"].map((key) => {
          const item = index?.[key as keyof IndexPayload];
          const positive = (item?.change_pct ?? 0) >= 0;
          return (
            <article key={key} className="card">
              <p className="kpi-label">{key.toUpperCase()}</p>
              {indexLoading ? (
                <div className="mt-2 h-8 rounded-xl bg-white animate-pulse" />
              ) : (
                <>
                  <p className="number-lg mt-1">{item?.value?.toLocaleString("ko-KR") ?? "—"}</p>
                  <p className={`mt-0.5 text-sm font-semibold ${positive ? "text-profit" : "text-loss"}`}>
                    {item?.change_pct != null ? `${item.change_pct >= 0 ? "+" : ""}${item.change_pct.toFixed(2)}%` : "—"}
                  </p>
                </>
              )}
            </article>
          );
        })}
      </section>

      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-bold text-[#191F28]">종목 OHLCV 차트</h2>
            <p className="mt-1 text-xs text-[#8B95A1]">
              {ohlcv?.name ? `${ohlcv.name} (${ohlcv.ticker})` : "종목 선택"} · {chartSource === "db" ? "내부 수집 DB" : "오픈소스 API(FDR)"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="min-w-[190px] bg-white"
              value={activeTicker ?? ""}
              onChange={(e) => setSelectedTicker(e.target.value)}
              disabled={tickersLoading || !tickers?.length}
            >
              {(tickers ?? []).map((item) => (
                <option key={item.ticker} value={item.ticker}>
                  {item.ticker} · {item.name}
                </option>
              ))}
            </select>
            <select className="min-w-[140px] bg-white" value={chartSource} onChange={(e) => setChartSource(e.target.value as ChartSource)}>
              <option value="db">내부 DB</option>
              <option value="opensource">오픈소스 API</option>
            </select>
          </div>
        </div>

        {ohlcvLoading || chartData.length === 0 ? (
          <div className="h-72 rounded-2xl bg-white animate-pulse" />
        ) : (
          <div className="space-y-3">
            <div className="h-72 rounded-2xl bg-white px-2 py-2">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#8B95A1" }} minTickGap={16} />
                  <YAxis yAxisId="price" orientation="right" tick={{ fontSize: 11, fill: "#8B95A1" }} domain={["auto", "auto"]} />
                  <Tooltip
                    formatter={(value: number, name: string) => {
                      if (["open", "high", "low", "close"].includes(name)) {
                        return [Number(value).toLocaleString("ko-KR"), name.toUpperCase()];
                      }
                      return [Number(value).toLocaleString("ko-KR"), name];
                    }}
                  />
                  <Bar yAxisId="price" dataKey="high" fill="#E8EBEF" radius={[2, 2, 0, 0]} barSize={2} />
                  <Bar yAxisId="price" dataKey="low" fill="#E8EBEF" radius={[0, 0, 2, 2]} barSize={2} />
                  <Bar yAxisId="price" dataKey="oc_mid" fill="#A9B8FF" barSize={6} />
                  <Area yAxisId="price" dataKey="close" stroke="#0019FF" fill="#EAF1FF" fillOpacity={0.45} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            <div className="h-36 rounded-2xl bg-white px-2 py-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#8B95A1" }} minTickGap={16} />
                  <YAxis tick={{ fontSize: 10, fill: "#8B95A1" }} orientation="right" />
                  <Tooltip formatter={(value: number) => Number(value).toLocaleString("ko-KR")} />
                  <Area dataKey="volume" stroke="#0EA5E9" fill="#D9F1FF" fillOpacity={0.55} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </section>

      <section className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-[#191F28]">실시간 가격 추이</h2>
          <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-[#8B95A1]">5초 폴링</span>
        </div>

        {realtimeLoading || realtimeData.length === 0 ? (
          <div className="h-56 rounded-2xl bg-white animate-pulse" />
        ) : (
          <div className="h-56 rounded-2xl bg-white px-2 py-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={realtimeData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#8B95A1" }} minTickGap={16} />
                <YAxis tick={{ fontSize: 10, fill: "#8B95A1" }} orientation="right" domain={["auto", "auto"]} />
                <Tooltip
                  formatter={(value: number, name: string) => {
                    if (name === "current_price") {
                      return [Number(value).toLocaleString("ko-KR"), "현재가"];
                    }
                    return [Number(value).toLocaleString("ko-KR"), name];
                  }}
                />
                <Line type="monotone" dataKey="current_price" stroke="#0019FF" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  );
}
