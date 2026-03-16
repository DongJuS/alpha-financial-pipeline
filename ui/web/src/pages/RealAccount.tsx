/**
 * ui/web/src/pages/RealAccount.tsx — KIS 실계좌 보유종목 라이브 조회 페이지
 */
import { useRealHoldings } from "@/hooks/usePortfolio";
import { formatKRW, formatPct } from "@/utils/api";

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export default function RealAccount() {
  const { data, isLoading, isError, error, refetch, isFetching } = useRealHoldings();

  return (
    <div className="page-shell">
      {/* ── Hero ─────────────────────────────────────────────── */}
      <section className="card">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-[22px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                실계좌 보유종목
              </h2>
              <span
                className="rounded-full px-2.5 py-1 text-xs font-semibold"
                style={{ background: "var(--red-bg)", color: "var(--red)" }}
              >
                KIS Real
              </span>
            </div>
            {data && (
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                계좌 {data.account_number_masked} · 마지막 조회{" "}
                {new Date(data.fetched_at).toLocaleTimeString("ko-KR")}
              </p>
            )}
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="btn-secondary flex items-center gap-2"
          >
            <svg
              className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21 12a9 9 0 1 1-6.22-8.56" strokeLinecap="round" />
            </svg>
            {isFetching ? "조회 중..." : "새로고침"}
          </button>
        </div>
      </section>

      {/* ── 에러 상태 ──────────────────────────────────────────── */}
      {isError && (
        <section className="card" style={{ borderLeft: "4px solid var(--red)" }}>
          <h3 className="font-semibold" style={{ color: "var(--red)" }}>
            KIS Real API 조회 실패
          </h3>
          <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
            {(error as Error)?.message || "KIS 서버 연결에 실패했습니다. 토큰 발급 상태를 확인하세요."}
          </p>
          <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
            터미널에서 <code className="rounded bg-slate-100 px-1.5 py-0.5">python scripts/kis_auth.py --scope real</code>을
            실행하여 토큰을 발급받으세요.
          </p>
        </section>
      )}

      {/* ── 로딩 상태 ──────────────────────────────────────────── */}
      {isLoading && (
        <section className="card">
          <div className="grid gap-4 md:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-20 rounded-2xl" />
            ))}
          </div>
          <div className="mt-6">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="mt-3 h-12 rounded-xl" />
            ))}
          </div>
        </section>
      )}

      {/* ── 계좌 요약 KPI ─────────────────────────────────────── */}
      {data && (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <KpiCard
              label="예수금"
              value={formatKRW(data.summary.cash_balance)}
            />
            <KpiCard
              label="주식 평가금액"
              value={formatKRW(data.summary.total_eval_amount)}
            />
            <KpiCard
              label="총 자산"
              value={formatKRW(data.summary.total_equity)}
              highlight
            />
            <KpiCard
              label="평가 손익"
              value={formatKRW(data.summary.total_unrealized_pnl)}
              sub={formatPct(data.summary.total_unrealized_pnl_pct)}
              positive={data.summary.total_unrealized_pnl >= 0}
            />
          </section>

          {/* ── 보유종목 테이블 ───────────────────────────────── */}
          <section className="card">
            <h3 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
              보유종목 ({data.positions.length}건)
            </h3>

            {data.positions.length === 0 ? (
              <p className="mt-4 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>
                보유 중인 종목이 없습니다.
              </p>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr
                      className="border-b text-left text-xs font-semibold"
                      style={{ color: "var(--text-secondary)", borderColor: "var(--border)" }}
                    >
                      <th className="pb-3 pr-4">종목</th>
                      <th className="pb-3 pr-4 text-right">수량</th>
                      <th className="pb-3 pr-4 text-right">평균단가</th>
                      <th className="pb-3 pr-4 text-right">현재가</th>
                      <th className="pb-3 pr-4 text-right">평가금액</th>
                      <th className="pb-3 text-right">평가손익</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.positions.map((pos) => (
                      <tr
                        key={pos.ticker}
                        className="border-b last:border-0"
                        style={{ borderColor: "var(--border)" }}
                      >
                        <td className="py-3 pr-4">
                          <div className="font-semibold" style={{ color: "var(--text-primary)" }}>
                            {pos.name}
                          </div>
                          <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                            {pos.ticker}
                          </div>
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums" style={{ color: "var(--text-primary)" }}>
                          {pos.quantity.toLocaleString("ko-KR")}
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums" style={{ color: "var(--text-secondary)" }}>
                          {pos.avg_price.toLocaleString("ko-KR")}
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums" style={{ color: "var(--text-primary)" }}>
                          {pos.current_price.toLocaleString("ko-KR")}
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums" style={{ color: "var(--text-primary)" }}>
                          {formatKRW(pos.eval_amount)}
                        </td>
                        <td className="py-3 text-right">
                          <div
                            className="font-semibold tabular-nums"
                            style={{ color: pos.unrealized_pnl >= 0 ? "var(--green)" : "var(--red)" }}
                          >
                            {formatKRW(pos.unrealized_pnl)}
                          </div>
                          <div
                            className="text-xs tabular-nums"
                            style={{ color: pos.unrealized_pnl >= 0 ? "var(--green)" : "var(--red)" }}
                          >
                            {formatPct(pos.unrealized_pnl_pct)}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

/* ── KPI 카드 서브 컴포넌트 ─────────────────────────────────────── */
function KpiCard({
  label,
  value,
  sub,
  positive,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
  highlight?: boolean;
}) {
  return (
    <div
      className="card"
      style={
        highlight
          ? {
              background: "linear-gradient(135deg, var(--brand-500), #4b9dff)",
              color: "white",
            }
          : undefined
      }
    >
      <div
        className="text-xs font-semibold uppercase tracking-wider"
        style={{ color: highlight ? "rgba(255,255,255,0.7)" : "var(--text-tertiary)" }}
      >
        {label}
      </div>
      <div className="mt-1 text-xl font-bold tabular-nums">{value}</div>
      {sub && (
        <div
          className="mt-0.5 text-sm font-semibold tabular-nums"
          style={{
            color: highlight
              ? "rgba(255,255,255,0.85)"
              : positive
              ? "var(--green)"
              : "var(--red)",
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}
