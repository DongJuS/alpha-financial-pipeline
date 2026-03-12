/**
 * ui/src/pages/Strategy.tsx — Strategy A/B overview with compact debate logs
 */
import { useState } from "react";
import TournamentTable from "@/components/TournamentTable/TournamentTable";
import { useDebateList, useDebateTranscript, useStrategyBSignals } from "@/hooks/useSignals";
import { signalBadgeClass } from "@/utils/api";

function parseRoundBlocks(content: string | null): Record<number, string> {
  if (!content) return {};
  const entries = content
    .split(/\n\n(?=\[Round\s+\d+\])/)
    .map((chunk) => chunk.trim())
    .filter(Boolean);
  const rounds: Record<number, string> = {};
  entries.forEach((entry) => {
    const matched = entry.match(/^\[Round\s+(\d+)\]\s*([\s\S]*)$/);
    if (!matched) return;
    rounds[Number(matched[1])] = (matched[2] || "").trim();
  });
  return rounds;
}

function extractPolicy(content: string | null): string | null {
  if (!content) return null;
  const matched = content.match(/\[Policy\][\s\S]*$/);
  return matched ? matched[0].trim() : null;
}

function previewText(value: string | null | undefined, maxLen: number = 96): string {
  const source = (value || "").replace(/\s+/g, " ").trim();
  if (!source) return "요약 없음";
  if (source.length <= maxLen) return source;
  return `${source.slice(0, maxLen)}...`;
}

