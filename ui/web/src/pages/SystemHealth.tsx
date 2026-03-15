import { useSystemHealthOverview, useSystemMetrics } from "@/hooks/useSystemHealth";

function ServiceCard({ name, status, latency_ms }: { name: string; status: string; latency_ms: number | null }) {
  const colors: Record<string, { bg: string; text: string; dot: string }> = {
    ok: { bg: "var(--green-bg)", text: "var(--green)", dot: "bg-green-400" },
    degraded: { bg: "#fff3cd", text: "#856404", dot: "bg-yellow-400" },
    error: { bg: "#f8d7da", text: "#721c24", dot: "bg-red-400" },
  };
  const c = colors[status] ?? colors.error;

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>{name}</h3>
        <span className={`h-3 w-3 rounded-full ${c.dot}`} />
      </div>
      <div className="mt-2">
        <span className="inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold" style={{ background: c.bg, color: c.text }}>
          {status === "ok" ? "정상" : status === "degraded" ? "저하" : "오류"}
        </span>
      </div>
      {latency_ms !== null && (
        <p className="mt-1 text-xs" style={{ color: "var(--text-tertiary)" }}>응답시간: {latency_ms}ms</p>
      )}
    </div>
  );
}

export default function SystemHealth() {
  const { data: overview, isLoading: loadingOverview } = useSystemHealthOverview();
  const { data: metrics, isLoading: loadingMetrics } = useSystemMetrics();

  return (
    <div className="page-shell">
      <section className="card">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>시스템 헬스</h2>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>인프라 서비스 및 에이전트 상태 모니터링</p>
          </div>
          {overview && (
            <span
              className="inline-flex rounded-full px-3 py-1 text-xs font-bold"
              style={{
                background: overview.overall_status === "healthy" ? "var(--green-bg)" : "#f8d7da",
                color: overview.overall_status === "healthy" ? "var(--green)" : "#721c24",
              }}
            >
              {overview.overall_status === "healthy" ? "전체 정상" : overview.overall_status}
            </span>
          )}
        </div>
      </section>

      <h3 className="mt-4 text-sm font-bold" style={{ color: "var(--text-primary)" }}>서비스 상태</h3>
      {loadingOverview ? (
        <div className="grid gap-3 md:grid-cols-3">{[1, 2, 3].map(i => <div key={i} className="h-24 skeleton" />)}</div>
      ) : (
        <div className="mt-2 grid gap-3 md:grid-cols-3">
          {overview?.services.map(s => <ServiceCard key={s.name} name={s.name} status={s.status} latency_ms={s.latency_ms} />)}
        </div>
      )}

      {overview && (
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <div className="card text-center">
            <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{overview.agent_summary.total}</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>전체 에이전트</p>
          </div>
          <div className="card text-center">
            <p className="text-2xl font-bold" style={{ color: "var(--green)" }}>{overview.agent_summary.alive}</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>활성</p>
          </div>
          <div className="card text-center">
            <p className="text-2xl font-bold" style={{ color: "#dc3545" }}>{overview.agent_summary.dead}</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>비활성</p>
          </div>
          <div className="card text-center">
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>마지막 오케스트레이터 사이클</p>
            <p className="mt-1 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              {overview.last_orchestrator_cycle ? new Date(overview.last_orchestrator_cycle).toLocaleString("ko-KR") : "기록 없음"}
            </p>
          </div>
        </div>
      )}

      <h3 className="mt-6 text-sm font-bold" style={{ color: "var(--text-primary)" }}>24시간 메트릭</h3>
      {loadingMetrics ? (
        <div className="mt-2 grid gap-3 md:grid-cols-4">{[1, 2, 3, 4].map(i => <div key={i} className="h-20 skeleton" />)}</div>
      ) : metrics && (
        <div className="mt-2 grid gap-3 md:grid-cols-4">
          <div className="card text-center">
            <p className="text-2xl font-bold" style={{ color: "#dc3545" }}>{metrics.error_count_24h}</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>에러 수 (24h)</p>
          </div>
          <div className="card text-center">
            <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{metrics.total_heartbeats_24h}</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>하트비트 (24h)</p>
          </div>
          <div className="card text-center">
            <p className="text-2xl font-bold" style={{ color: "var(--brand-500)" }}>{metrics.active_agents}</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>활성 에이전트 (5분)</p>
          </div>
          <div className="card text-center">
            <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{metrics.db_table_count}</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>DB 테이블 수</p>
          </div>
        </div>
      )}

      {metrics && metrics.recent_errors.length > 0 && (
        <section className="card mt-4">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>최근 에러 (24h)</h3>
          <div className="mt-2 max-h-60 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b" style={{ color: "var(--text-secondary)" }}>
                  <th className="py-1.5 text-left font-medium">에이전트</th>
                  <th className="py-1.5 text-left font-medium">상태</th>
                  <th className="py-1.5 text-left font-medium">동작</th>
                  <th className="py-1.5 text-left font-medium">시각</th>
                </tr>
              </thead>
              <tbody>
                {metrics.recent_errors.map((err, i) => (
                  <tr key={i} className="border-b border-slate-100">
                    <td className="py-1.5 font-medium">{String(err.agent_id)}</td>
                    <td className="py-1.5"><span className="rounded-full bg-red-50 px-2 py-0.5 text-red-700">{String(err.status)}</span></td>
                    <td className="max-w-xs truncate py-1.5" style={{ color: "var(--text-secondary)" }}>{String(err.last_action || "-")}</td>
                    <td className="py-1.5" style={{ color: "var(--text-tertiary)" }}>{err.recorded_at ? new Date(String(err.recorded_at)).toLocaleString("ko-KR") : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
