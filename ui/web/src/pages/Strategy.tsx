import { useMemo, useState } from "react";

import TournamentTable from "@/components/TournamentTable/TournamentTable";
import {
  useCombinedSignals,
  useDebateList,
  useDebateTranscript,
  useStrategyBSignals,
} from "@/hooks/useSignals";
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

  const { data: combined, isLoading: combinedLoading } = useCombinedSignals();
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

  const combinedSignals = combined?.signals ?? [];
  const conflictCount = combinedSignals.filter((item) => item.conflict).length;
  const holdCount = combinedSignals.filter((item) => item.combined_signal === "HOLD").length;

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <span className="eyebrow">Strategy coordination</span>
        <h1 className="mt-4 text-[32px] font-extrabold tracking-[-0.04em]" style={{ color: "var(--text-primary)" }}>
          Strategy A/B 교차 검증
        </h1>
        <p className="mt-3 max-w-[760px] text-sm leading-6 md:text-base" style={{ color: "var(--text-secondary)" }}>
          다양한 관점을 빠르게 탐색하는 Tournament와 깊이 있는 구조화 토론을 수행하는 Consensus를 함께 운용해,
          하나의 전략만 믿는 위험을 줄였습니다.
        </p>

        <div className="mt-5 flex flex-wrap gap-2">
          <span className="chip">충돌 시 기본값은 HOLD</span>
          <span className="chip">Blend ratio {Math.round((combined?.blend_ratio ?? 0) * 100)}%</span>
          <span className="chip">Debate transcript 90일 보관</span>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article className="card">
          <p className="kpi-label">Blend ratio</p>
          <p className="number-lg mt-2">{combinedLoading ? "—" : `${Math.round((combined?.blend_ratio ?? 0) * 100)}%`}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            Strategy B 기준 비중
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">Combined signals</p>
          <p className="number-lg mt-2">{combinedLoading ? "—" : combinedSignals.length.toLocaleString()}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            오늘 교차 검증된 종목
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">Conflict HOLD</p>
          <p className="number-lg mt-2">{combinedLoading ? "—" : conflictCount.toLocaleString()}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            A/B 신호 충돌로 멈춘 케이스
          </p>
        </article>
        <article className="card">
          <p className="kpi-label">Total HOLD</p>
          <p className="number-lg mt-2">{combinedLoading ? "—" : holdCount.toLocaleString()}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            최종 판단이 HOLD인 수
          </p>
        </article>
      </section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.05fr_1fr]">
        <section className="space-y-5">
          <div className="card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  교차 검증 보드
                </h2>
                <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                  Tournament와 Consensus의 결론을 한 번에 비교합니다.
                </p>
              </div>
              <span className="chip">Conflict to HOLD</span>
            </div>

            {combinedLoading ? (
              <div className="mt-4 space-y-2">
                {[...Array(5)].map((_, idx) => (
                  <div key={idx} className="h-16 skeleton" />
                ))}
              </div>
            ) : combinedSignals.length ? (
              <div className="mt-4 space-y-3">
                {combinedSignals.slice(0, 8).map((signal) => (
                  <div key={signal.ticker} className="inner-card">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-bold tracking-[-0.02em]" style={{ color: "var(--text-primary)" }}>
                            {signal.ticker}
                          </p>
                          <span className={signalBadgeClass(signal.combined_signal)}>{signal.combined_signal}</span>
                          {signal.conflict && <span className="chip">signal conflict</span>}
                        </div>
                        <p className="mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                          A: {signal.strategy_a_signal ?? "-"} / B: {signal.strategy_b_signal ?? "-"} / confidence{" "}
                          {signal.combined_confidence != null ? signal.combined_confidence.toFixed(3) : "-"}
                        </p>
                      </div>
                      <button
                        className="btn-secondary"
                        onClick={() => {
                          const matched = strategyB?.signals.find((item) => item.ticker === signal.ticker);
                          if (matched?.debate_transcript_id) {
                            setSelectedDebateId(matched.debate_transcript_id);
                          }
                        }}
                      >
                        근거 보기
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm" style={{ color: "var(--text-secondary)" }}>
                현재 교차 검증 데이터가 없습니다.
              </p>
            )}
          </div>

          <TournamentTable />

          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                최근 Debate 이력
              </h2>
              <span className="chip">최근 30개</span>
            </div>

            {debateListLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, idx) => (
                  <div key={idx} className="h-14 skeleton" />
                ))}
              </div>
            ) : debateList?.items.length ? (
              <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                {debateList.items.map((item) => (
                  <button
                    key={item.id}
                    className="w-full rounded-[22px] px-4 py-3 text-left transition-all"
                    style={{
                      background:
                        selectedDebateId === item.id ? "rgba(31, 99, 247, 0.08)" : "rgba(255, 255, 255, 0.78)",
                      border:
                        selectedDebateId === item.id
                          ? "1px solid rgba(31, 99, 247, 0.22)"
                          : "1px solid var(--line-soft)",
                    }}
                    onClick={() => setSelectedDebateId(item.id)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                        #{item.id} · {item.ticker}
                      </p>
                      <span className={signalBadgeClass(item.final_signal ?? "HOLD")}>{item.final_signal ?? "HOLD"}</span>
                    </div>
                    <p className="mt-2 text-xs leading-5" style={{ color: "var(--text-secondary)" }}>
                      {item.date} · rounds {item.rounds} · conf{" "}
                      {item.confidence !== null ? item.confidence.toFixed(3) : "-"} · consensus{" "}
                      {item.consensus_reached ? "yes" : "no"}
                    </p>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                토론 이력이 없습니다.
              </p>
            )}
          </div>
        </section>

        <section className="space-y-5">
          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                Strategy B · Consensus
              </h2>
              <span className="chip">요약 보기</span>
            </div>

            {strategyBLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, idx) => (
                  <div key={idx} className="h-14 skeleton" />
                ))}
              </div>
            ) : strategyB?.signals.length ? (
              <div className="space-y-2">
                {strategyB.signals.map((signal) => (
                  <button
                    key={`${signal.ticker}-${signal.debate_transcript_id ?? "no-debate"}`}
                    className="w-full rounded-[22px] px-4 py-3 text-left transition-all disabled:opacity-50"
                    style={{
                      background: "rgba(255, 255, 255, 0.78)",
                      border: "1px solid var(--line-soft)",
                    }}
                    onClick={() => setSelectedDebateId(signal.debate_transcript_id)}
                    disabled={!signal.debate_transcript_id}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                          {signal.ticker}
                        </p>
                        <p className="mt-1 text-xs leading-5" style={{ color: "var(--text-secondary)" }}>
                          {previewText(signal.reasoning_summary)}
                        </p>
                      </div>
                      <span className={signalBadgeClass(signal.signal)}>{signal.signal}</span>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <p className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
                Strategy B 데이터가 없습니다.
              </p>
            )}
          </div>

          {selectedDebateId && (
            <div className="card space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                  Debate #{selectedDebateId}
                </p>
                {debate?.final_signal && <span className={signalBadgeClass(debate.final_signal)}>{debate.final_signal}</span>}
              </div>

              {debateLoading ? (
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  토론 전문 로딩 중...
                </p>
              ) : debate ? (
                <>
                  <p className="inner-card text-xs leading-6" style={{ color: "var(--text-secondary)" }}>
                    {debate.ticker} · rounds {debate.rounds} · confidence{" "}
                    {debate.confidence !== null ? debate.confidence.toFixed(3) : "-"} · consensus{" "}
                    {debate.consensus_reached ? "yes" : "no"}
                  </p>

                  {!debate.consensus_reached && debate.no_consensus_reason && (
                    <p
                      className="rounded-[20px] px-4 py-3 text-xs font-medium"
                      style={{ background: "var(--warning-bg)", color: "var(--warning)" }}
                    >
                      no consensus: {debate.no_consensus_reason}
                    </p>
                  )}

                  {rounds.length ? (
                    <div className="space-y-3">
                      {rounds.map((roundNo) => (
                        <details
                          key={roundNo}
                          className="rounded-[22px] border border-[var(--line-soft)] bg-white/72 p-4"
                        >
                          <summary className="cursor-pointer text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
                            Round {roundNo} 상세 로그
                          </summary>
                          <div className="mt-3 space-y-3">
                            {[
                              { label: "Proposer", data: proposerByRound[roundNo] },
                              { label: "Challenger 1", data: challenger1ByRound[roundNo] },
                              { label: "Challenger 2", data: challenger2ByRound[roundNo] },
                              { label: "Synthesizer", data: synthesizerByRound[roundNo] },
                            ].map(({ label, data }) => (
                              <div key={label}>
                                <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
                                  {label}
                                </p>
                                <pre className="log-preview whitespace-pre-wrap">{data ?? "-"}</pre>
                              </div>
                            ))}
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
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  토론 전문을 불러오지 못했습니다.
                </p>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
