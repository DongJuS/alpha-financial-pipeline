/**
 * ui/src/pages/RLTrading.tsx
 * RL Trading 대시보드 — 정책 관리, 실험, 섀도우 추론, 승격
 */
import { useState, useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  usePolicies,
  useActivePolicies,
  useExperiments,
  useEvaluations,
  useShadowPolicies,
  useShadowPerformance,
  useActivatePolicy,
  useTrainingJobs,
  useStartTrainingJob,
  useDeleteTrainingJob,
  useRunWalkForward,
  usePromoteShadowToPaper,
  usePromotePaperToReal,
  usePolicyMode,
  useRLTickers,
  useAddRLTickers,
  useRemoveRLTicker,
  useMarketTickers,
  type RLPolicy,
  type RLTickerInfo,
  type TrainingJob,
} from "@/hooks/useRL";
import { api, formatPct } from "@/utils/api";

/** 특정 종목의 시장 데이터를 FDR로 즉시 수집 → DB 저장 */
function useCollectMarketData() {
  return useMutation({
    mutationFn: async (tickers: string[]) => {
      const { data } = await api.post(
        "/market/collect",
        { tickers, days: 150 },
        { timeout: 120_000 },
      );
      return data as { saved: number; tickers_collected: string[]; tickers_failed: string[]; message: string };
    },
  });
}

/* ── 탭 정의 ───────────────────────────────────────────────────────────── */
type Tab = "tickers" | "policies" | "experiments" | "shadow" | "promotion";
const TABS: { key: Tab; label: string; desc: string }[] = [
  { key: "tickers", label: "종목 관리", desc: "RL 대상 종목 추가/제거" },
  { key: "policies", label: "정책 관리", desc: "활성 정책 및 평가" },
  { key: "experiments", label: "학습 실험", desc: "트레이닝 잡 실행" },
  { key: "shadow", label: "섀도우 추론", desc: "가상 시그널 성과" },
  { key: "promotion", label: "승격 게이트", desc: "Shadow → Paper → Real" },
];

/* ── 모드 배지 ─────────────────────────────────────────────────────────── */
function ModeBadge({ mode }: { mode: string }) {
  const m = mode ?? "shadow";
  const style =
    m === "real"
      ? { background: "var(--red-bg)", color: "var(--red)" }
      : m === "paper"
        ? { background: "var(--yellow-bg)", color: "var(--yellow)" }
        : { background: "var(--blue-bg)", color: "var(--blue)" };
  return (
    <span className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold" style={style}>
      {(m ?? "unknown").toUpperCase()}
    </span>
  );
}

