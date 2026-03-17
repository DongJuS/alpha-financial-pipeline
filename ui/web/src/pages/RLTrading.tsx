/**
 * ui/src/pages/RLTrading.tsx
 * RL Trading 대시보드 — 정책 관리, 실험, 섀도우 추론, 승격
 */
import { useState } from "react";
import {
  usePolicies,
  useActivePolicies,
  useExperiments,
  useEvaluations,
  useShadowPolicies,
  useShadowPerformance,
  useActivatePolicy,
  useCreateTrainingJob,
  useRunWalkForward,
  usePromoteShadowToPaper,
  usePromotePaperToReal,
  usePolicyMode,
  type RLPolicy,
  type TrainingJobRequest,
} from "@/hooks/useRL";
import { formatPct } from "@/utils/api";

/* ── 탭 정의 ───────────────────────────────────────────────────────────── */
type Tab = "policies" | "experiments" | "shadow" | "promotion";
const TABS: { key: Tab; label: string; desc: string }[] = [
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
      {m.toUpperCase()}
    </span>
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
  const createJob = useCreateTrainingJob();
  const runWF = useRunWalkForward();
  const [ticker, setTicker] = useState("");
  const [episodes, setEpisodes] = useState(500);

  function handleTrain() {
    if (!ticker) return;
    const payload: TrainingJobRequest = { ticker: ticker.trim(), episodes };
    createJob.mutate(payload);
    setTicker("");
  }

  if (isLoading) return <div className="card"><div className="h-40 skeleton" /></div>;

  return (
    <div className="space-y-4">
      {/* 새 트레이닝 잡 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>새 트레이닝 실행</h3>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>종목 코드</label>
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="005930"
              className="mt-1 block w-32 rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
            />
          </div>
          <div>
            <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>에피소드</label>
            <input
              type="number"
              value={episodes}
              onChange={(e) => setEpisodes(Number(e.target.value))}
              className="mt-1 block w-24 rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
            />
          </div>
          <button onClick={handleTrain} disabled={createJob.isPending || !ticker} className="btn-primary">
            {createJob.isPending ? "실행 중..." : "학습 시작"}
          </button>
        </div>
        {createJob.isSuccess && (
          <p className="mt-2 text-xs font-semibold" style={{ color: "var(--green)" }}>
            트레이닝 잡 생성 완료: {createJob.data?.job_id}
          </p>
        )}
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
          종목 코드를 입력하여 교차 검증을 실행합니다.
        </p>
        <WalkForwardRunner onRun={(ticker) => runWF.mutate({ ticker })} isPending={runWF.isPending} result={runWF.data} />
      </div>
    </div>
  );
}

function WalkForwardRunner({ onRun, isPending, result }: {
  onRun: (ticker: string) => void;
  isPending: boolean;
  result?: import("@/hooks/useRL").WalkForwardResult | null;
}) {
  const [ticker, setTicker] = useState("");
  return (
    <div className="mt-3 flex flex-wrap items-end gap-3">
      <div>
        <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>종목 코드</label>
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
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
          {(result.overall_approved ?? result.passed) ? "PASS" : "FAIL"}
          {" — "}
          평균 수익 {formatPct(result.avg_return_pct ?? result.avg_return ?? 0)},
          {" "}
          일관성 {(result.consistency_score ?? 0).toFixed(2)}
          {result.approved_folds != null && ` (${result.approved_folds}/${result.n_folds} folds)`}
        </span>
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
      {status.toUpperCase()}
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
              현재 모드: <strong style={{ color: "var(--text-primary)" }}>{policyMode.current_mode.toUpperCase()}</strong>
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
  const [activeTab, setActiveTab] = useState<Tab>("policies");

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
      {activeTab === "policies" && <PoliciesTab />}
      {activeTab === "experiments" && <ExperimentsTab />}
      {activeTab === "shadow" && <ShadowTab />}
      {activeTab === "promotion" && <PromotionTab />}
    </div>
  );
}
