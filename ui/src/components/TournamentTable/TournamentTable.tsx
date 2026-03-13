/**
 * Strategy A 토너먼트 순위표 컴포넌트
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
          <div key={i} className="h-16 rounded-2xl bg-white animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="card space-y-3">
      <h3 className="text-sm font-bold text-[#191F28]">
        Strategy A 토너먼트 · 최근 {data?.period_days}일 누적 정확도
      </h3>
      <div className="space-y-2">
        {data?.rankings.map((rank, idx) => {
          const accuracy = rank.rolling_accuracy != null ? `${(rank.rolling_accuracy * 100).toFixed(1)}%` : "—";
          return (
            <div
              key={rank.agent_id}
              className={`rounded-2xl bg-white px-4 py-3 shadow-[0_6px_16px_rgba(25,31,40,0.05)] ${
                rank.is_current_winner ? "ring-2 ring-[#0019FF]/20" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[#F2F4F6] text-xs font-bold text-[#8B95A1]">
                    {idx + 1}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-[#191F28]">
                      {rank.is_current_winner ? "★ " : ""}
                      {rank.persona}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[#8B95A1]">{rank.agent_id}</p>
                  </div>
                </div>

                <div className="text-right">
                  <span className="rounded-full bg-[#EAF1FF] px-2.5 py-1 text-[11px] font-semibold text-[#0019FF]">
                    {LLM_BADGES[rank.llm_model] ?? "Model"}
                  </span>
                  <p className="mt-1 text-sm font-bold text-[#191F28]">{accuracy}</p>
                  <p className="text-[11px] text-[#8B95A1]">
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
