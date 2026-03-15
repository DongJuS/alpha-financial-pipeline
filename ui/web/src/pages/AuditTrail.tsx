/**
 * ui/src/pages/AuditTrail.tsx
 * 감사 로그 — 시스템 활동 추적
 */
import { useTradeHistory } from "@/hooks/usePortfolio";

export default function AuditTrailPage() {
  const { data: history, isLoading } = useTradeHistory(1, 50);

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>투명성</p>
        <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
          감사 로그
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          모든 거래 활동과 에이전트 의사결정을 투명하게 기록합니다.
        </p>
      </section>

      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>최근 거래 기록</h3>
        {isLoading ? (
          <div className="mt-3 h-40 skeleton" />
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>시간</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>종목</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>방향</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>전략</th>
                  <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>수량</th>
                  <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>가격</th>
                </tr>
              </thead>
              <tbody>
                {(history?.data ?? []).map((t, i) => (
                  <tr key={i} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="py-2 font-mono text-[11px]" style={{ color: "var(--text-secondary)" }}>
                      {t.executed_at?.slice(0, 16).replace("T", " ")}
                    </td>
                    <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>{t.name}</td>
                    <td className="py-2">
                      <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{
                        background: t.side === "BUY" ? "var(--green-bg)" : "var(--red-bg)",
                        color: t.side === "BUY" ? "var(--green)" : "var(--red)",
                      }}>{t.side}</span>
                    </td>
                    <td className="py-2 text-xs" style={{ color: "var(--text-secondary)" }}>{t.signal_source ?? "—"}</td>
                    <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>{t.quantity}</td>
                    <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                      {t.price.toLocaleString("ko-KR")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
