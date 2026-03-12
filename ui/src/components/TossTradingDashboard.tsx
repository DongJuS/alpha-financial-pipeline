/**
 * ui/src/components/TossTradingDashboard.tsx
 * Toss Securities-inspired dashboard focused on simple, shopping-like UX.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useAgentStatus } from "@/hooks/useAgentStatus";
import type { PortfolioSummary } from "@/hooks/usePortfolio";
import { api, formatPct } from "@/utils/api";

type TickerItem = {
  ticker: string;
  name: string;
  market: string;
};

type QuoteItem = {
  ticker: string;
  name: string;
  current_price: number;
  change_pct: number | null;
  volume: number | null;
};

type PopularStock = QuoteItem & { market: string };

type ActivityTone = "active" | "idle" | "danger";

interface TossTradingDashboardProps {
  portfolio: PortfolioSummary | null;
  isLoading: boolean;
}

const ICON_BACKGROUNDS = [
  "from-[#0019FF] to-[#3E54FF]",
  "from-[#FF5D48] to-[#FF9A62]",
  "from-[#00A2FF] to-[#00D1FF]",
  "from-[#00B894] to-[#4FD5A9]",
  "from-[#64748B] to-[#94A3B8]",
];

const QUICK_LINKS = [
  { to: "/strategy", title: "Strategy A/B", subtitle: "토너먼트 · 컨센서스" },
  { to: "/market", title: "주식 관리", subtitle: "실시간 시세 · 차트" },
  { to: "/portfolio", title: "내 계좌", subtitle: "성과 · 거래내역" },
  { to: "/settings", title: "설정", subtitle: "리스크 · 실거래 전환" },
];

const AGENT_LABELS: Record<string, string> = {
  collector_agent: "수집기",
  predictor_1: "예측 1(Claude)",
  predictor_2: "예측 2(Claude)",
  predictor_3: "예측 3(GPT)",
  predictor_4: "예측 4(GPT)",
  predictor_5: "예측 5(Gemini)",
  portfolio_manager_agent: "운용역",
  notifier_agent: "알리미",
  orchestrator_agent: "지휘자",
};

const PRIORITY_AGENT_IDS = [
  "collector_agent",
  "predictor_1",
  "predictor_3",
  "portfolio_manager_agent",
  "notifier_agent",
  "orchestrator_agent",
];

function formatWon(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--원";
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

function iconLabel(name: string, ticker: string): string {
  const source = (name || ticker).replace(/\s+/g, "").trim();
  if (!source) return ticker.slice(0, 1).toUpperCase();
  return source.slice(0, 1).toUpperCase();
}

function activityTone(state: string): ActivityTone {
  if (["investing", "collecting", "analyzing", "orchestrating", "notifying", "active"].includes(state)) {
    return "active";
  }
  if (["offline", "error", "degraded"].includes(state)) {
    return "danger";
  }
  return "idle";
}

function toneClass(tone: ActivityTone): string {
  if (tone === "active") return "bg-[#E7F9F1] text-[#007A53]";
  if (tone === "danger") return "bg-[#FEECEC] text-[#C92A2A]";
  return "bg-white text-[#8B95A1]";
}

async function fetchPopularStocks(): Promise<PopularStock[]> {
  const { data: tickersPayload } = await api.get<{ data: TickerItem[] }>("/market/tickers", {
    params: { page: 1, per_page: 24 },
  });

  const tickerCandidates = (tickersPayload.data ?? []).slice(0, 20);
  const quotes = await Promise.all(
    tickerCandidates.map(async (item) => {
      try {
        const { data } = await api.get<QuoteItem>(`/market/quote/${item.ticker}`);
        return {
          ...data,
          market: item.market,
        } as PopularStock;
      } catch {
        return null;
      }
    })
  );

  const dedupedByTicker = new Map<string, PopularStock>();
  quotes.filter(Boolean).forEach((stock) => {
    dedupedByTicker.set((stock as PopularStock).ticker, stock as PopularStock);
  });

  return [...dedupedByTicker.values()]
    .sort((a, b) => {
      const volumeGap = (b.volume ?? 0) - (a.volume ?? 0);
      if (volumeGap !== 0) return volumeGap;
      return Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0);
    })
    .slice(0, 5);
}

export default function TossTradingDashboard({ portfolio, isLoading }: TossTradingDashboardProps) {
  const { data: popularStocks, isLoading: popularLoading } = useQuery({
    queryKey: ["dashboard", "popular-stocks"],
    queryFn: fetchPopularStocks,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const { data: agents } = useAgentStatus();

  const selectedAgents = useMemo(() => {
    if (!agents?.length) return [];
    const orderIndex = new Map(PRIORITY_AGENT_IDS.map((id, index) => [id, index]));
    return [...agents]
      .filter((item) => PRIORITY_AGENT_IDS.includes(item.agent_id))
      .sort((a, b) => (orderIndex.get(a.agent_id) ?? 999) - (orderIndex.get(b.agent_id) ?? 999));
  }, [agents]);

  const totalAsset = isLoading ? null : portfolio?.total_value ?? 0;
  const pnlValue = isLoading ? null : portfolio?.total_pnl ?? 0;
  const pnlPct = isLoading ? null : portfolio?.total_pnl_pct ?? 0;

  return (
    <div className="mx-auto w-full max-w-[1180px] px-4 pb-10 pt-5 md:px-8">
      <div className="mx-auto w-full max-w-[960px] space-y-4">
        <section className="rounded-[32px] bg-[#F2F4F6] px-6 py-7 shadow-[0_14px_32px_rgba(25,31,40,0.06)] md:px-8 md:py-8">
          <p className="text-[13px] font-semibold tracking-[-0.01em] text-[#8B95A1]">내 자산 현황</p>
          <h1 className="mt-2 text-[36px] font-extrabold tracking-[-0.03em] text-[#191F28] md:text-[44px]">
            {formatWon(totalAsset)}
          </h1>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                (pnlValue ?? 0) >= 0 ? "bg-[#EAF3FF] text-[#0019FF]" : "bg-[#FEECEC] text-[#C92A2A]"
              }`}
            >
              {pnlValue == null ? "손익 집계 중" : `총 손익 ${formatWon(pnlValue)}`}
            </span>
            <span className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#8B95A1]">
              {pnlPct == null ? "--" : formatPct(pnlPct)}
            </span>
            <span className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#8B95A1]">
              {portfolio?.is_paper ? "페이퍼 트레이딩" : "실거래"}
            </span>
          </div>
        </section>

        <section className="rounded-[32px] bg-[#F2F4F6] p-5 shadow-[0_10px_28px_rgba(25,31,40,0.05)] md:p-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[18px] font-bold tracking-[-0.02em] text-[#191F28]">실시간 인기 주식</h2>
            <Link to="/market" className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#8B95A1] hover:scale-105">
              전체 보기
            </Link>
          </div>

          <div className="flex snap-x gap-3 overflow-x-auto pb-1">
            {popularLoading
              ? [...Array(5)].map((_, index) => (
                  <div key={index} className="min-w-[152px] animate-pulse rounded-[26px] bg-white p-4">
                    <div className="h-4 w-12 rounded-full bg-[#F2F4F6]" />
                    <div className="mt-3 h-16 w-16 rounded-[22px] bg-[#F2F4F6]" />
                    <div className="mt-3 h-4 w-20 rounded-full bg-[#F2F4F6]" />
                  </div>
                ))
              : (popularStocks ?? []).map((stock, index) => {
                  const isPositive = (stock.change_pct ?? 0) >= 0;
                  return (
                    <article
                      key={stock.ticker}
                      className="group min-w-[152px] snap-start rounded-[26px] bg-white p-4 transition-transform duration-200 hover:scale-105"
                    >
                      <div className="flex items-center justify-between">
                        <span className="rounded-full bg-[#F2F4F6] px-2 py-1 text-[11px] font-semibold text-[#8B95A1]">
                          {index + 1}위
                        </span>
                        <span className={`text-xs font-bold ${isPositive ? "text-[#0019FF]" : "text-[#C92A2A]"}`}>
                          {stock.change_pct != null ? formatPct(stock.change_pct) : "--"}
                        </span>
                      </div>

                      <div
                        className={`mt-3 flex h-16 w-16 items-center justify-center rounded-[22px] bg-gradient-to-br ${
                          ICON_BACKGROUNDS[index % ICON_BACKGROUNDS.length]
                        } text-[30px] font-black text-white shadow-[0_10px_22px_rgba(25,31,40,0.2)]`}
                      >
                        {iconLabel(stock.name, stock.ticker)}
                      </div>

                      <p className="mt-3 text-[18px] font-extrabold tracking-[-0.02em] text-[#191F28]">{stock.ticker}</p>
                      <p className="mt-0.5 truncate text-[12px] font-medium text-[#8B95A1]">{stock.name}</p>
                      <p className="mt-2 text-sm font-bold text-[#191F28]">{formatWon(stock.current_price)}</p>
                    </article>
                  );
                })}
          </div>
        </section>

        <section className="grid grid-cols-2 gap-3">
          {QUICK_LINKS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="rounded-[24px] bg-[#F2F4F6] px-4 py-4 shadow-[0_8px_18px_rgba(25,31,40,0.05)] transition-transform duration-200 hover:scale-105"
            >
              <p className="text-[15px] font-bold tracking-[-0.02em] text-[#191F28]">{item.title}</p>
              <p className="mt-1 text-[12px] font-medium text-[#8B95A1]">{item.subtitle}</p>
            </Link>
          ))}
        </section>

        <section className="rounded-[32px] bg-[#F2F4F6] p-5 shadow-[0_10px_28px_rgba(25,31,40,0.05)] md:p-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[18px] font-bold tracking-[-0.02em] text-[#191F28]">에이전트 활동</h2>
            <span className="text-xs font-semibold text-[#8B95A1]">실시간 상태</span>
          </div>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
            {selectedAgents.map((agent) => (
              <div key={agent.agent_id} className="rounded-[20px] bg-white px-3 py-3">
                <p className="truncate text-[12px] font-bold text-[#191F28]">{AGENT_LABELS[agent.agent_id] ?? agent.agent_id}</p>
                <span className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${toneClass(activityTone(agent.activity_state))}`}>
                  {agent.activity_label}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