/* ── 종목 관리 탭 ──────────────────────────────────────────────────────── */
function TickersTab() {
  const { data: rlTickers, isLoading: rlLoading } = useRLTickers();
  const { data: allTickers = [], isLoading: allLoading } = useMarketTickers(true);
  const addTickers = useAddRLTickers();
  const removeTicker = useRemoveRLTicker();
  const [search, setSearch] = useState("");
  const [market, setMarket] = useState<string>("ALL");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const rlSet = useMemo(() => new Set((rlTickers ?? []).map((t) => t.ticker)), [rlTickers]);
  const rlMap = useMemo(() => {
    const m = new Map<string, RLTickerInfo>();
    for (const t of rlTickers ?? []) m.set(t.ticker, t);
    return m;
  }, [rlTickers]);

  const markets = useMemo(() => [...new Set(allTickers.map((t) => t.market))].sort(), [allTickers]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return allTickers
      .filter((t) => market === "ALL" || t.market === market)
      .filter((t) => !q || t.ticker.includes(q) || (t.name ?? "").toLowerCase().includes(q));
  }, [allTickers, market, search]);

  const handleToggle = (instrumentId: string) => {
    if (rlSet.has(instrumentId)) return; // 이미 등록된 종목은 체크박스가 아닌 제거 버튼 사용
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(instrumentId)) next.delete(instrumentId);
      else next.add(instrumentId);
      return next;
    });
  };

  const handleAddSelected = () => {
    const tickers = [...selected];
    if (tickers.length === 0) return;
    addTickers.mutate({ tickers }, { onSuccess: () => setSelected(new Set()) });
  };

  const isLoading = rlLoading || allLoading;

  return (
    <div className="space-y-4">
      {/* 상단 요약 + 액션 */}
      <div className="card">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
              RL 학습 종목 선택
            </h3>
            <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
              스크롤하여 종목을 찾고 체크하세요. 등록된 종목 {rlSet.size}개 / 전체 {allTickers.length}개
            </p>
          </div>
          {selected.size > 0 && (
            <button
              onClick={handleAddSelected}
              disabled={addTickers.isPending}
              className="btn-primary px-4 py-2 text-sm"
              style={{ background: "linear-gradient(135deg, var(--brand-500), #4b9dff)" }}
            >
              {addTickers.isPending ? "추가 중..." : `선택한 ${selected.size}개 추가`}
            </button>
          )}
        </div>
        {addTickers.data && addTickers.data.added.length > 0 && (
          <p className="mt-2 text-xs font-semibold" style={{ color: "var(--green)" }}>
            {addTickers.data.added.join(", ")} 추가 완료
          </p>
        )}
      </div>

      {/* 검색 + 마켓 필터 */}
      <div className="card" style={{ paddingBottom: 0 }}>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="종목명 또는 코드 검색..."
            className="flex-1 min-w-[200px] rounded-xl border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--bg-secondary)", color: "var(--text-primary)" }}
          />
          <div className="flex gap-1.5">
            {["ALL", ...markets].map((m) => (
              <button
                key={m}
                onClick={() => setMarket(m)}
                className="rounded-full px-3 py-1 text-xs font-semibold transition-colors"
                style={{
                  background: market === m ? "var(--brand-500)" : "var(--bg-secondary)",
                  color: market === m ? "white" : "var(--text-secondary)",
                }}
              >
                {m === "ALL" ? `전체 (${allTickers.length})` : `${m} (${allTickers.filter((t) => t.market === m).length})`}
              </button>
            ))}
          </div>
        </div>

        {/* 스크롤 리스트 */}
        <div
          className="mt-3 overflow-y-auto border-t"
          style={{ maxHeight: "55vh", borderColor: "var(--border)" }}
        >
          {isLoading && <div className="h-40 skeleton" />}
          {!isLoading && filtered.length === 0 && (
            <p className="py-8 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>
              검색 결과가 없습니다.
            </p>
          )}
          {filtered.map((t) => {
            const instrumentId = t.ticker; // instrument_id는 ticker 필드에 "005930.KS" 형태로 옴
            const isRL = rlSet.has(instrumentId);
            const isChecked = isRL || selected.has(instrumentId);
            const rlInfo = rlMap.get(instrumentId);

            return (
              <div
                key={instrumentId}
                onClick={() => handleToggle(instrumentId)}
                className="flex items-center gap-3 px-3 py-2.5 transition-colors"
                style={{
                  borderBottom: "1px solid var(--border)",
                  background: isRL ? "var(--green-bg)" : selected.has(instrumentId) ? "var(--blue-bg)" : "transparent",
                  cursor: isRL ? "default" : "pointer",
                }}
              >
                {/* 체크박스 */}
                <div
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 text-xs transition-colors"
                  style={{
                    borderColor: isChecked ? "var(--brand-500)" : "var(--border)",
                    background: isChecked ? "var(--brand-500)" : "transparent",
                    color: isChecked ? "white" : "transparent",
                  }}
                >
                  {isChecked && "✓"}
                </div>

                {/* 종목 정보 */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-sm truncate" style={{ color: "var(--text-primary)" }}>
                      {t.name || instrumentId}
                    </span>
                    <span className="font-mono text-xs shrink-0" style={{ color: "var(--text-tertiary)" }}>
                      {t.ticker}
                    </span>
                  </div>
                </div>

                {/* 마켓 배지 */}
                <span
                  className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold"
                  style={{
                    background: t.market === "KOSPI" ? "var(--blue-bg)" : "var(--purple-bg)",
                    color: t.market === "KOSPI" ? "var(--blue)" : "var(--purple)",
                  }}
                >
                  {t.market}
                </span>

                {/* RL 상태 */}
                {isRL && (
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                      style={{
                        background: rlInfo?.has_policy ? "var(--green-bg)" : "var(--bg-secondary)",
                        color: rlInfo?.has_policy ? "var(--green)" : "var(--text-secondary)",
                      }}
                    >
                      {rlInfo?.has_policy ? "학습됨" : "미학습"}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`${instrumentId}을(를) RL 대상에서 제거하시겠습니까?`))
                          removeTicker.mutate(instrumentId);
                      }}
                      disabled={removeTicker.isPending}
                      className="rounded-lg px-2 py-1 text-[11px] font-semibold transition-colors hover:bg-red-50"
                      style={{ color: "var(--red)" }}
                    >
                      제거
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* 하단 요약 */}
        <div
          className="sticky bottom-0 flex items-center justify-between py-3 text-xs font-semibold"
          style={{ color: "var(--text-secondary)", background: "var(--bg-card)" }}
        >
          <span>검색 결과 {filtered.length}개</span>
          {selected.size > 0 && (
            <button
              onClick={() => setSelected(new Set())}
              className="text-xs"
              style={{ color: "var(--text-tertiary)" }}
            >
              선택 초기화
            </button>
          )}
        </div>
      </div>

      {removeTicker.data && (
        <p className="text-xs font-semibold" style={{ color: "var(--red)" }}>
          {removeTicker.data.removed} 제거 완료 (남은 종목: {removeTicker.data.total})
        </p>
      )}
    </div>
  );
}

