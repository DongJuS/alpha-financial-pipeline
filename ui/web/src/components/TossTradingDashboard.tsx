import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useAgentStatus } from "@/hooks/useAgentStatus";
import {
  usePerformance,
  usePerformanceSeries,
  usePortfolioConfig,
  type MarketSessionStatus,
  type PortfolioSummary,
  type TradingAccountOverview,
  type TradingScope,
} from "@/hooks/usePortfolio";
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
  accountOverview: TradingAccountOverview | null;
  isLoading: boolean;
}

const ICON_BACKGROUNDS = [
  "linear-gradient(135deg, #1f63f7 0%, #57a8ff 100%)",
  "linear-gradient(135deg, #f04452 0%, #ff7c85 100%)",
  "linear-gradient(135deg, #0cb58f 0%, #4addb5 100%)",
  "linear-gradient(135deg, #c27b0a 0%, #ffb95a 100%)",
  "linear-gradient(135deg, #6d5efc 0%, #a78bfa 100%)",
  "linear-gradient(135deg, #0f172a 0%, #334155 100%)",
];

const QUICK_LINKS = [
  {
    to: "/strategy",
    title: "전략 센터",
    subtitle: "토너먼트와 컨센서스를 교차 검증합니다.",
    icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  },
  {
    to: "/market",
    title: "마켓 센터",
    subtitle: "실시간 수집 데이터와 오픈소스 차트를 비교합니다.",
    icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",
  },
  {
    to: "/paper-trading",
    title: "모의 투자",
    subtitle: "KIS 페이퍼 계좌의 수익률과 체결 흐름을 봅니다.",
    icon: "M4 6h16M4 12h16M4 18h10",
  },
  {
    to: "/portfolio",
    title: "포트폴리오",
    subtitle: "성과, 포지션, 거래 이력을 한 번에 점검합니다.",
    icon: "M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z",
  },
  {
    to: "/settings",
    title: "운영 설정",
    subtitle: "전략 비율과 리스크 정책을 안전하게 조정합니다.",
    icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z",
  },
];

const AGENT_LABELS: Record<string, string> = {
  collector_agent: "데이터 수집기",
  predictor_1: "예측 1 · Claude",
  predictor_2: "예측 2 · Claude",
  predictor_3: "예측 3 · Gemini",
  predictor_4: "예측 4 · Gemini",
  predictor_5: "예측 5 · Claude",
  portfolio_manager_agent: "포트폴리오 매니저",
  notifier_agent: "알림 에이전트",
  orchestrator_agent: "오케스트레이터",
};

/** 홈 대시보드에는 인프라 에이전트 4개만 표시.
 *  예측 에이전트(predictor_1-5)는 모델 관리 페이지에서 관리합니다. */
const PRIORITY_AGENT_IDS = [
  "collector_agent",
  "portfolio_manager_agent",
  "notifier_agent",
  "orchestrator_agent",
];

const HOLD_RULES = [
  "신뢰도 0.6 미만",
  "시장 데이터 30분 이상 지연",
  "Strategy B 합의 실패",
  "Strategy A/B 시그널 충돌",
  "서킷브레이커 발동",
];

const TRANSPARENCY_PROMISES = [
  "모든 매매 결정은 이유와 함께 로깅됩니다.",
  "Debate transcript는 90일간 보관됩니다.",
  "데이터가 없으면 예측하지 않고 부재를 그대로 보여줍니다.",
  "오류와 합의 실패도 사용자에게 숨기지 않습니다.",
];

function formatWon(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--원";
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

function formatCompactNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("ko-KR", {
    notation: "compact",
    compactDisplay: "short",
    maximumFractionDigits: 1,
  }).format(value);
}

