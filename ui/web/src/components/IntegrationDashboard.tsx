/**
 * ui/src/components/IntegrationDashboard.tsx
 * Phase 10: Integration Status Dashboard
 * Shows search sources, RL evaluation, active policies, and audit status
 */
import { useEffect, useState } from "react";
import { TrendingUp, AlertCircle, CheckCircle, Clock } from "lucide-react";

// ── Type Definitions ──────────────────────────────────────────────────────

interface SearchSourceItem {
  query_id: string;
  ticker: string;
  query: string;
  sentiment: string;
  source_count: number;
  confidence: number;
  sources: string[];
  timestamp: string;
}

interface SearchSourcesResponse {
  items: SearchSourceItem[];
  total_count: number;
  last_updated: string;
}

interface RLEvaluationItem {
  policy_id: string;
  ticker: string;
  algorithm: string;
  holdout_return_pct: number;
  sharpe_ratio: number | null;
  win_rate: number;
  status: string;
  timestamp: string;
}

interface RLEvaluationResponse {
  items: RLEvaluationItem[];
  total_count: number;
  last_updated: string;
}

interface ActivePolicyItem {
  policy_id: string;
  ticker: string;
  algorithm: string;
  strategy_id: string;
  mode: string;
  last_inference_time: string | null;
  return_pct: number;
  trades_count: number;
  timestamp: string;
}

interface ActivePoliciesResponse {
  items: ActivePolicyItem[];
  total_count: number;
  last_updated: string;
}

interface AuditCheckItem {
  category: string;
  item_name: string;
  status: string;
  details: string | null;
}

interface AuditStatusResponse {
  items: AuditCheckItem[];
  overall_status: string;
  last_updated: string;
}

// ── Helper Functions ──────────────────────────────────────────────────────

function getSentimentColor(sentiment: string): string {
  const colors: Record<string, string> = {
    bullish: "#0cb58f",
    bearish: "#f04452",
    neutral: "#94a3b8",
  };
  return colors[sentiment] || colors.neutral;
}

function getSentimentBg(sentiment: string): string {
  const bgs: Record<string, string> = {
    bullish: "rgba(12,181,143,0.12)",
    bearish: "rgba(240,68,82,0.12)",
    neutral: "rgba(148,163,184,0.12)",
  };
  return bgs[sentiment] || bgs.neutral;
}

function getSentimentLabel(sentiment: string): string {
  const labels: Record<string, string> = {
    bullish: "강세",
    bearish: "약세",
    neutral: "중립",
  };
  return labels[sentiment] || sentiment;
}

function getStatusBg(status: string): string {
  const bgs: Record<string, string> = {
    pass: "rgba(12,181,143,0.12)",
    approved: "rgba(12,181,143,0.12)",
    fail: "rgba(240,68,82,0.12)",
    warning: "rgba(194,123,10,0.12)",
    pending: "rgba(31,99,247,0.12)",
  };
  return bgs[status] || bgs.pending;
}

function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    pass: "#0cb58f",
    approved: "#0cb58f",
    fail: "#f04452",
    warning: "#c27b0a",
    pending: "#1f63f7",
  };
  return colors[status] || colors.pending;
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pass: "통과",
    approved: "승인",
    fail: "실패",
    warning: "경고",
    pending: "대기중",
  };
  return labels[status] || status;
}

function getModalLabel(mode: string): string {
  const labels: Record<string, string> = {
    shadow: "섀도우",
    paper: "모의",
    live: "실전",
  };
  return labels[mode] || mode;
}

function getModalColor(mode: string): { bg: string; text: string } {
  const colors: Record<string, { bg: string; text: string }> = {
    shadow: { bg: "rgba(148,163,184,0.12)", text: "#64748b" },
    paper: { bg: "rgba(31,99,247,0.12)", text: "#1f63f7" },
    live: { bg: "rgba(240,68,82,0.12)", text: "#f04452" },
  };
  return colors[mode] || colors.shadow;
}

