/**
 * 에이전트 헬스 상태를 실시간으로 표시하는 컴포넌트 — Dark theme
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

function activityBadgeStyle(state: string): { background: string; color: string } {
  if (state === "investing") return { background: "var(--brand-50)", color: "var(--brand-500)" };
  if (["collecting", "analyzing", "orchestrating", "notifying", "active"].includes(state))
    return { background: "var(--profit-bg)", color: "var(--profit)" };
  if (["error", "offline"].includes(state)) return { background: "var(--loss-bg)", color: "var(--loss)" };
  if (state === "degraded") return { background: "var(--warning-bg)", color: "var(--warning)" };
  if (state === "scheduled_wait") return { background: "var(--brand-50)", color: "var(--brand-500)" };
  if (state === "on_demand") return { background: "rgba(139,92,246,0.12)", color: "#8B5CF6" };
  if (state === "idle") return { background: "rgba(139,149,161,0.12)", color: "var(--text-secondary)" };
  return { background: "var(--profit-bg)", color: "var(--profit)" };
}

export default function AgentStatusBar() {
  const { data: agents, isLoading } = useAgentStatus();

  if (isLoading) {
    return (
      <div className="card">
        <div className="h-4 w-48 skeleton" />
      </div>
    );
  }

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>에이전트 상태</h3>
        <span className="text-[11px] font-semibold" style={{ color: "var(--text-tertiary)" }}>실시간 모니터링</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {agents?.map((agent) => (
          <div
            key={agent.agent_id}
            className="rounded-xl px-3 py-3"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--line-soft)" }}
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
              <span className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                {AGENT_LABELS[agent.agent_id] ?? agent.agent_id}
              </span>
            </div>
            <div className="mt-2">
              <span
                className="inline-flex items-center rounded-lg px-2.5 py-1 text-[11px] font-semibold"
                style={activityBadgeStyle(agent.activity_state)}
              >
                {agent.activity_label}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
