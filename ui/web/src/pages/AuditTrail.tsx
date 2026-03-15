/**
 * ui/src/pages/AuditTrail.tsx
 * 감사 로그 — 시스템 활동 추적 (통합 감사 API 연동)
 */
import { useState } from "react";
import { useAuditTrail, useAuditSummary } from "@/hooks/useAudit";

function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, { bg: string; color: string }> = {
    trade: { bg: "var(--green-bg)", color: "var(--green)" },
    operational_audit: { bg: "#e0e7ff", color: "#4338ca" },
    notification: { bg: "#fef3c7", color: "#92400e" },
  };
  const s = colors[type] ?? { bg: "var(--bg-secondary)", color: "var(--text-secondary)" };
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: s.bg, color: s.color }}
    >
      {type}
    </span>
  );
}

export default function AuditTrailPage() {
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState("");
  const { data: trail, isLoading } = useAuditTrail({ page, limit: 30, event_type: eventType || undefined });
  const { data: summary } = useAuditSummary();

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>투명성</p>
        <h1
          className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]"
          style={{ color: "var(--text-primary)" }}
        >
          감사 로그
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          모든 거래 활동과 에이전트 의사결정을 투명하게 기록합니다.
        </p>
      </section>

      {summary && (
        <div className="grid gap-3 md:grid-cols-4">
          <div className="card">
            <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>총 이벤트</p>
            <p className="mt-1 text-xl font-bold" style={{ color: "var(--text-primary)" }}>
              {summary.total_events.toLocaleString()}
            </p>
          </div>
          <div className="card">
            <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>통과율</p>
            <p className="mt-1 text-xl font-bold" style={{ color: "var(--green)" }}>
              {summary.pass_rate != null ? `${(summary.pass_rate * 100).toFixed(1)}%` : "—"}
            </p>
          </div>
          {summary.by_type &&
            Object.entries(summary.by_type).map(([type, count]) => (
              <div key={type} className="card">
                <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>{type}</p>
                <p className="mt-1 text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                  {(count as number).toLocaleString()}
                </p>
              </div>
            ))}
        </div>
      )}

      <div className="card">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>감사 추적</h3>
          <select
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border px-2 py-1 text-xs"
            style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
          >
            <option value="">전체</option>
            <option value="trade">거래</option>
            <option value="operational_audit">운영 감사</option>
            <option value="notification">알림</option>
          </select>
        </div>

        {isLoading ? (
          <div className="mt-3 h-40 skeleton" />
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>시간</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>유형</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>에이전트</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>내용</th>
                  <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>결과</th>
                </tr>
              </thead>
              <tbody>
                {(trail?.data ?? []).map((item, i) => (
                  <tr key={i} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="py-2 font-mono text-[11px]" style={{ color: "var(--text-secondary)" }}>
                      {item.event_time?.slice(0, 16).replace("T", " ")}
                    </td>
                    <td className="py-2">
                      <TypeBadge type={item.event_type} />
                    </td>
                    <td className="py-2 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                      {item.agent_id ?? "—"}
                    </td>
                    <td className="max-w-xs truncate py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {item.description}
                    </td>
                    <td className="py-2 text-right">
                      {item.result && (
                        <span
                          className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                          style={{
                            background: item.result === "pass" ? "var(--green-bg)" : "var(--red-bg)",
                            color: item.result === "pass" ? "var(--green)" : "var(--red)",
                          }}
                        >
                          {item.result}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(trail?.data ?? []).length === 0 && (
              <p className="py-6 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>
                감사 기록이 없습니다.
              </p>
            )}
          </div>
        )}

        {trail && trail.total > 30 && (
          <div className="mt-3 flex items-center justify-center gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-lg px-3 py-1 text-xs font-semibold disabled:opacity-40"
              style={{ color: "var(--brand-500)" }}
            >
              ← 이전
            </button>
            <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              {page} / {Math.ceil(trail.total / 30)}
            </span>
            <button
              disabled={page >= Math.ceil(trail.total / 30)}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-lg px-3 py-1 text-xs font-semibold disabled:opacity-40"
              style={{ color: "var(--brand-500)" }}
            >
              다음 →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