function formatPct(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "--";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatPercentBar(value: number): string {
  return `${Math.round(value * 100)}%`;
}

// ── Search Sources Panel ──────────────────────────────────────────────────

function SearchSourcesPanel() {
  const [data, setData] = useState<SearchSourcesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch("/api/v1/integration/search-sources");
        if (!res.ok) throw new Error("Failed to fetch search sources");
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-16 skeleton" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 p-3">
        <p className="text-sm text-red-700">{error}</p>
      </div>
    );
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 p-4 text-center">
        <p style={{ color: "var(--text-secondary)" }} className="text-sm">
          검색 결과가 없습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {data.items.map((item) => {
        const sentimentBg = getSentimentBg(item.sentiment);
        const sentimentColor = getSentimentColor(item.sentiment);
        const sentimentLabel = getSentimentLabel(item.sentiment);

        return (
          <div
            key={item.query_id}
            className="rounded-xl border border-gray-100 bg-white/60 p-3 hover:shadow-sm transition-shadow"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="text-[10px] font-bold uppercase tracking-wider rounded px-2 py-0.5"
                    style={{
                      background: sentimentBg,
                      color: sentimentColor,
                    }}
                  >
                    {sentimentLabel}
                  </span>
                  <span
                    className="text-[10px] font-bold rounded px-2 py-0.5"
                    style={{ background: "var(--bg-input)", color: "var(--text-muted)" }}
                  >
                    {item.ticker}
                  </span>
                </div>
                <p
                  className="text-sm font-medium truncate"
                  style={{ color: "var(--text-primary)" }}
                >
                  {item.query}
                </p>
                <p
                  className="text-xs mt-1"
                  style={{ color: "var(--text-secondary)" }}
                >
                  소스 {item.source_count}개
                </p>
              </div>
              <div className="text-right">
                <div className="mb-1">
                  <div
                    className="w-12 h-1.5 rounded-full"
                    style={{
                      background: "var(--bg-input)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        background: sentimentColor,
                        width: formatPercentBar(item.confidence),
                      }}
                    />
                  </div>
                </div>
                <p
                  className="text-xs font-semibold"
                  style={{ color: "var(--text-muted)" }}
                >
                  {formatPercentBar(item.confidence)}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── RL Evaluation Panel ────────────────────────────────────────────────────

function RLEvaluationPanel() {
  const [data, setData] = useState<RLEvaluationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch("/api/v1/integration/rl-evaluation");
        if (!res.ok) throw new Error("Failed to fetch RL evaluation");
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  if (isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {[...Array(2)].map((_, i) => (
          <div key={i} className="h-32 skeleton" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 p-3">
        <p className="text-sm text-red-700">{error}</p>
      </div>
    );
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 p-4 text-center">
        <p style={{ color: "var(--text-secondary)" }} className="text-sm">
          평가 결과가 없습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {data.items.map((item) => {
        const statusBg = getStatusBg(item.status);
        const statusColor = getStatusColor(item.status);
        const statusLabel = getStatusLabel(item.status);
        const isPositive = item.holdout_return_pct >= 0;

        return (
          <div
            key={item.policy_id}
            className="rounded-xl border border-gray-100 bg-white/60 p-4"
          >
            <div className="flex items-start justify-between gap-2 mb-3">
              <div>
                <p
                  className="text-sm font-bold"
                  style={{ color: "var(--text-primary)" }}
                >
                  {item.ticker}
                </p>
                <p
                  className="text-xs"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {item.algorithm}
                </p>
              </div>
              <span
                className="text-[10px] font-bold px-2 py-1 rounded"
                style={{
                  background: statusBg,
                  color: statusColor,
                }}
              >
                {statusLabel}
              </span>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between items-center text-xs">
                <span style={{ color: "var(--text-secondary)" }}>
                  홀드아웃 수익률
                </span>
                <span
                  className="font-bold"
                  style={{
                    color: isPositive ? "var(--profit)" : "var(--loss)",
                  }}
                >
                  {formatPct(item.holdout_return_pct)}
                </span>
              </div>

              <div className="flex justify-between items-center text-xs">
                <span style={{ color: "var(--text-secondary)" }}>
                  샤프 지수
                </span>
                <span
                  className="font-bold"
                  style={{ color: "var(--text-primary)" }}
                >
                  {item.sharpe_ratio !== null
                    ? item.sharpe_ratio.toFixed(2)
                    : "--"}
                </span>
              </div>

              <div className="flex justify-between items-center text-xs">
                <span style={{ color: "var(--text-secondary)" }}>
                  승률
                </span>
                <span
                  className="font-bold"
                  style={{ color: "var(--text-primary)" }}
                >
                  {formatPercentBar(item.win_rate)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Active Policies Panel ──────────────────────────────────────────────────

function ActivePoliciesPanel() {
  const [data, setData] = useState<ActivePoliciesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch("/api/v1/integration/active-policies");
        if (!res.ok) throw new Error("Failed to fetch active policies");
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(2)].map((_, i) => (
          <div key={i} className="h-20 skeleton" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 p-3">
        <p className="text-sm text-red-700">{error}</p>
      </div>
    );
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 p-4 text-center">
        <p style={{ color: "var(--text-secondary)" }} className="text-sm">
          활성 정책이 없습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {data.items.map((item) => {
        const modeColor = getModalColor(item.mode);
        const modeLabel = getModalLabel(item.mode);
        const isPositive = item.return_pct >= 0;

        return (
          <div
            key={item.policy_id}
            className="rounded-xl border border-gray-100 bg-white/60 p-3 hover:shadow-sm transition-shadow"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="text-[10px] font-bold uppercase tracking-wider rounded px-2 py-0.5"
                    style={{
                      background: modeColor.bg,
                      color: modeColor.text,
                    }}
                  >
                    {modeLabel}
                  </span>
                  <span
                    className="text-[10px] font-bold rounded px-2 py-0.5"
                    style={{ background: "var(--bg-input)", color: "var(--text-muted)" }}
                  >
                    {item.ticker} · {item.algorithm}
                  </span>
                </div>
                <p
                  className="text-sm font-medium"
                  style={{ color: "var(--text-primary)" }}
                >
                  {item.policy_id}
                </p>
                <p
                  className="text-xs mt-1"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {item.trades_count}건 거래
                </p>
              </div>
              <div className="text-right">
                <span
                  className="text-sm font-bold"
                  style={{
                    color: isPositive ? "var(--profit)" : "var(--loss)",
                  }}
                >
                  {formatPct(item.return_pct)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Audit Status Panel ────────────────────────────────────────────────────

function AuditStatusPanel() {
  const [data, setData] = useState<AuditStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch("/api/v1/integration/audit-status");
        if (!res.ok) throw new Error("Failed to fetch audit status");
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-12 skeleton" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 p-3">
        <p className="text-sm text-red-700">{error}</p>
      </div>
    );
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 p-4 text-center">
        <p style={{ color: "var(--text-secondary)" }} className="text-sm">
          감사 항목이 없습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {data.items.map((item, idx) => {
        const statusBg = getStatusBg(item.status);
        const statusColor = getStatusColor(item.status);
        const statusLabel = getStatusLabel(item.status);
        const IconComponent =
          item.status === "pass" || item.status === "approved"
            ? CheckCircle
            : item.status === "fail"
              ? AlertCircle
              : Clock;

        return (
          <div
            key={`${item.category}-${idx}`}
            className="rounded-xl border border-gray-100 bg-white/60 p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-start gap-2 flex-1">
                <IconComponent
                  size={16}
                  style={{ color: statusColor, marginTop: "2px", flexShrink: 0 }}
                />
                <div className="flex-1 min-w-0">
                  <p
                    className="text-sm font-medium"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {item.item_name}
                  </p>
                  {item.details && (
                    <p
                      className="text-xs mt-0.5"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {item.details}
                    </p>
                  )}
                </div>
              </div>
              <span
                className="text-[10px] font-bold px-2 py-1 rounded whitespace-nowrap"
                style={{
                  background: statusBg,
                  color: statusColor,
                }}
              >
                {statusLabel}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────

export default function IntegrationDashboard() {
  const [activeTab, setActiveTab] = useState<
    "sources" | "evaluation" | "policies" | "audit"
  >("sources");

  return (
    <section className="card">
      <div>
        <span className="eyebrow">Integration Status</span>
        <h2
          className="mt-3 text-[24px] font-bold tracking-tight"
          style={{ color: "var(--text-primary)" }}
        >
          통합 대시보드
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          검색 소스, RL 평가, 활성 정책, 시스템 감사 상태를 모니터링합니다.
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="mt-5 flex gap-2 border-b" style={{ borderColor: "var(--bg-input)" }}>
        {(
          [
            { id: "sources", label: "검색 소스" },
            { id: "evaluation", label: "RL 평가" },
            { id: "policies", label: "활성 정책" },
            { id: "audit", label: "감시 상태" },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="px-3 py-2.5 text-sm font-medium transition-colors relative"
            style={{
              color:
                activeTab === tab.id
                  ? "var(--text-primary)"
                  : "var(--text-secondary)",
            }}
          >
            {tab.label}
            {activeTab === tab.id && (
              <div
                className="absolute bottom-0 left-0 right-0 h-0.5"
                style={{ background: "var(--text-primary)" }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="mt-5">
        {activeTab === "sources" && <SearchSourcesPanel />}
        {activeTab === "evaluation" && <RLEvaluationPanel />}
        {activeTab === "policies" && <ActivePoliciesPanel />}
        {activeTab === "audit" && <AuditStatusPanel />}
      </div>
    </section>
  );
}
