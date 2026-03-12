/**
 * ui/src/pages/Market.tsx — 시장 데이터 / 지수 + 종목 OHLCV 차트
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  Line,
  LineChart,
  ComposedChart,
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
  if (Number.isNaN(d.getTime())) {
    return ts.slice(11, 19);
  }
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
          oc_range: Math.abs(item.close - item.open),
          is_up: item.close >= item.open,
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
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900">시장 데이터</h1>

      <div className="grid grid-cols-2 gap-4">
        {["kospi", "kosdaq"].map((key) => {
          const item = index?.[key as keyof IndexPayload];
          return (
            <div key={key} className="card">
              <p className="text-xs text-gray-500 font-medium">{key.toUpperCase()}</p>
              {indexLoading ? (
                <div className="h-8 bg-gray-100 rounded mt-2 animate-pulse" />
              ) : (
                <>
                  <p className="number-lg mt-1">{item?.value?.toLocaleString("ko-KR") ?? "—"}</p>
                  <p className={`text-sm font-medium mt-0.5 ${(item?.change_pct ?? 0) >= 0 ? "text-positive" : "text-negative"}`}>
                    {item?.change_pct != null ? `${item.change_pct >= 0 ? "+" : ""}${item.change_pct.toFixed(2)}%` : "—"}
                  </p>
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className="card space-y-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold text-gray-800">종목 OHLCV 차트</h2>
            <p className="text-xs text-gray-500 mt-1">
              {ohlcv?.name ? `${ohlcv.name} (${ohlcv.ticker})` : "종목 선택"} · {chartSource === "db" ? "내부 수집 DB" : "오픈소스 API(FDR)"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              className="border border-surface-border rounded-xl px-3 py-2 text-sm"
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
            <select
              className="border border-surface-border rounded-xl px-3 py-2 text-sm"
              value={chartSource}
              onChange={(e) => setChartSource(e.target.value as ChartSource)}
            >
              <option value="db">내부 DB</option>
              <option value="opensource">오픈소스 API</option>
            </select>
          </div>
        </div>

        {ohlcvLoading || chartData.length === 0 ? (
          <div className="h-72 bg-gray-50 rounded-xl animate-pulse" />
        ) : (
          <div className="space-y-4">
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={16} />
                  <YAxis yAxisId="price" orientation="right" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                  <Tooltip
                    formatter={(value: number, name: string) => {
                      if (["open", "high", "low", "close"].includes(name)) {
                        return [Number(value).toLocaleString("ko-KR"), name.toUpperCase()];
                      }
                      return [Number(value).toLocaleString("ko-KR"), name];
                    }}
                  />
                  <Bar yAxisId="price" dataKey="high" fill="#E5E7EB" radius={[2, 2, 0, 0]} barSize={2} />
                  <Bar yAxisId="price" dataKey="low" fill="#E5E7EB" radius={[0, 0, 2, 2]} barSize={2} />
                  <Bar yAxisId="price" dataKey="oc_mid" fill="#93C5FD" barSize={6} />
                  <Area yAxisId="price" dataKey="close" stroke="#2563EB" fill="#DBEAFE" fillOpacity={0.35} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            <div className="h-36">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={16} />
                  <YAxis tick={{ fontSize: 10 }} orientation="right" />
                  <Tooltip formatter={(value: number) => Number(value).toLocaleString("ko-KR")} />
                  <Area dataKey="volume" stroke="#10B981" fill="#A7F3D0" fillOpacity={0.5} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>

      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-800">실시간 가격 추이</h2>
          <p className="text-xs text-gray-500">5초 폴링 · Redis 실시간 캐시</p>
        </div>
        {realtimeLoading || realtimeData.length === 0 ? (
          <div className="h-56 bg-gray-50 rounded-xl animate-pulse" />
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={realtimeData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={16} />
                <YAxis tick={{ fontSize: 10 }} orientation="right" domain={["auto", "auto"]} />
                <Tooltip
                  formatter={(value: number, name: string) => {
                    if (name === "current_price") {
                      return [Number(value).toLocaleString("ko-KR"), "현재가"];
                    }
                    return [Number(value).toLocaleString("ko-KR"), name];
                  }}
                />
                <Line type="monotone" dataKey="current_price" stroke="#0EA5E9" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
