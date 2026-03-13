/**
 * ui/src/pages/Strategy.tsx
 * Strategy A/B overview with cleaner Toss-like information hierarchy.
 */
import { useMemo, useState } from "react";

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

function previewText(value: string | null | undefined, maxLen: number = 90): string {
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

  const rounds = useMemo(() => {
    const roundSet = new Set<number>([
      ...Object.keys(proposerByRound).map(Number),
      ...Object.keys(challenger1ByRound).map(Number),
      ...Object.keys(challenger2ByRound).map(Number),
      ...Object.keys(synthesizerByRound).map(Number),
    ]);
    return [...roundSet].sort((a, b) => a - b);
  }, [challenger1ByRound, challenger2ByRound, proposerByRound, synthesizerByRound]);

  return (
    <div className="page-shell space-y-4">
      <section className="rounded-[30px] bg-[#F2F4F6] px-6 py-6 shadow-[0_12px_28px_rgba(25,31,40,0.06)] md:px-7">
        <p className="text-[13px] font-semibold text-[#8B95A1]">투자 Agent</p>
        <h1 className="mt-1 text-[32px] font-extrabold tracking-[-0.03em] text-[#191F28]">전략 센터</h1>
        <p className="mt-2 text-sm text-[#8B95A1]">토너먼트 승자와 컨센서스 토론 결과를 같은 화면에서 빠르게 판단합니다.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#191F28]">
            Strategy B 시그널 {(strategyB?.signals.length ?? 0).toLocaleString()}건
          </span>
          <span className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#191F28]">
            Debate 로그 {(debateList?.items.length ?? 0).toLocaleString()}건
          </span>
          <span className="rounded-full bg-[#EAF1FF] px-3 py-1.5 text-xs font-semibold text-[#0019FF]">최종 판단 기록 중심</span>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.05fr_1fr]">
        <section className="space-y-4">
          <TournamentTable />

          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-[#191F28]">최근 Debate 이력</h2>
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-[#8B95A1]">최근 30개</span>
            </div>

            {debateListLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, idx) => (
                  <div key={idx} className="h-14 rounded-2xl bg-white animate-pulse" />
                ))}
              </div>
            ) : debateList?.items.length ? (
              <div className="max-h-[390px] space-y-2 overflow-y-auto pr-1">
                {debateList.items.map((item) => (
                  <button
                    key={item.id}
                    className={`w-full rounded-2xl px-3 py-2.5 text-left transition-transform hover:scale-[1.01] ${
                      selectedDebateId === item.id ? "bg-[#EAF1FF]" : "bg-white"
                    }`}
                    onClick={() => setSelectedDebateId(item.id)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold text-[#191F28]">
                        #{item.id} · {item.ticker}
                      </p>
                      <span className={signalBadgeClass(item.final_signal ?? "HOLD")}>{item.final_signal ?? "HOLD"}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-[#8B95A1]">
                      {item.date} · rounds {item.rounds} · conf {item.confidence !== null ? item.confidence.toFixed(3) : "-"} ·
                      consensus {item.consensus_reached ? "yes" : "no"}
                    </p>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#8B95A1]">토론 이력이 없습니다.</p>
            )}
          </div>
        </section>

        <section className="space-y-4">
          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-[#191F28]">Strategy B · Consensus</h2>
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-[#8B95A1]">요약 보기</span>
            </div>

            {strategyBLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, idx) => (
                  <div key={idx} className="h-14 rounded-2xl bg-white animate-pulse" />
                ))}
              </div>
            ) : strategyB?.signals.length ? (
              <div className="space-y-2">
                {strategyB.signals.map((signal) => (
                  <button
                    key={`${signal.ticker}-${signal.debate_transcript_id ?? "no-debate"}`}
                    className="w-full rounded-2xl bg-white px-3 py-2.5 text-left transition-transform hover:scale-[1.01] disabled:opacity-60"
                    onClick={() => setSelectedDebateId(signal.debate_transcript_id)}
                    disabled={!signal.debate_transcript_id}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-[#191F28]">{signal.ticker}</p>
                        <p className="mt-1 text-xs text-[#8B95A1]">{previewText(signal.reasoning_summary)}</p>
                      </div>
                      <span className={signalBadgeClass(signal.signal)}>{signal.signal}</span>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <p className="py-8 text-center text-sm text-[#8B95A1]">Strategy B 데이터가 없습니다.</p>
            )}
          </div>

          {selectedDebateId && (
            <div className="card space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-bold text-[#191F28]">Debate #{selectedDebateId}</p>
                {debate?.final_signal && <span className={signalBadgeClass(debate.final_signal)}>{debate.final_signal}</span>}
              </div>

              {debateLoading ? (
                <p className="text-sm text-[#8B95A1]">토론 전문 로딩 중...</p>
              ) : debate ? (
                <>
                  <p className="rounded-2xl bg-white px-3 py-2 text-xs text-[#8B95A1]">
                    {debate.ticker} · rounds {debate.rounds} · confidence {debate.confidence !== null ? debate.confidence.toFixed(3) : "-"} ·
                    consensus {debate.consensus_reached ? "yes" : "no"}
                  </p>

                  {!debate.consensus_reached && debate.no_consensus_reason && (
                    <p className="rounded-2xl bg-[#FFF4E6] px-3 py-2 text-xs font-medium text-[#B35C00]">
                      no consensus: {debate.no_consensus_reason}
                    </p>
                  )}

                  {rounds.length ? (
                    <div className="space-y-2">
                      {rounds.map((roundNo) => (
                        <details key={roundNo} className="rounded-2xl bg-white p-3">
                          <summary className="cursor-pointer text-xs font-semibold text-[#4E5968]">Round {roundNo} 상세 로그</summary>
                          <div className="mt-2 space-y-2">
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-[#8B95A1]">Proposer</p>
                              <pre className="log-preview whitespace-pre-wrap">{proposerByRound[roundNo] ?? "-"}</pre>
                            </div>
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-[#8B95A1]">Challenger 1</p>
                              <pre className="log-preview whitespace-pre-wrap">{challenger1ByRound[roundNo] ?? "-"}</pre>
                            </div>
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-[#8B95A1]">Challenger 2</p>
                              <pre className="log-preview whitespace-pre-wrap">{challenger2ByRound[roundNo] ?? "-"}</pre>
                            </div>
                            <div>
                              <p className="mb-1 text-[11px] font-semibold text-[#8B95A1]">Synthesizer</p>
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
                <p className="text-sm text-[#8B95A1]">토론 전문을 불러오지 못했습니다.</p>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
