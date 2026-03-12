/**
 * 에이전트 헬스 상태를 실시간으로 표시하는 컴포넌트
 */
import { useAgentStatus } from "@/hooks/useAgentStatus";

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
  fast_flow_agent: "빠른 흐름",
  slow_meticulous_agent: "꼼꼼 검증",
};

function activityBadgeClass(state: string): string {
  if (state === "investing") {
    return "bg-blue-100 text-blue-700";
  }
  if (state === "collecting" || state === "analyzing" || state === "orchestrating" || state === "notifying") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (state === "error" || state === "offline") {
    return "bg-red-100 text-red-700";
  }
  if (state === "degraded") {
    return "bg-yellow-100 text-yellow-700";
  }
  if (state === "scheduled_wait") {
    return "bg-sky-100 text-sky-700";
  }
  if (state === "on_demand") {
    return "bg-indigo-100 text-indigo-700";
  }
  if (state === "idle") {
    return "bg-gray-100 text-gray-600";
  }
  return "bg-green-100 text-green-700";
}

export default function AgentStatusBar() {
  const { data: agents, isLoading } = useAgentStatus();

  if (isLoading) {
    return (
      <div className="card animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-48" />
      </div>
    );
  }

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-800">에이전트 상태</h3>
        <span className="text-[11px] font-semibold text-slate-500">실시간 모니터링</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {agents?.map((agent) => (
          <div
            key={agent.agent_id}
            className="rounded-2xl border border-slate-100 bg-white/75 px-3 py-3 shadow-[0_6px_14px_rgba(15,23,42,0.06)]"
            title={agent.last_action ?? ""}
          >
            <div className="flex items-center gap-2">
              <span
                className={
                  agent.status === "healthy"
                    ? "dot-healthy"
                    : agent.status === "degraded"
                    ? "dot-degraded"
                    : "dot-dead"
                }
              />
              <span className="text-xs font-semibold text-slate-700">
                {AGENT_LABELS[agent.agent_id] ?? agent.agent_id}
              </span>
            </div>
            <div className="mt-2">
              <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ${activityBadgeClass(agent.activity_state)}`}>
                {agent.activity_label}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