export default function Strategy() {
  const [selectedDebateId, setSelectedDebateId] = useState<number | null>(null);

  const { data: strategyB, isLoading: strategyBLoading } = useStrategyBSignals();
  const { data: debateList, isLoading: debateListLoading } = useDebateList(30);
  const { data: debate, isLoading: debateLoading } = useDebateTranscript(selectedDebateId);

  const proposerByRound = parseRoundBlocks(debate?.proposer_content ?? null);
  const challenger1ByRound = parseRoundBlocks(debate?.challenger1_content ?? null);
  const challenger2ByRound = parseRoundBlocks(debate?.challenger2_content ?? null);
  const synthesizerByRound = parseRoundBlocks(debate?.synthesizer_content ?? null);
  const policyText = extractPolicy(debate?.synthesizer_content ?? null);

  const roundSet = new Set<number>([
    ...Object.keys(proposerByRound).map(Number),
    ...Object.keys(challenger1ByRound).map(Number),
    ...Object.keys(challenger2ByRound).map(Number),
    ...Object.keys(synthesizerByRound).map(Number),
  ]);
  const rounds = [...roundSet].sort((a, b) => a - b);

  return (
    <div className="page-shell">
      <h1 className="section-title">전략</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="space-y-4">
          <div>
            <h2 className="text-base font-bold text-slate-800">Strategy A · Tournament</h2>
            <p className="section-sub mt-1">최근 성과 기반 우승 에이전트를 매 사이클 선택합니다.</p>
          </div>
          <TournamentTable />
        </section>

        <section className="space-y-4">
          <div>
            <h2 className="text-base font-bold text-slate-800">Strategy B · Consensus</h2>
            <p className="section-sub mt-1">토론 로그는 요약 위주로 표시하고, 필요할 때만 펼쳐 확인합니다.</p>
          </div>

          {strategyBLoading ? (
            <div className="card py-10 text-center text-slate-400">Strategy B 시그널 로딩 중</div>
          ) : strategyB?.signals.length ? (
            <div className="space-y-3">
              {strategyB.signals.map((signal) => (
                <button
                  key={`${signal.ticker}-${signal.debate_transcript_id ?? "no-debate"}`}
                  className="card w-full text-left transition-colors hover:border-blue-300"
                  onClick={() => setSelectedDebateId(signal.debate_transcript_id)}
                  disabled={!signal.debate_transcript_id}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-800">{signal.ticker}</p>
                      <p className="mt-1 text-xs text-slate-500">{previewText(signal.reasoning_summary, 92)}</p>
                    </div>
                    <span className={signalBadgeClass(signal.signal)}>{signal.signal}</span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="card py-10 text-center text-slate-400">Strategy B 데이터가 없습니다.</div>
          )}

          <div className="card space-y-2">
            <p className="text-sm font-bold text-slate-800">최근 Debate 이력</p>
            {debateListLoading ? (
              <p className="text-sm text-slate-500">이력 로딩 중...</p>
            ) : debateList?.items.length ? (
              <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
                {debateList.items.map((item) => (
                  <button
                    key={item.id}
                    className={`w-full rounded-2xl border px-3 py-2 text-left transition-colors ${
                      selectedDebateId === item.id
                        ? "border-blue-300 bg-blue-50/60"
                        : "border-slate-200 bg-white hover:border-blue-300"
                    }`}
                    onClick={() => setSelectedDebateId(item.id)}
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold text-slate-800">
                        #{item.id} · {item.ticker}
                      </p>
                      <span className={signalBadgeClass(item.final_signal ?? "HOLD")}>{item.final_signal ?? "HOLD"}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {item.date} · rounds {item.rounds} · conf {item.confidence !== null ? item.confidence.toFixed(3) : "-"} ·
                      consensus {item.consensus_reached ? "yes" : "no"}
                    </p>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">토론 이력이 없습니다.</p>
            )}
          </div>

          {selectedDebateId && (
            <div className="card space-y-3">
              <p className="text-sm font-bold text-slate-800">Debate #{selectedDebateId}</p>
              {debateLoading ? (
                <p className="text-sm text-slate-500">토론 전문 로딩 중...</p>
              ) : debate ? (
                <>
                  <p className="text-xs text-slate-500">
                    {debate.ticker} · rounds {debate.rounds} · final {debate.final_signal ?? "HOLD"} · confidence{" "}
                    {debate.confidence !== null ? debate.confidence.toFixed(3) : "-"} · consensus{" "}
                    {debate.consensus_reached ? "yes" : "no"}
                  </p>
                  {!debate.consensus_reached && debate.no_consensus_reason && (
                    <p className="text-xs font-medium text-amber-700">reason: {debate.no_consensus_reason}</p>
                  )}

                  {rounds.length ? (
                    <div className="space-y-2">
                      {rounds.map((roundNo) => (
                        <details key={roundNo} className="rounded-2xl border border-slate-200 bg-slate-50/50 p-3">
                          <summary className="cursor-pointer text-xs font-semibold text-slate-700">
                            Round {roundNo} 상세 로그
                          </summary>
                          <div className="mt-2 space-y-2">
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-slate-600">Proposer</p>
                              <pre className="log-preview whitespace-pre-wrap">{proposerByRound[roundNo] ?? "-"}</pre>
                            </div>
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-slate-600">Challenger 1</p>
                              <pre className="log-preview whitespace-pre-wrap">{challenger1ByRound[roundNo] ?? "-"}</pre>
                            </div>
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-slate-600">Challenger 2</p>
                              <pre className="log-preview whitespace-pre-wrap">{challenger2ByRound[roundNo] ?? "-"}</pre>
                            </div>
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-slate-600">Synthesizer</p>
                              <pre className="log-preview whitespace-pre-wrap">{synthesizerByRound[roundNo] ?? "-"}</pre>
                            </div>
                          </div>
                        </details>
                      ))}
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <pre className="log-preview whitespace-pre-wrap">{debate.proposer_content ?? "-"}</pre>
                      <pre className="log-preview whitespace-pre-wrap">{debate.challenger1_content ?? "-"}</pre>
                      <pre className="log-preview whitespace-pre-wrap">{debate.challenger2_content ?? "-"}</pre>
                      <pre className="log-preview whitespace-pre-wrap">{debate.synthesizer_content ?? "-"}</pre>
                    </div>
                  )}

                  {policyText && <pre className="log-preview whitespace-pre-wrap">{policyText}</pre>}
                </>
              ) : (
                <p className="text-sm text-slate-500">토론 전문을 불러오지 못했습니다.</p>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
