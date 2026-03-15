/**
 * ui/src/pages/SystemHealth.tsx
 * 시스템 헬스 모니터링 대시보드
 */
import {
  useSystemHealthOverview,
  useSystemMetrics,
  type ServiceStatus,
} from "@/hooks/useSystemHealth";

function ServiceCard({ service }: { service: ServiceStatus }) {
  const color =
    service.status === "ok"
      ? { bg: "var(--green-bg)", text: "var(--green)" }
      : service.status === "degraded"
        ? { bg: "#fff3cd", text: "#856404" }
        : { bg: "#f8d7da", text: "#721c24" };

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          {service.name}
        </h4>
        <span
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={{ background: color.bg, color: color.text }}
        >
          {service.status}
        </span>
      </div>
      {service.latency_ms != null && (
        <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
          응답 시간: {service.latency_ms}ms
        </p>
      )}
    </div>
  );
}

export default function SystemHealth() {
  const { data: overview, isLoading: overviewLoading } = useSystemHealthOverview();
  const { data: metrics, isLoading: metricsLoading } = useSystemMetrics();

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>인프라</p>
        <h1
          className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]"
          style={{ color: "var(--text-primary)" }}
        >
          시스템 헬스
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          PostgreSQL · Redis · S3 인프라 상태 및 에이전트 헬스를 모니터링합니다.
        </p>
      </section>

      {overviewLoading ? (
        <div className="grid gap-3 md:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 skeleton" />
          ))}
        </div>
      ) : overview ? (
        <>
          <div className="card">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
                전체 상태
              </h3>
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{
                  background:
                    overview.overall_status === "healthy"
                      ? "var(--green-bg)"
                      : overview.overall_status === "degraded"
                        ? "#fff3cd"
                        : "#f8d7da",
                  color:
                    overview.overall_status === "healthy"
                      ? "var(--green)"
                      : overview.overall_status === "degraded"
                        ? "#856404"
                        : "#721c24",
                }}
              >
                {overview.overall_status}
              </span>
            </div>
            {overview.last_orchestrator_cycle && (
              <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
                마지막 오케스트레이터 사이클: {new Date(overview.last_orchestrator_cycle).toLocaleString("ko-KR")}
              </p>
            )}
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            {overview.services.map((svc) => (
              <ServiceCard key={svc.name} service={svc} />
            ))}
          </div>

          <div className="card">
            <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>에이전트 요약</h3>
            <div className="mt-3 grid grid-cols-4 gap-3">
              <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
                <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>전체</p>
                <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>{overview.agent_summary.total}</p>
              </div>
              <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
                <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>정상</p>
                <p className="text-xl font-bold" style={{ color: "var(--green)" }}>{overview.agent_summary.alive}</p>
              </div>
              <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
                <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>중단</p>
                <p className="text-xl font-bold" style={{ color: "var(--red)" }}>{overview.agent_summary.dead}</p>
              </div>
              <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
                <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>경고</p>
                <p className="text-xl font-bold" style={{ color: "#856404" }}>{overview.agent_summary.degraded}</p>
              </div>
            </div>
          </div>
        </>
      ) : null}

      {metricsLoading ? (
        <div className="h-40 skeleton" />
      ) : metrics ? (
        <div className="card">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>24시간 메트릭</h3>
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>에러 수</p>
              <p className="text-xl font-bold" style={{ color: metrics.error_count_24h > 0 ? "var(--red)" : "var(--text-primary)" }}>
                {metrics.error_count_24h}
              </p>
            </div>
            <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>총 하트비트</p>
              <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                {metrics.total_heartbeats_24h.toLocaleString()}
              </p>
            </div>
            <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>활성 에이전트</p>
              <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                {metrics.active_agents}
              </p>
            </div>
            <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>DB 테이블</p>
              <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                {metrics.db_table_count}
              </p>
            </div>
          </div>

          {metrics.recent_errors.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>최근 에러</h4>
              <div className="mt-2 max-h-48 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b" style={{ color: "var(--text-secondary)" }}>
                      <th className="py-1 text-left font-medium">시각</th>
                      <th className="py-1 text-left font-medium">에이전트</th>
                      <th className="py-1 text-left font-medium">상태</th>
                      <th className="py-1 text-left font-medium">동작</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.recent_errors.map((err, i) => (
                      <tr key={i} className="border-b border-slate-100">
                        <td className="py-1" style={{ color: "var(--text-tertiary)" }}>
                          {err.recorded_at ? new Date(err.recorded_at as string).toLocaleString("ko-KR") : "-"}
                        </td>
                        <td className="py-1 font-semibold" style={{ color: "var(--text-primary)" }}>
                          {err.agent_id as string}
                        </td>
                        <td className="py-1">
                          <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-600">
                            {err.status as string}
                          </span>
                        </td>
                        <td className="max-w-xs truncate py-1" style={{ color: "var(--text-secondary)" }}>
                          {(err.last_action as string) || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
