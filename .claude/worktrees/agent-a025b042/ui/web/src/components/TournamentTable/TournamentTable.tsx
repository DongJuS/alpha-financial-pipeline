/**
 * Strategy A 토너먼트 순위표 컴포넌트 — Dark theme
 */
import { useTournament } from "@/hooks/useSignals";

const LLM_BADGES: Record<string, string> = {
  "claude-sonnet-4-6": "Claude",
  "gpt-4o": "GPT",
  "gemini-1.5-pro": "Gemini",
};

export default function TournamentTable() {
  const { data, isLoading } = useTournament();

  if (isLoading) {
    return (
      <div className="card space-y-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-16 skeleton" />
        ))}
      </div>
    );
  }

  return (
    <div className="card space-y-3">
      <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
        Strategy A 토너먼트 · 최근 {data?.period_days}일 누적 정확도
      </h3>
      <div className="space-y-2">
        {data?.rankings.map((rank, idx) => {
          const accuracy = rank.rolling_accuracy != null ? `${(rank.rolling_accuracy * 100).toFixed(1)}%` : "—";
          return (
            <div
              key={rank.agent_id}
              className="rounded-xl px-4 py-3"
              style={{
                background: "var(--bg-elevated)",
                border: rank.is_current_winner
                  ? "1px solid rgba(49,130,246,0.3)"
                  : "1px solid var(--line-soft)",
              }}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span
                    className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-xs font-bold"
                    style={{ background: "var(--bg-input)", color: "var(--text-secondary)" }}
                  >
                    {idx + 1}
                  </span>
                  <div>
                    <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                      {rank.is_current_winner ? "★ " : ""}
                      {rank.persona}
                    </p>
                    <p className="mt-0.5 text-[11px]" style={{ color: "var(--text-secondary)" }}>
                      {rank.agent_id}
                    </p>
                  </div>
                </div>

                <div className="text-right">
                  <span className="chip">
                    {LLM_BADGES[rank.llm_model] ?? "Model"}
                  </span>
                  <p className="mt-1 text-sm font-bold" style={{ color: "var(--text-primary)" }}>
                    {accuracy}
                  </p>
                  <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                    {rank.correct}/{rank.total}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