/* ── 정책 관리 탭 ──────────────────────────────────────────────────────── */
function PoliciesTab() {
  const { data: policies, isLoading } = usePolicies();
  const { data: activePolicies } = useActivePolicies();
  const { data: evaluations } = useEvaluations();
  const activatePolicy = useActivatePolicy();

  if (isLoading) return <div className="card"><div className="h-40 skeleton" /></div>;

  const items = policies ?? [];
  const activeCount = activePolicies?.length ?? 0;

  return (
    <div className="space-y-4">
      {/* KPI */}
      <div className="grid gap-3 md:grid-cols-4">
        <div className="card text-center">
          <p className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>전체 정책</p>
          <p className="mt-1 text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{items.length}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>활성 정책</p>
          <p className="mt-1 text-2xl font-bold" style={{ color: "var(--green)" }}>{activeCount}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>Walk-Forward 통과</p>
          <p className="mt-1 text-2xl font-bold" style={{ color: "var(--brand-500)" }}>
            {items.filter((p) => p.walk_forward_passed).length}
          </p>
        </div>
        <div className="card text-center">
          <p className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>평가 기록</p>
          <p className="mt-1 text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
            {evaluations?.length ?? 0}
          </p>
        </div>
      </div>

      {/* 정책 테이블 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>정책 목록</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>종목</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>버전</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>알고리즘</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>모드</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>초과수익</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>Sharpe</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>승률</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>WF</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>활성</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <PolicyRow
                  key={String(p.id)}
                  policy={p}
                  onActivate={() => activatePolicy.mutate({ policyId: p.id, ticker: p.ticker })}
                />
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10} className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
                    등록된 정책이 없습니다. 학습 실험 탭에서 트레이닝을 시작하세요.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function PolicyRow({ policy: p, onActivate }: { policy: RLPolicy; onActivate: () => void }) {
  return (
    <tr className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
      <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>{p.ticker}</td>
      <td className="py-2" style={{ color: "var(--text-secondary)" }}>{p.version}</td>
      <td className="py-2" style={{ color: "var(--text-secondary)" }}>{p.algorithm}</td>
      <td className="py-2"><ModeBadge mode={p.mode} /></td>
      <td className="py-2 text-right font-mono text-xs" style={{ color: (p.excess_return ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
        {p.excess_return != null ? formatPct(p.excess_return) : "—"}
      </td>
      <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
        {p.sharpe_ratio?.toFixed(2) ?? "—"}
      </td>
      <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
        {p.win_rate != null ? `${(p.win_rate * 100).toFixed(1)}%` : "—"}
      </td>
      <td className="py-2">
        {p.walk_forward_passed ? (
          <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>PASS</span>
        ) : (
          <span className="text-xs font-semibold" style={{ color: "var(--red)" }}>FAIL</span>
        )}
      </td>
      <td className="py-2">
        {p.is_active ? (
          <span className="inline-flex h-2 w-2 rounded-full" style={{ background: "var(--green)" }} />
        ) : (
          <span className="inline-flex h-2 w-2 rounded-full bg-slate-300" />
        )}
      </td>
      <td className="py-2">
        {!p.is_active && p.walk_forward_passed && (
          <button onClick={onActivate} className="btn-secondary text-xs">활성화</button>
        )}
      </td>
    </tr>
  );
}

/* ── 학습 실험 탭 ──────────────────────────────────────────────────────── */
function ExperimentsTab() {
  const { data: experiments, isLoading } = useExperiments();
  const { data: trainingJobs, isLoading: isJobsLoading } = useTrainingJobs();
  const startJob = useStartTrainingJob();
  const deleteJob = useDeleteTrainingJob();
  const runWF = useRunWalkForward();

  if (isLoading && isJobsLoading) return <div className="card"><div className="h-40 skeleton" /></div>;

  return (
    <div className="space-y-4">
      {/* 트레이닝 잡 목록 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>트레이닝 잡</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>Job ID</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>종목</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>알고리즘</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>상태</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>진행률</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>생성</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>액션</th>
              </tr>
            </thead>
            <tbody>
              {(trainingJobs ?? []).map((job: TrainingJob) => (
                <tr key={job.job_id} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2 font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                    {job.job_id}
                  </td>
                  <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>
                    {job.tickers?.join(", ") ?? job.ticker ?? "—"}
                  </td>
                  <td className="py-2" style={{ color: "var(--text-secondary)" }}>
                    {job.policy_family ?? job.algorithm ?? "—"}
                  </td>
                  <td className="py-2">
                    <StatusBadge status={job.status} />
                  </td>
                  <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                    {job.progress_pct != null ? `${job.progress_pct.toFixed(0)}%` : "—"}
                  </td>
                  <td className="py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                    {(job.created_at ?? job.started_at)?.slice(0, 16).replace("T", " ") ?? "—"}
                  </td>
                  <td className="py-2 flex gap-1">
                    {job.status === "queued" && (
                      <button
                        onClick={() => startJob.mutate(job.job_id)}
                        disabled={startJob.isPending}
                        className="btn-primary text-xs px-3 py-1"
                      >
                        학습 시작
                      </button>
                    )}
                    {job.status !== "running" && (
                      <button
                        onClick={() => { if (confirm("이 작업을 삭제하시겠습니까?")) deleteJob.mutate(job.job_id); }}
                        disabled={deleteJob.isPending}
                        className="text-xs px-3 py-1 rounded"
                        style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                      >
                        삭제
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(trainingJobs ?? []).length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
                    아직 트레이닝 잡이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 실험 목록 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>실험 기록</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>Run ID</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>종목</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>알고리즘</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>상태</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>에피소드</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>Best Reward</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>시작</th>
              </tr>
            </thead>
            <tbody>
              {(experiments ?? []).map((exp) => (
                <tr key={exp.run_id} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2 font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                    {exp.run_id.slice(0, 8)}
                  </td>
                  <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>{exp.ticker}</td>
                  <td className="py-2" style={{ color: "var(--text-secondary)" }}>{exp.algorithm}</td>
                  <td className="py-2">
                    <StatusBadge status={exp.status} />
                  </td>
                  <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                    {exp.episodes}
                  </td>
                  <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                    {exp.best_reward?.toFixed(2) ?? "—"}
                  </td>
                  <td className="py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                    {exp.started_at?.slice(0, 16).replace("T", " ")}
                  </td>
                </tr>
              ))}
              {(experiments ?? []).length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
                    아직 실험 기록이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Walk-Forward 실행 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>Walk-Forward 검증</h3>
        <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
          종목 코드를 입력하여 교차 검증을 실행합니다. DB에 데이터가 없으면 자동으로 FinanceDataReader에서 수집합니다.
        </p>
        <WalkForwardRunner
          onRun={(ticker) => runWF.mutate({ ticker })}
          isPending={runWF.isPending}
          result={runWF.data}
          error={runWF.isError ? (runWF.error as Error)?.message ?? "알 수 없는 오류" : null}
        />
      </div>

      {/* 시장 데이터 수집 */}
      <MarketDataCollector />
    </div>
  );
}

function WalkForwardRunner({ onRun, isPending, result, error }: {
  onRun: (ticker: string) => void;
  isPending: boolean;
  result?: import("@/hooks/useRL").WalkForwardResult | null;
  error?: string | null;
}) {
  const [ticker, setTicker] = useState("");
  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>종목 코드</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !isPending && ticker && onRun(ticker)}
            placeholder="005930"
            className="mt-1 block w-28 rounded-xl border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
          />
        </div>
        <button onClick={() => onRun(ticker)} disabled={isPending || !ticker} className="btn-primary">
          {isPending ? "검증 중..." : "Walk-Forward 실행"}
        </button>
        {result && (
          <span className="text-xs font-semibold" style={{ color: (result.overall_approved ?? result.passed) ? "var(--green)" : "var(--red)" }}>
            {(result.overall_approved ?? result.passed) ? "✓ PASS" : "✗ FAIL"}
            {" — "}
            평균 수익 {formatPct(result.avg_return_pct ?? result.avg_return ?? 0)},
            {" "}
            일관성 {(result.consistency_score ?? 0).toFixed(2)}
            {result.approved_folds != null && ` (${result.approved_folds}/${result.n_folds} folds)`}
          </span>
        )}
      </div>
      {error && (
        <div
          className="rounded-xl px-3 py-2 text-xs font-semibold"
          style={{ background: "var(--red-bg)", color: "var(--red)" }}
        >
          ⚠ 오류: {error}
        </div>
      )}
    </div>
  );
}

/* ── 시장 데이터 수집 컴포넌트 ────────────────────────────────────────── */
function MarketDataCollector() {
  const collect = useCollectMarketData();
  const [tickerInput, setTickerInput] = useState("");

  function handleCollect() {
    const tickers = tickerInput
      .split(/[\s,]+/)
      .map((t) => t.trim())
      .filter(Boolean);
    collect.mutate(tickers);
  }

  return (
    <div className="card">
      <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>시장 데이터 수집</h3>
      <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
        FinanceDataReader(FDR)로 일봉 데이터를 수집하여 DB에 저장합니다. 비워두면 KOSPI/KOSDAQ 상위 30개 종목을 자동 수집합니다.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="flex-1">
          <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>종목 코드 (쉼표/공백 구분, 비워두면 자동)</label>
          <input
            type="text"
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value)}
            placeholder="005930, 000660, 035720"
            className="mt-1 block w-full rounded-xl border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
          />
        </div>
        <button onClick={handleCollect} disabled={collect.isPending} className="btn-primary">
          {collect.isPending ? "수집 중..." : "데이터 수집"}
        </button>
      </div>
      {collect.isSuccess && collect.data && (
        <p className="mt-2 text-xs font-semibold" style={{ color: "var(--green)" }}>
          ✓ {collect.data.message}
        </p>
      )}
      {collect.isError && (
        <p className="mt-2 text-xs font-semibold" style={{ color: "var(--red)" }}>
          ⚠ 수집 실패: {(collect.error as Error)?.message ?? "알 수 없는 오류"}
        </p>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    running: { bg: "var(--blue-bg)", fg: "var(--blue)" },
    completed: { bg: "var(--green-bg)", fg: "var(--green)" },
    failed: { bg: "var(--red-bg)", fg: "var(--red)" },
    queued: { bg: "var(--yellow-bg)", fg: "var(--yellow)" },
  };
  const c = colors[status] ?? colors.queued;
  return (
    <span className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: c.bg, color: c.fg }}>
      {(status ?? "unknown").toUpperCase()}
    </span>
  );
}

