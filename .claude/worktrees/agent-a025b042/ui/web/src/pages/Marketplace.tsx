/**
 * ui/web/src/pages/Marketplace.tsx
 * Marketplace page — Toss Invest dark theme with tabs for sectors, rankings, macro, themes, ETF, watchlist.
 */

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Treemap,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { api } from "@/utils/api";

// ── Type definitions ──────────────────────────────────────────────────────

type HeatmapItem = {
  sector: string;
  stock_count: number;
  avg_change_pct: number;
  total_market_cap: number;
  total_volume: number;
};

type RankingItem = {
  rank: number;
  ticker: string;
  name: string;
  value?: number;
  change_pct?: number;
  extra?: Record<string, unknown>;
};

type MacroItem = {
  category: string;
  symbol: string;
  name: string;
  value: number;
  change_pct?: number;
  previous_close?: number;
  snapshot_date: string;
  source: string;
};

type StockItem = {
  ticker: string;
  name: string;
  market: string;
  sector?: string;
  market_cap?: number;
  is_etf?: boolean;
  is_etn?: boolean;
};

type ThemeItem = {
  theme_slug: string;
  theme_name: string;
  stock_count: number;
  leader_count: number;
};

type WatchlistItem = {
  ticker: string;
  name: string;
  group_name: string;
  market?: string;
  sector?: string;
  market_cap?: number;
  added_at: string;
};

// ── Helper functions ──────────────────────────────────────────────────────

function changeColor(pct: number | undefined): string {
  if (!pct) return "var(--text-secondary)";
  // Korean stock market: red=up, blue=down
  return pct > 0 ? "var(--red-500)" : "var(--blue-500)";
}

function heatmapColor(pct: number): string {
  if (pct > 0) {
    const intensity = Math.min(pct / 10, 1);
    return `rgba(255, 71, 87, ${0.2 + intensity * 0.6})`;
  } else {
    const intensity = Math.min(Math.abs(pct) / 10, 1);
    return `rgba(66, 135, 245, ${0.2 + intensity * 0.6})`;
  }
}

function formatLargeNum(value: number | undefined): string {
  if (!value) return "0";
  if (value >= 1e12) return `${(value / 1e12).toFixed(1)}조`;
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}억`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}만`;
  return String(value);
}

