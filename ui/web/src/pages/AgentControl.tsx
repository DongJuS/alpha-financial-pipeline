import { useState } from "react";
import {
  useAgentStatus,
  useAgentLogs,
  useRestartAgent,
  usePauseAgent,
  useResumeAgent,
  type AgentStatus,
} from "@/hooks/useAgentStatus";

function statusColor(status: string) {
  if (status === "healthy") return { bg: "var(--green-bg)", color: "var(--green)" };
  if (status === "degraded") return { bg: "#fff3cd", color: "#856404" };
  return { bg: "#f8d7da", color: "#721c24" };
}

function StatusBadge({ status }: { status: string }) {
  const s = statusColor(status);
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold"
      style={{ background: s.bg, color: s.color }}
    >
      {status}
    </span>
  );
}

function AgentCard({
  agent,
  isSelected,
  onSelect,
}: {
  agent: AgentStatus;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`card text-left transition-all ${isSelected ? "ring-2 ring-blue-400" : ""}`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          {agent.agent_id}
        </h3>
        <StatusBadge status={agent.status} />
      </div>
      <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
        {agent.activity_label}
      </p>
      {agent.last_action && (
        <p className="mt-1 truncate text-xs" style={{ color: "var(--text-tertiary)" }}>
          {agent.last_action}
        </p>
      )}
      <div className="mt-2 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${agent.is_alive ? "bg-green-400" : "bg-red-400"}`} />
        <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
          {agent.is_alive ? "연결됨" : "연결 끊김"}
        </span>
        {agent.updated_at && (
          <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
            · {new Date(agent.updated_at).toLocaleString("ko-KR")}
          </span>
        )}
      </div>
    </button>
  );
}

function AgentLogPanel({ agentId }: { agentId: string }) {
  const { data: logData, isLoading } = useAgentLogs(agentId);
  const restart = useRestartAgent();
  const pause = usePauseAgent();
  const resume = useResumeAgent();

  const logs = (logData as any)?.logs ?? (Array.isArray(logData) ? logData : []);

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          {agentId} 로그
        </h3>
        <div className="flex gap-2">
          <button
            className="rounded-lg bg-green-50 px-3 py-1.5 text-xs font-semibold text-green-700 hover:bg-green-100"
            onClick={() => resume.mutate(agentId)}
            disabled={resume.isPending}
          >
            재개
          </button>
          <button
            className="rounded-lg bg-yellow-50 px-3 py-1.5 text-xs font-semibold text-yellow-700 hover:bg-yellow-100"
            onClick={() => pause.mutate(agentId)}
            disabled={pause.isPending}
          >
            일시정지
          </button>
          <button
            className="rounded-lg bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-100"
            onClick={() => restart.mutate(agentId)}
            disabled={restart.isPending}
          >
            재시작
          </button>
        </div>
      </div>
      {isLoading ? (
        <div className="mt-3 h-20 skeleton" />
      ) : (
        <div className="mt-3 max-h-80 overflow-y-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b" style={{ color: "var(--text-secondary)" }}>
                <th className="py-1.5 text-left font-medium">시각</th>
                <th className="py-1.5 text-left font-medium">상태</th>
                <th className="py-1.5 text-left font-medium">마지막 동작</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log: any, i: number) => (
                <tr key={i} className="border-b border-slate-100">
                  <td className="py-1.5" style={{ color: "var(--text-tertiary)" }}>
                    {log.recorded_at ? new Date(log.recorded_at).toLocaleString("ko-KR") : "-"}
                  </td>
                  <td className="py-1.5">
                    <StatusBadge status={log.status || "unknown"} />
                  </td>
                  <td className="max-w-xs truncate py-1.5" style={{ color: "var(--text-secondary)" }}>
                    {log.last_action || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {logs.length === 0 && (
            <p className="py-4 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>
              로그가 없습니다.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function AgentControl() {
  const { data: agents, isLoading } = useAgentStatus();
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  return (
    <div className="page-shell">
      <section className="card">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>에이전트 제어</h2>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>실시간 에이전트 상태 모니터링 및 제어</p>
          </div>
          <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>30초마다 자동 갱신</span>
        </div>
      </section>

      {isLoading ? (
        <div className="grid gap-3 md:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-28 skeleton" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-3">
          {agents?.map((agent) => (
            <AgentCard
              key={agent.agent_id}
              agent={agent}
              isSelected={selectedAgent === agent.agent_id}
              onSelect={() => setSelectedAgent(selectedAgent === agent.agent_id ? null : agent.agent_id)}
            />
          ))}
        </div>
      )}

      {selectedAgent && <AgentLogPanel agentId={selectedAgent} />}
    </div>
  );
}