/* ── 섀도우 추론 탭 ───────────────────────────────────────────────────── */
function ShadowTab() {
  const { data: shadowPolicies, isLoading } = useShadowPolicies();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data: perfData } = useShadowPerformance(selectedId);

  if (isLoading) return <div className="card"><div className="h-40 skeleton" /></div>;

  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>섀도우 정책 목록</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>Policy ID</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>종목</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>시그널 수</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>평균 신뢰도</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>마지막 시그널</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {(shadowPolicies ?? []).map((sp) => (
                <tr key={sp.policy_id} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2 font-mono text-xs" style={{ color: "var(--text-primary)" }}>{sp.policy_id}</td>
                  <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>{sp.ticker}</td>
                  <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>{sp.signal_count}</td>
                  <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                    {sp.avg_confidence != null ? `${(sp.avg_confidence * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                    {sp.last_signal_at?.slice(0, 16).replace("T", " ") ?? "—"}
                  </td>
                  <td className="py-2">
                    <button onClick={() => setSelectedId(sp.policy_id)} className="btn-secondary text-xs">
                      성과 보기
                    </button>
                  </td>
                </tr>
              ))}
              {(shadowPolicies ?? []).length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
                    섀도우 추론 중인 정책이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 선택된 정책 성과 */}
      {perfData && (
        <div className="card">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
            섀도우 성과 — Policy #{perfData.policy_id} ({perfData.ticker})
          </h3>
          <div className="mt-3 grid gap-3 md:grid-cols-4">
            <div className="rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>정확도</p>
              <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                {(perfData.accuracy * 100).toFixed(1)}%
              </p>
            </div>
            <div className="rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>가상 수익률</p>
              <p className="text-lg font-bold" style={{ color: perfData.virtual_return >= 0 ? "var(--green)" : "var(--red)" }}>
                {formatPct(perfData.virtual_return)}
              </p>
            </div>
            <div className="rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>초과 수익</p>
              <p className="text-lg font-bold" style={{ color: perfData.excess_return >= 0 ? "var(--green)" : "var(--red)" }}>
                {formatPct(perfData.excess_return)}
              </p>
            </div>
            <div className="rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>평가 기간</p>
              <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>{perfData.period_days}일</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 승격 게이트 탭 ───────────────────────────────────────────────────── */
function PromotionTab() {
  const { data: policies } = usePolicies();
  const promoteShadow = usePromoteShadowToPaper();
  const promoteReal = usePromotePaperToReal();
  const [selectedId, setSelectedId] = useState<number | string | null>(null);
  const selectedPolicy = (policies ?? []).find((p) => String(p.id) === String(selectedId));
  const selectedTicker = selectedPolicy?.ticker ?? null;
  const { data: policyMode } = usePolicyMode(selectedId, selectedTicker);
  const [confirmCode, setConfirmCode] = useState("");

  const shadowPolicies = (policies ?? []).filter((p) => p.mode === "shadow" && p.walk_forward_passed);
  const paperPolicies = (policies ?? []).filter((p) => p.mode === "paper");

  return (
    <div className="space-y-4">
      {/* Shadow → Paper */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>Shadow → Paper 승격</h3>
        <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
          Walk-Forward 통과한 Shadow 정책을 Paper 모드로 승격합니다.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>ID</th>
                <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>종목</th>
                <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>초과수익</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {shadowPolicies.map((p) => (
                <tr key={p.id} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2 font-mono text-xs" style={{ color: "var(--text-primary)" }}>{p.id}</td>
                  <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>{p.ticker}</td>
                  <td className="py-2 text-right font-mono text-xs" style={{ color: (p.excess_return ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {p.excess_return != null ? formatPct(p.excess_return) : "—"}
                  </td>
                  <td className="py-2 text-right">
                    <button
                      onClick={() => promoteShadow.mutate({ policy_id: p.id, ticker: p.ticker })}
                      disabled={promoteShadow.isPending}
                      className="btn-primary text-xs"
                    >
                      Paper 승격
                    </button>
                  </td>
                </tr>
              ))}
              {shadowPolicies.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
                    승격 가능한 Shadow 정책이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {promoteShadow.data && (
          <p className="mt-2 text-xs font-semibold" style={{ color: (promoteShadow.data.passed ?? promoteShadow.data.approved) ? "var(--green)" : "var(--red)" }}>
            {(promoteShadow.data.passed ?? promoteShadow.data.approved)
              ? "승격 승인됨"
              : `거부: ${promoteShadow.data.failures?.join(", ") ?? promoteShadow.data.reason ?? "조건 미충족"}`}
          </p>
        )}
      </div>

      {/* Paper → Real */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>Paper → Real 승격</h3>
        <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
          Paper 모드에서 검증된 정책을 실거래로 승격합니다. 확인 코드가 필요합니다.
        </p>
        <div className="mt-3 space-y-3">
          {paperPolicies.map((p) => (
            <div key={p.id} className="flex flex-wrap items-center gap-3 rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
              <span className="font-mono text-xs" style={{ color: "var(--text-primary)" }}>#{p.id}</span>
              <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{p.ticker}</span>
              <ModeBadge mode={p.mode} />
              <span className="font-mono text-xs" style={{ color: (p.excess_return ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                {p.excess_return != null ? formatPct(p.excess_return) : "—"}
              </span>
              <input
                type="text"
                placeholder="확인 코드"
                value={String(selectedId) === String(p.id) ? confirmCode : ""}
                onFocus={() => setSelectedId(p.id)}
                onChange={(e) => { setSelectedId(p.id); setConfirmCode(e.target.value); }}
                className="w-28 rounded-xl border px-2 py-1.5 text-xs"
                style={{ borderColor: "var(--border)", background: "white" }}
              />
              <button
                onClick={() =>
                  promoteReal.mutate({ policy_id: p.id, ticker: p.ticker, confirmation_code: confirmCode })
                }
                disabled={promoteReal.isPending || String(selectedId) !== String(p.id) || !confirmCode}
                className="btn-primary text-xs"
                style={{ background: "linear-gradient(135deg, var(--red), #ff6b6b)" }}
              >
                Real 승격
              </button>
            </div>
          ))}
          {paperPolicies.length === 0 && (
            <p className="py-4 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
              Paper 모드 정책이 없습니다.
            </p>
          )}
        </div>
        {promoteReal.data && (
          <p className="mt-2 text-xs font-semibold" style={{ color: (promoteReal.data.passed ?? promoteReal.data.approved) ? "var(--green)" : "var(--red)" }}>
            {(promoteReal.data.passed ?? promoteReal.data.approved)
              ? "실거래 승격 완료"
              : `거부: ${promoteReal.data.failures?.join(", ") ?? promoteReal.data.reason ?? "조건 미충족"}`}
          </p>
        )}
      </div>

      {/* 정책 모드 조회 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>정책 모드 조회</h3>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>Policy ID</label>
            <input
              type="text"
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value ? e.target.value : null)}
              placeholder="tabular_005930_..."
              className="mt-1 block w-40 rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
            />
          </div>
        </div>
        {policyMode && (
          <div className="mt-3 rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              현재 모드: <strong style={{ color: "var(--text-primary)" }}>{(policyMode.current_mode ?? "unknown").toUpperCase()}</strong>
              {policyMode.can_promote_to && (
                <> → 다음 승격: <strong style={{ color: "var(--brand-500)" }}>{policyMode.can_promote_to.toUpperCase()}</strong></>
              )}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── 메인 페이지 ───────────────────────────────────────────────────────── */
export default function RLTrading() {
  const [activeTab, setActiveTab] = useState<Tab>("tickers");

  return (
    <div className="page-shell space-y-5">
      {/* Hero */}
      <section className="hero-section">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>강화학습</p>
            <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
              RL Trading
            </h1>
            <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
              강화학습 정책을 학습·평가·승격하고, 섀도우 추론 성과를 모니터링합니다.
            </p>
          </div>
        </div>
      </section>

      {/* 탭 */}
      <div className="flex flex-wrap gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={[
              "rounded-2xl px-4 py-2.5 text-sm font-semibold transition-all",
              activeTab === tab.key ? "text-white shadow-lg" : "text-slate-600 hover:bg-white/80",
            ].join(" ")}
            style={
              activeTab === tab.key
                ? { background: "linear-gradient(135deg, var(--brand-500), #4b9dff)" }
                : { background: "rgba(255,255,255,0.72)" }
            }
          >
            <span>{tab.label}</span>
            <span className="ml-1.5 text-[11px] font-medium opacity-70">{tab.desc}</span>
          </button>
        ))}
      </div>

      {/* 탭 콘텐츠 */}
      {activeTab === "tickers" && <TickersTab />}
      {activeTab === "policies" && <PoliciesTab />}
      {activeTab === "experiments" && <ExperimentsTab />}
      {activeTab === "shadow" && <ShadowTab />}
      {activeTab === "promotion" && <PromotionTab />}
    </div>
  );
}