function formatPercent(pct: number | undefined): string {
  if (!pct) return "0%";
  return `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

// ── API Hooks ────────────────────────────────────────────────────────────

function useSectorHeatmap() {
  return useQuery({
    queryKey: ["marketplace", "sectors", "heatmap"],
    queryFn: async () => {
      const { data } = await api.get<HeatmapItem[]>("/marketplace/sectors/heatmap");
      return data;
    },
    refetchInterval: 60_000,
  });
}

function useRankings(type: string) {
  return useQuery({
    queryKey: ["marketplace", "rankings", type],
    queryFn: async () => {
      const { data } = await api.get<{
        ranking_type: string;
        data: RankingItem[];
      }>(`/marketplace/rankings/${type}`);
      return data.data;
    },
    refetchInterval: 120_000,
    enabled: !!type,
  });
}

function useMacro() {
  return useQuery({
    queryKey: ["marketplace", "macro"],
    queryFn: async () => {
      const { data } = await api.get<Record<string, MacroItem[]>>("/marketplace/macro");
      // Flatten to single list for display
      const items: MacroItem[] = [];
      Object.values(data).forEach((category) => {
        items.push(...category);
      });
      return items;
    },
    refetchInterval: 300_000,
  });
}

function useSearch(q: string) {
  return useQuery({
    queryKey: ["marketplace", "search", q],
    queryFn: async () => {
      const { data } = await api.get<StockItem[]>("/marketplace/search", {
        params: { q },
      });
      return data;
    },
    enabled: q.length > 0,
  });
}

function useThemes() {
  return useQuery({
    queryKey: ["marketplace", "themes"],
    queryFn: async () => {
      const { data } = await api.get<ThemeItem[]>("/marketplace/themes");
      return data;
    },
    refetchInterval: 600_000,
  });
}

function useThemeStocks(slug: string) {
  return useQuery({
    queryKey: ["marketplace", "themes", slug],
    queryFn: async () => {
      const { data } = await api.get<StockItem[]>(`/marketplace/themes/${slug}/stocks`);
      return data;
    },
    enabled: !!slug,
  });
}

function useETF(page: number = 1, search: string = "") {
  return useQuery({
    queryKey: ["marketplace", "etf", page, search],
    queryFn: async () => {
      const { data } = await api.get<{
        data: StockItem[];
        meta: { page: number; per_page: number; total: number };
      }>("/marketplace/etf", {
        params: { page, per_page: 50, search },
      });
      return data;
    },
    refetchInterval: 600_000,
  });
}

function useWatchlist() {
  return useQuery({
    queryKey: ["marketplace", "watchlist"],
    queryFn: async () => {
      const { data } = await api.get<WatchlistItem[]>("/marketplace/watchlist");
      return data;
    },
    refetchInterval: 120_000,
  });
}

// ── Components ───────────────────────────────────────────────────────────

function OverviewTab() {
  const heatmap = useSectorHeatmap();
  const gainers = useRankings("gainer");
  const losers = useRankings("loser");

  return (
    <div className="space-y-6">
      {/* Sector Heatmap Treemap */}
      <div className="card">
        <h3 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
          섹터 히트맵
        </h3>
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          실시간 섹터별 등락률 및 시가총액 분포
        </p>

        {heatmap.isLoading && <div className="mt-4 h-64 skeleton" />}
        {heatmap.data && (
          <div className="mt-4" style={{ width: "100%", height: 400 }}>
            <ResponsiveContainer width="100%" height="100%">
              <Treemap
                data={heatmap.data}
                dataKey="total_market_cap"
                stroke="var(--border-subtle)"
                fill="var(--bg-elevated)"
              >
                {heatmap.data.map((item, idx) => (
                  <Cell
                    key={`cell-${idx}`}
                    fill={heatmapColor(item.avg_change_pct)}
                  />
                ))}
              </Treemap>
            </ResponsiveContainer>
          </div>
        )}
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {heatmap.data?.slice(0, 4).map((sector) => (
            <div
              key={sector.sector}
              className="rounded-lg p-4"
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    {sector.sector}
                  </p>
                  <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {sector.stock_count}개 종목
                  </p>
                </div>
                <div className="text-right">
                  <p
                    className="text-lg font-bold"
                    style={{ color: changeColor(sector.avg_change_pct) }}
                  >
                    {formatPercent(sector.avg_change_pct)}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Top Gainers & Losers */}
      <div className="grid gap-6 md:grid-cols-2">
        <div className="card">
          <h3 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            상승률 상위
          </h3>
          {gainers.isLoading && <div className="mt-3 space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-10 skeleton" />
            ))}
          </div>}
          {gainers.data && (
            <div className="mt-3 space-y-2">
              {gainers.data.slice(0, 5).map((item) => (
                <div
                  key={item.ticker}
                  className="flex items-center justify-between rounded-lg p-3"
                  style={{ background: "var(--bg-elevated)" }}
                >
                  <div>
                    <p className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>
                      {item.ticker}
                    </p>
                    <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      {item.name}
                    </p>
                  </div>
                  <p className="font-semibold text-sm" style={{ color: changeColor(item.change_pct) }}>
                    {formatPercent(item.change_pct)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            하락률 상위
          </h3>
          {losers.isLoading && <div className="mt-3 space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-10 skeleton" />
            ))}
          </div>}
          {losers.data && (
            <div className="mt-3 space-y-2">
              {losers.data.slice(0, 5).map((item) => (
                <div
                  key={item.ticker}
                  className="flex items-center justify-between rounded-lg p-3"
                  style={{ background: "var(--bg-elevated)" }}
                >
                  <div>
                    <p className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>
                      {item.ticker}
                    </p>
                    <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      {item.name}
                    </p>
                  </div>
                  <p className="font-semibold text-sm" style={{ color: changeColor(item.change_pct) }}>
                    {formatPercent(item.change_pct)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RankingsTab() {
  const [rankingType, setRankingType] = useState<string>("market_cap");
  const rankings = useRankings(rankingType);

  const rankingLabels: Record<string, string> = {
    market_cap: "시가총액",
    volume: "거래량",
    turnover: "거래대금",
    gainer: "상승률",
    loser: "하락률",
    new_high: "신고가",
    new_low: "신저가",
  };

  return (
    <div className="card">
      <div className="mb-6 flex flex-wrap gap-2">
        {Object.entries(rankingLabels).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setRankingType(key)}
            className="px-3 py-2 rounded-lg text-sm font-medium transition-all"
            style={{
              background: rankingType === key ? "var(--brand-500)" : "var(--bg-elevated)",
              color: rankingType === key ? "white" : "var(--text-primary)",
              border: `1px solid ${rankingType === key ? "var(--brand-500)" : "var(--border-subtle)"}`,
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {rankings.isLoading && (
        <div className="space-y-2">
          {[...Array(10)].map((_, i) => (
            <div key={i} className="h-12 skeleton" />
          ))}
        </div>
      )}

      {rankings.data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  순위
                </th>
                <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  종목
                </th>
                <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  값
                </th>
                <th className="text-right py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  등락률
                </th>
              </tr>
            </thead>
            <tbody>
              {rankings.data.slice(0, 50).map((item) => (
                <tr
                  key={`${item.ticker}-${item.rank}`}
                  style={{ borderBottom: "1px solid var(--border-subtle)" }}
                >
                  <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                    {item.rank}
                  </td>
                  <td className="py-3 px-4">
                    <div style={{ color: "var(--text-primary)" }} className="font-medium">
                      {item.ticker}
                    </div>
                    <div style={{ color: "var(--text-secondary)" }} className="text-xs">
                      {item.name}
                    </div>
                  </td>
                  <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                    {item.value ? formatLargeNum(item.value) : "—"}
                  </td>
                  <td className="py-3 px-4 text-right font-medium" style={{ color: changeColor(item.change_pct) }}>
                    {formatPercent(item.change_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function MacroTab() {
  const macro = useMacro();

  const categories: Record<string, string[]> = {
    "해외지수": ["index"],
    "환율": ["currency"],
    "원자재": ["commodity"],
    "금리": ["rate"],
  };

  return (
    <div className="space-y-6">
      {macro.isLoading && (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-40 skeleton rounded-lg" />
          ))}
        </div>
      )}

      {macro.data && (
        <>
          {Object.entries(categories).map(([categoryLabel, categoryKeys]) => {
            const items = macro.data.filter((item) =>
              categoryKeys.includes(item.category)
            );
            if (items.length === 0) return null;

            return (
              <div key={categoryLabel} className="card">
                <h3 className="text-lg font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
                  {categoryLabel}
                </h3>
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                  {items.map((item) => (
                    <div
                      key={item.symbol}
                      className="rounded-lg p-4"
                      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}
                    >
                      <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                        {item.name}
                      </p>
                      <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                        {item.symbol}
                      </p>
                      <div className="mt-3 flex items-center justify-between">
                        <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                          {item.value.toFixed(2)}
                        </p>
                        <p
                          className="font-semibold text-sm"
                          style={{ color: changeColor(item.change_pct) }}
                        >
                          {formatPercent(item.change_pct)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

function SearchTab() {
  const [query, setQuery] = useState<string>("");
  const search = useSearch(query);

  return (
    <div className="card">
      <div className="mb-6">
        <input
          type="text"
          placeholder="종목명 또는 티커 검색..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full px-4 py-3 rounded-lg"
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border-subtle)",
            color: "var(--text-primary)",
          }}
        />
      </div>

      {search.isLoading && (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 skeleton" />
          ))}
        </div>
      )}

      {search.data && search.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  종목
                </th>
                <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  시장
                </th>
                <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  섹터
                </th>
                <th className="text-right py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                  시가총액
                </th>
              </tr>
            </thead>
            <tbody>
              {search.data.map((item) => (
                <tr key={item.ticker} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <td className="py-3 px-4">
                    <div style={{ color: "var(--text-primary)" }} className="font-medium">
                      {item.ticker}
                    </div>
                    <div style={{ color: "var(--text-secondary)" }} className="text-xs">
                      {item.name}
                    </div>
                  </td>
                  <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                    {item.market}
                  </td>
                  <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                    {item.sector || "—"}
                  </td>
                  <td className="py-3 px-4 text-right" style={{ color: "var(--text-secondary)" }}>
                    {item.market_cap ? formatLargeNum(item.market_cap) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {search.data && search.data.length === 0 && query.length > 0 && (
        <p style={{ color: "var(--text-secondary)" }} className="text-center py-8">
          검색 결과가 없습니다.
        </p>
      )}
    </div>
  );
}

function ThemesTab() {
  const [selectedTheme, setSelectedTheme] = useState<string>("");
  const themes = useThemes();
  const themeStocks = useThemeStocks(selectedTheme);

  return (
    <div className="space-y-6">
      {selectedTheme && (
        <button
          onClick={() => setSelectedTheme("")}
          className="text-sm font-medium"
          style={{ color: "var(--brand-500)" }}
        >
          ← 테마 목록으로 돌아가기
        </button>
      )}

      {!selectedTheme && (
        <>
          <p style={{ color: "var(--text-secondary)" }} className="text-sm">
            테마를 클릭하여 관련 종목을 확인하세요.
          </p>
          {themes.isLoading && (
            <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-32 skeleton rounded-lg" />
              ))}
            </div>
          )}
          {themes.data && (
            <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4">
              {themes.data.map((theme) => (
                <button
                  key={theme.theme_slug}
                  onClick={() => setSelectedTheme(theme.theme_slug)}
                  className="rounded-lg p-4 text-left transition-all"
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  <p className="font-semibold" style={{ color: "var(--text-primary)" }}>
                    {theme.theme_name}
                  </p>
                  <p className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>
                    {theme.stock_count}개 종목
                  </p>
                  {theme.leader_count > 0 && (
                    <p className="text-xs mt-1" style={{ color: "var(--brand-500)" }}>
                      리더: {theme.leader_count}
                    </p>
                  )}
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {selectedTheme && (
        <div className="card">
          <h3 className="text-lg font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            {themes.data?.find((t) => t.theme_slug === selectedTheme)?.theme_name}
          </h3>

          {themeStocks.isLoading && (
            <div className="space-y-2">
              {[...Array(10)].map((_, i) => (
                <div key={i} className="h-12 skeleton" />
              ))}
            </div>
          )}

          {themeStocks.data && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                    <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                      종목
                    </th>
                    <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                      시장
                    </th>
                    <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                      섹터
                    </th>
                    <th className="text-right py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                      시가총액
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {themeStocks.data.map((item) => (
                    <tr key={item.ticker} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      <td className="py-3 px-4">
                        <div style={{ color: "var(--text-primary)" }} className="font-medium">
                          {item.ticker}
                        </div>
                        <div style={{ color: "var(--text-secondary)" }} className="text-xs">
                          {item.name}
                        </div>
                      </td>
                      <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                        {item.market}
                      </td>
                      <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                        {item.sector || "—"}
                      </td>
                      <td className="py-3 px-4 text-right" style={{ color: "var(--text-secondary)" }}>
                        {item.market_cap ? formatLargeNum(item.market_cap) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ETFTab() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const etf = useETF(page, search);

  return (
    <div className="card">
      <div className="mb-6">
        <input
          type="text"
          placeholder="ETF/ETN 검색..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="w-full px-4 py-3 rounded-lg"
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border-subtle)",
            color: "var(--text-primary)",
          }}
        />
      </div>

      {etf.isLoading && (
        <div className="space-y-2">
          {[...Array(10)].map((_, i) => (
            <div key={i} className="h-12 skeleton" />
          ))}
        </div>
      )}

      {etf.data && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    종목
                  </th>
                  <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    시장
                  </th>
                  <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    섹터
                  </th>
                  <th className="text-right py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    시가총액
                  </th>
                </tr>
              </thead>
              <tbody>
                {etf.data.data.map((item) => (
                  <tr key={item.ticker} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                    <td className="py-3 px-4">
                      <div style={{ color: "var(--text-primary)" }} className="font-medium">
                        {item.ticker}
                      </div>
                      <div style={{ color: "var(--text-secondary)" }} className="text-xs">
                        {item.name}
                      </div>
                    </td>
                    <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                      {item.market}
                    </td>
                    <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                      {item.sector || "—"}
                    </td>
                    <td className="py-3 px-4 text-right" style={{ color: "var(--text-secondary)" }}>
                      {item.market_cap ? formatLargeNum(item.market_cap) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-6 flex items-center justify-between">
            <p style={{ color: "var(--text-secondary)" }} className="text-sm">
              전체 {etf.data.meta.total}개 중 {(page - 1) * etf.data.meta.per_page + 1}~
              {Math.min(page * etf.data.meta.per_page, etf.data.meta.total)}개
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page === 1}
                className="px-3 py-2 rounded-lg text-sm font-medium"
                style={{
                  background: page === 1 ? "var(--bg-elevated)" : "var(--brand-500)",
                  color: page === 1 ? "var(--text-secondary)" : "white",
                  opacity: page === 1 ? 0.5 : 1,
                }}
              >
                이전
              </button>
              <button
                onClick={() => setPage(page + 1)}
                disabled={page * etf.data.meta.per_page >= etf.data.meta.total}
                className="px-3 py-2 rounded-lg text-sm font-medium"
                style={{
                  background:
                    page * etf.data.meta.per_page >= etf.data.meta.total
                      ? "var(--bg-elevated)"
                      : "var(--brand-500)",
                  color:
                    page * etf.data.meta.per_page >= etf.data.meta.total
                      ? "var(--text-secondary)"
                      : "white",
                  opacity:
                    page * etf.data.meta.per_page >= etf.data.meta.total
                      ? 0.5
                      : 1,
                }}
              >
                다음
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function WatchlistTab() {
  const watchlist = useWatchlist();
  const [searchQuery, setSearchQuery] = useState("");
  const search = useSearch(searchQuery);

  const handleAddToWatchlist = async (ticker: string, name: string) => {
    try {
      await api.post("/marketplace/watchlist", {
        ticker,
        name,
        group_name: "default",
      });
      // Refetch watchlist
      await watchlist.refetch();
    } catch (error) {
      console.error("Failed to add to watchlist", error);
    }
  };

  const handleRemoveFromWatchlist = async (ticker: string) => {
    try {
      await api.delete(`/marketplace/watchlist/${ticker}`);
      // Refetch watchlist
      await watchlist.refetch();
    } catch (error) {
      console.error("Failed to remove from watchlist", error);
    }
  };

  return (
    <div className="space-y-6">
      {/* Current Watchlist */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          내 관심 종목
        </h3>

        {watchlist.isLoading && (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 skeleton" />
            ))}
          </div>
        )}

        {watchlist.data && watchlist.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    종목
                  </th>
                  <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    시장
                  </th>
                  <th className="text-left py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    섹터
                  </th>
                  <th className="text-right py-3 px-4 font-semibold" style={{ color: "var(--text-secondary)" }}>
                    시가총액
                  </th>
                  <th className="text-center py-3 px-4" />
                </tr>
              </thead>
              <tbody>
                {watchlist.data.map((item) => (
                  <tr key={item.ticker} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                    <td className="py-3 px-4">
                      <div style={{ color: "var(--text-primary)" }} className="font-medium">
                        {item.ticker}
                      </div>
                      <div style={{ color: "var(--text-secondary)" }} className="text-xs">
                        {item.name}
                      </div>
                    </td>
                    <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                      {item.market || "—"}
                    </td>
                    <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                      {item.sector || "—"}
                    </td>
                    <td className="py-3 px-4 text-right" style={{ color: "var(--text-secondary)" }}>
                      {item.market_cap ? formatLargeNum(item.market_cap) : "—"}
                    </td>
                    <td className="py-3 px-4 text-center">
                      <button
                        onClick={() => handleRemoveFromWatchlist(item.ticker)}
                        className="text-xs font-medium"
                        style={{ color: "var(--red-500)" }}
                      >
                        제거
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {watchlist.data && watchlist.data.length === 0 && (
          <p style={{ color: "var(--text-secondary)" }} className="text-center py-8">
            아직 관심 종목이 없습니다.
          </p>
        )}
      </div>

      {/* Add Watchlist */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          관심 종목 추가
        </h3>
        <div className="mb-6">
          <input
            type="text"
            placeholder="종목명 또는 티커 검색..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-4 py-3 rounded-lg"
            style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-subtle)",
              color: "var(--text-primary)",
            }}
          />
        </div>

        {search.isLoading && (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 skeleton" />
            ))}
          </div>
        )}

        {search.data && search.data.length > 0 && (
          <div className="space-y-2">
            {search.data.map((item) => (
              <div
                key={item.ticker}
                className="flex items-center justify-between rounded-lg p-3"
                style={{ background: "var(--bg-elevated)" }}
              >
                <div>
                  <p className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>
                    {item.ticker}
                  </p>
                  <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {item.name}
                  </p>
                </div>
                <button
                  onClick={() => handleAddToWatchlist(item.ticker, item.name)}
                  disabled={
                    watchlist.data?.some((w) => w.ticker === item.ticker) || false
                  }
                  className="px-3 py-1 rounded-lg text-xs font-medium"
                  style={{
                    background: watchlist.data?.some((w) => w.ticker === item.ticker)
                      ? "var(--bg-elevated)"
                      : "var(--brand-500)",
                    color: watchlist.data?.some((w) => w.ticker === item.ticker)
                      ? "var(--text-secondary)"
                      : "white",
                    opacity: watchlist.data?.some((w) => w.ticker === item.ticker)
                      ? 0.5
                      : 1,
                  }}
                >
                  {watchlist.data?.some((w) => w.ticker === item.ticker)
                    ? "추가됨"
                    : "추가"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────

export default function Marketplace() {
  const [activeTab, setActiveTab] = useState<
    "overview" | "rankings" | "macro" | "search" | "themes" | "etf" | "watchlist"
  >("overview");

  const tabs = [
    { id: "overview", label: "오버뷰" },
    { id: "rankings", label: "랭킹" },
    { id: "macro", label: "매크로" },
    { id: "search", label: "검색" },
    { id: "themes", label: "테마" },
    { id: "etf", label: "ETF" },
    { id: "watchlist", label: "관심종목" },
  ];

  return (
    <div className="page-shell">
      <section className="card">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
            마켓플레이스
          </h1>
          <p style={{ color: "var(--text-secondary)" }}>
            섹터·랭킹·매크로 지표·테마를 한눈에 확인하세요.
          </p>
        </div>

        <div className="mt-6 flex flex-wrap gap-2 border-b" style={{ borderColor: "var(--border-subtle)" }}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className="px-4 py-3 font-medium text-sm transition-all"
              style={{
                color:
                  activeTab === tab.id
                    ? "var(--brand-500)"
                    : "var(--text-secondary)",
                borderBottom:
                  activeTab === tab.id
                    ? "2px solid var(--brand-500)"
                    : "transparent",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {activeTab === "overview" && <OverviewTab />}
          {activeTab === "rankings" && <RankingsTab />}
          {activeTab === "macro" && <MacroTab />}
          {activeTab === "search" && <SearchTab />}
          {activeTab === "themes" && <ThemesTab />}
          {activeTab === "etf" && <ETFTab />}
          {activeTab === "watchlist" && <WatchlistTab />}
        </div>
      </section>
    </div>
  );
}