function compactDate(value: string): string {
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

function toneDot(tone: ActivityTone): string {
  if (tone === "active") return "dot-healthy";
  if (tone === "danger") return "dot-dead";
  return "dot-degraded";
}

function toneColor(tone: ActivityTone): string {
  if (tone === "active") return "var(--green)";
  if (tone === "danger") return "var(--profit)";
  return "rgba(255,255,255,0.78)";
}

function marketStatusChip(status?: MarketSessionStatus): string {
  switch (status) {
    case "open":
      return "정규장 주문 가능";
    case "pre_open":
      return "장 시작 전 · 분석만";
    case "after_hours":
      return "장 마감 후 · 분석만";
    case "holiday":
      return "휴장일 · 분석만";
    case "weekend":
      return "주말 · 분석만";
    default:
      return "시장 종료 · 분석만";
  }
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
        return { ...data, market: item.market } as PopularStock;
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
    .slice(0, 6);
}

function QuickLinkCard({
  to,
  title,
  subtitle,
  icon,
}: {
  to: string;
  title: string;
  subtitle: string;
  icon: string;
}) {
  return (
    <Link
      to={to}
      className="group rounded-[24px] border border-white/70 bg-white/70 p-4 transition-all hover:-translate-y-0.5 hover:border-[var(--brand-500)]/20 hover:bg-white"
    >
      <div className="flex items-start gap-3">
        <div
          className="flex h-11 w-11 items-center justify-center rounded-2xl"
          style={{ background: "var(--brand-bg)" }}
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="var(--brand-500)"
            strokeWidth="1.8"
            aria-hidden="true"
          >
            <path d={icon} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="space-y-1">
          <p className="text-sm font-bold tracking-[-0.02em]" style={{ color: "var(--text-primary)" }}>
            {title}
          </p>
          <p className="text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
            {subtitle}
          </p>
        </div>
      </div>
    </Link>
  );
}

function ReturnCompareCard({
  scope,
  title,
  subtitle,
  actionTo,
  actionLabel,
}: {
  scope: TradingScope;
  title: string;
  subtitle: string;
  actionTo: string;
  actionLabel: string;
}) {
  const { data: perf, isLoading: perfLoading } = usePerformance("monthly", scope);
  const { data: series, isLoading: seriesLoading } = usePerformanceSeries("monthly", scope);

  const chartData = useMemo(
    () =>
      (series?.points ?? []).map((point) => ({
        ...point,
        label: compactDate(point.date),
      })),
    [series]
  );

  const hasData = chartData.length > 0;
  const isPositive = (perf?.return_pct ?? 0) >= 0;

  return (
    <article className="rounded-[28px] border border-white/75 bg-white/78 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-bold tracking-[-0.02em]" style={{ color: "var(--text-primary)" }}>
            {title}
          </p>
          <p className="mt-1 text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
            {subtitle}
          </p>
        </div>
        <Link to={actionTo} className="btn-secondary">
          {actionLabel}
        </Link>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${isPositive ? "badge-buy" : "badge-sell"}`}>
          {perfLoading ? "집계 중" : `월간 ${formatPct(perf?.return_pct ?? 0)}`}
        </span>
        <span className="chip">거래 {(perf?.total_trades ?? 0).toLocaleString()}건</span>
        <span className="chip">MDD {perfLoading ? "—" : formatPct(perf?.max_drawdown_pct ?? 0)}</span>
      </div>

      <div className="mt-5">
        {seriesLoading ? (
          <div className="h-64 skeleton" />
        ) : hasData ? (
          <div className="chart-container h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--chart-axis)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--chart-axis)" }} unit="%" />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value: number) => `${Number(value).toFixed(2)}%`} />
                <Line
                  type="monotone"
                  dataKey="portfolio_return_pct"
                  stroke={scope === "paper" ? "var(--brand-500)" : "var(--profit)"}
                  strokeWidth={2.4}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="flex h-64 items-center justify-center rounded-[28px] border border-dashed border-[var(--line-strong)] bg-white/55 px-6 text-center">
            <p className="text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
              {scope === "paper"
                ? "모의투자 수익률 데이터가 아직 없습니다."
                : "실투자 수익률 데이터가 아직 없습니다. 실거래 체결이 쌓이면 그래프가 표시됩니다."}
            </p>
          </div>
        )}
      </div>
    </article>
  );
}

export default function TossTradingDashboard({ portfolio, accountOverview, isLoading }: TossTradingDashboardProps) {
  const { data: popularStocks, isLoading: popularLoading } = useQuery({
    queryKey: ["dashboard", "popular-stocks"],
    queryFn: fetchPopularStocks,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const { data: agents } = useAgentStatus();
  const { data: config } = usePortfolioConfig();

  const selectedAgents = useMemo(() => {
    if (!agents?.length) return [];
    const orderIndex = new Map(PRIORITY_AGENT_IDS.map((id, index) => [id, index]));
    return [...agents]
      .filter((item) => PRIORITY_AGENT_IDS.includes(item.agent_id))
      .sort((a, b) => (orderIndex.get(a.agent_id) ?? 999) - (orderIndex.get(b.agent_id) ?? 999));
  }, [agents]);

  const topPositions = useMemo(() => {
    if (!portfolio?.positions?.length) return [];
    return [...portfolio.positions].sort((a, b) => b.weight_pct - a.weight_pct).slice(0, 3);
  }, [portfolio?.positions]);

  const totalAsset = isLoading ? null : accountOverview?.total_equity ?? portfolio?.total_value ?? 0;
  const pnlValue = isLoading ? null : accountOverview?.total_pnl ?? portfolio?.total_pnl ?? 0;
  const pnlPct = isLoading ? null : accountOverview?.total_pnl_pct ?? portfolio?.total_pnl_pct ?? 0;
  const accountScope = accountOverview?.account_scope ?? (portfolio?.is_paper ? "paper" : "real");
  const isPositivePnl = (pnlValue ?? 0) >= 0;

  return (
    <div className="page-shell space-y-6">
      <section className="dashboard-hero">
        <div className="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
          <div>
            <span className="inline-flex rounded-full border border-white/20 bg-white/10 px-3 py-1 text-[11px] font-semibold text-white/85">
              SOUL command center
            </span>

            <p className="mt-5 text-sm font-semibold text-white/72">오늘 운용 자산</p>
            <h1 className="mt-2 text-[38px] font-extrabold tracking-[-0.05em] md:text-[54px]">
              {formatWon(totalAsset)}
            </h1>
            <p className="mt-4 max-w-[560px] text-sm leading-6 text-white/78 md:text-base">
              전략 A의 탐색력과 전략 B의 깊은 토론을 함께 쓰되, 확신이 낮거나 조건이 충돌하면 과감히
              멈추는 금융 운영 화면으로 다시 정리했습니다.
            </p>

            <div className="mt-5 flex flex-wrap gap-2">
              <span
                className="inline-flex rounded-full px-3 py-1.5 text-xs font-semibold"
                style={{
                  background: isPositivePnl ? "rgba(240,68,82,0.16)" : "rgba(31,99,247,0.18)",
                  color: isPositivePnl ? "#ffd9de" : "#dbeafe",
                }}
              >
                {pnlValue == null ? "손익 집계 중" : `미실현 손익 ${formatWon(pnlValue)}`}
              </span>
              <span className="inline-flex rounded-full bg-white/12 px-3 py-1.5 text-xs font-semibold text-white/88">
                {pnlPct == null ? "--" : formatPct(pnlPct)}
              </span>
              <span className="inline-flex rounded-full bg-white/12 px-3 py-1.5 text-xs font-semibold text-white/88">
                {accountScope === "paper" ? "페이퍼 트레이딩" : "실거래"}
              </span>
              <span className="inline-flex rounded-full bg-white/12 px-3 py-1.5 text-xs font-semibold text-white/88">
                보유 종목 {portfolio?.positions.length ?? 0}개
              </span>
              {config?.market_hours_enforced ? (
                <span className="inline-flex rounded-full bg-white/12 px-3 py-1.5 text-xs font-semibold text-white/88">
                  {marketStatusChip(config.market_status)}
                </span>
              ) : null}
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <article className="rounded-[26px] border border-white/14 bg-white/10 p-4 backdrop-blur-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-white/58">Daily loss cap</p>
                <p className="mt-3 text-[28px] font-bold tracking-[-0.03em]">
                  -{config?.daily_loss_limit_pct ?? 3}%
                </p>
                <p className="mt-1 text-xs text-white/72">도달 즉시 당일 거래 중단</p>
              </article>
              <article className="rounded-[26px] border border-white/14 bg-white/10 p-4 backdrop-blur-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-white/58">Position cap</p>
                <p className="mt-3 text-[28px] font-bold tracking-[-0.03em]">
                  {config?.max_position_pct ?? 20}%
                </p>
                <p className="mt-1 text-xs text-white/72">단일 종목 비중 상한</p>
              </article>
              <article className="rounded-[26px] border border-white/14 bg-white/10 p-4 backdrop-blur-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-white/58">Confidence floor</p>
                <p className="mt-3 text-[28px] font-bold tracking-[-0.03em]">0.60</p>
                <p className="mt-1 text-xs text-white/72">미만이면 기본값은 HOLD</p>
              </article>
            </div>
          </div>

          <div className="rounded-[30px] border border-white/14 bg-slate-950/10 p-5 backdrop-blur-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-bold tracking-[-0.02em] text-white">오늘의 HOLD 기준</p>
                <p className="mt-1 text-sm text-white/72">불확실성 하에서 자동으로 멈추는 조건들</p>
              </div>
              <span className="rounded-full bg-white/12 px-3 py-1 text-xs font-semibold text-white/82">
                Safety rails
              </span>
            </div>

            <div className="mt-5 space-y-3">
              {HOLD_RULES.map((rule) => (
                <div key={rule} className="flex items-start gap-3 rounded-2xl bg-white/8 px-4 py-3">
                  <span className="mt-1 h-2.5 w-2.5 rounded-full bg-white/70" />
                  <p className="text-sm leading-6 text-white/88">{rule}</p>
                </div>
              ))}
            </div>

            <div className="mt-5 grid gap-2">
              <Link
                to="/strategy"
                className="rounded-2xl border border-white/16 bg-white/10 px-4 py-3 text-sm font-semibold text-white/88 transition-all hover:bg-white/16"
              >
                전략 근거와 토론 전문 보기
              </Link>
              <Link
                to="/settings"
                className="rounded-2xl border border-white/16 bg-white/10 px-4 py-3 text-sm font-semibold text-white/88 transition-all hover:bg-white/16"
              >
                리스크 한도와 실거래 전환 관리
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span className="eyebrow">Return compare</span>
            <h2 className="mt-3 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
              실투자 vs 모의투자 수익률
            </h2>
            <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
              실제 체결 계좌와 KIS 페이퍼 계좌의 누적 수익률 흐름을 나란히 비교합니다.
            </p>
          </div>
          <Link to="/paper-trading" className="btn-secondary">
            모의 투자 상세 보기
          </Link>
        </div>

        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          <ReturnCompareCard
            scope="real"
            title="실투자 수익률"
            subtitle="실거래 체결 이력 기준 월간 수익률 그래프"
            actionTo="/portfolio"
            actionLabel="내 계좌 보기"
          />
          <ReturnCompareCard
            scope="paper"
            title="모의투자 수익률"
            subtitle="한국투자증권 KIS 모의 계좌 기준 월간 수익률 그래프"
            actionTo="/paper-trading"
            actionLabel="모의투자 보기"
          />
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="card">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <span className="eyebrow">Market pulse</span>
              <h2 className="mt-3 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                실시간 인기 종목
              </h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                거래량과 변동성 기준으로 지금 가장 뜨거운 종목을 빠르게 확인합니다.
              </p>
            </div>
            <Link to="/market" className="btn-secondary">
              전체 시세 보기
            </Link>
          </div>

          {popularLoading ? (
            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {[...Array(6)].map((_, index) => (
                <div key={index} className="h-[180px] skeleton" />
              ))}
            </div>
          ) : (
            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(popularStocks ?? []).map((stock, index) => {
                const isPositive = (stock.change_pct ?? 0) >= 0;
                return (
                  <Link
                    key={stock.ticker}
                    to="/market"
                    className="rounded-[26px] border border-white/80 bg-white/78 p-4 transition-all hover:-translate-y-0.5 hover:border-[var(--brand-500)]/20 hover:shadow-[0_24px_40px_rgba(15,23,42,0.08)]"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span
                        className="rounded-full px-2.5 py-1 text-[11px] font-semibold"
                        style={{ background: "var(--bg-input)", color: "var(--text-secondary)" }}
                      >
                        {index + 1}위 · {stock.market}
                      </span>
                      <span
                        className="text-xs font-bold"
                        style={{ color: isPositive ? "var(--profit)" : "var(--loss)" }}
                      >
                        {stock.change_pct != null ? formatPct(stock.change_pct) : "--"}
                      </span>
                    </div>

                    <div
                      className="mt-4 flex h-14 w-14 items-center justify-center rounded-[20px] text-[24px] font-black text-white"
                      style={{ background: ICON_BACKGROUNDS[index % ICON_BACKGROUNDS.length] }}
                    >
                      {iconLabel(stock.name, stock.ticker)}
                    </div>

                    <div className="mt-4">
                      <p className="text-[18px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                        {stock.ticker}
                      </p>
                      <p className="mt-1 truncate text-sm" style={{ color: "var(--text-secondary)" }}>
                        {stock.name}
                      </p>
                    </div>

                    <div className="mt-5 flex items-end justify-between gap-3">
                      <div>
                        <p className="text-[18px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                          {formatWon(stock.current_price)}
                        </p>
                        <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
                          거래량 {formatCompactNumber(stock.volume)}
                        </p>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        <section className="space-y-4">
          <article className="card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="eyebrow">Navigate</span>
                <h2 className="mt-3 text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  빠른 이동
                </h2>
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              {QUICK_LINKS.map((item) => (
                <QuickLinkCard key={item.to} {...item} />
              ))}
            </div>
          </article>

          <article className="card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="eyebrow">Exposure</span>
                <h2 className="mt-3 text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  상위 포지션
                </h2>
              </div>
              <Link to="/portfolio" className="btn-secondary">
                계좌 보기
              </Link>
            </div>

            {topPositions.length ? (
              <div className="mt-5 space-y-3">
                {topPositions.map((position, index) => (
                  <div key={position.ticker} className="inner-card">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-bold tracking-[-0.02em]" style={{ color: "var(--text-primary)" }}>
                          {index + 1}. {position.name}
                        </p>
                        <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                          {position.ticker} · {position.quantity.toLocaleString()}주
                        </p>
                      </div>
                      <span className="chip">{position.weight_pct}%</span>
                    </div>
                    <div className="mt-4 flex items-center justify-between text-sm">
                      <span style={{ color: "var(--text-secondary)" }}>평가손익</span>
                      <span className={position.unrealized_pnl >= 0 ? "text-profit" : "text-loss"}>
                        {formatWon(position.unrealized_pnl)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-5 text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
                아직 보유 포지션이 없습니다. 페이퍼 모드에서 전략 신호를 충분히 검증한 뒤 포지션을 열 수 있습니다.
              </p>
            )}
          </article>
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <section className="card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <span className="eyebrow">Live operations</span>
              <h2 className="mt-3 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                에이전트 활동
              </h2>
            </div>
            <span className="chip">실시간 상태</span>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {selectedAgents.map((agent) => {
              const tone = activityTone(agent.activity_state);
              return (
                <div
                  key={agent.agent_id}
                  className="rounded-[24px] border border-white/70 bg-white/72 p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-bold tracking-[-0.02em]" style={{ color: "var(--text-primary)" }}>
                      {AGENT_LABELS[agent.agent_id] ?? agent.agent_id}
                    </p>
                    <span className={toneDot(tone)} />
                  </div>
                  <p className="mt-3 text-sm font-semibold" style={{ color: toneColor(tone) }}>
                    {agent.activity_label}
                  </p>
                  <p className="mt-2 text-xs leading-5" style={{ color: "var(--text-secondary)" }}>
                    {agent.last_action ?? "마지막 액션 정보 없음"}
                  </p>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <span className="eyebrow">Transparency</span>
              <h2 className="mt-3 text-[24px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                운영 원칙
              </h2>
            </div>
            <span className="chip">SOUL.md</span>
          </div>

          <div className="mt-5 space-y-3">
            {TRANSPARENCY_PROMISES.map((promise) => (
              <div key={promise} className="inner-card flex items-start gap-3">
                <span
                  className="mt-1 inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
                  style={{ background: "var(--brand-bg)", color: "var(--brand-500)" }}
                >
                  i
                </span>
                <p className="text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
                  {promise}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <span className="chip">서킷브레이커 절대 우선</span>
            <span className="chip">HOLD is a feature</span>
            <span className="chip">페이퍼 트레이딩 기본값</span>
          </div>
        </section>
      </div>
    </div>
  );
}
