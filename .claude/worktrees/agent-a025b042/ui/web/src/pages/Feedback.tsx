/**
 * ui/src/pages/Feedback.tsx
 * 피드백 루프 대시보드 — 정확도, 백테스트, LLM 피드백, 사이클 실행
 */
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  useAccuracy,
  useLLMContext,
  useRunBacktest,
  useCompareStrategies,
  useRetrainTicker,
  useRetrainAll,
  useRunFeedbackCycle,
  type BacktestRequest,
} from "@/hooks/useFeedback";
import { formatPct } from "@/utils/api";

/* ── 탭 정의 ───────────────────────────────────────────────────────────── */
type Tab = "accuracy" | "backtest" | "llm" | "cycle";
const TABS: { key: Tab; label: string; desc: string }[] = [
  { key: "accuracy", label: "예측 정확도", desc: "전략별 성과" },
  { key: "backtest", label: "백테스트", desc: "전략 비교 시뮬레이션" },
  { key: "llm", label: "LLM 피드백", desc: "에러 패턴 분석" },
  { key: "cycle", label: "피드백 사이클", desc: "수동 실행" },
];

const TOOLTIP_STYLE = {
  background: "rgba(255,255,255,0.96)",
  border: "1px solid rgba(148,163,184,0.2)",
  borderRadius: "20px",
  color: "#111827",
  fontSize: "12px",
  boxShadow: "0 20px 36px rgba(15,23,42,0.12)",
};

const STRATEGY_COLORS: Record<string, string> = {
  A: "#1f63f7",
  B: "#8b5cf6",
  RL: "#10b981",
  S: "#f59e0b",
  L: "#6366f1",
};

/* ── 정확도 탭 ─────────────────────────────────────────────────────────── */
function AccuracyTab() {
  const [days, setDays] = useState(30);
  const { data: stats, isLoading } = useAccuracy(undefined, days);

  if (isLoading) return <div className="card"><div className="h-40 skeleton" /></div>;

  const items = stats ?? [];

  const chartData = items.map((s) => ({
    strategy: s.strategy,
    accuracy: +(s.accuracy * 100).toFixed(1),
    total: s.total_predictions,
  }));

  return (
    <div className="space-y-4">
      {/* 기간 선택 */}
      <div className="flex flex-wrap gap-1.5">
        {[7, 14, 30, 60, 90].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={[
              "rounded-xl px-3 py-1.5 text-xs font-semibold transition-all",
              days === d ? "text-white" : "text-slate-600",
            ].join(" ")}
            style={
              days === d
                ? { background: "linear-gradient(135deg, var(--brand-500), #4b9dff)" }
                : { background: "rgba(255,255,255,0.72)" }
            }
          >
            {d}일
          </button>
        ))}
      </div>

      {/* KPI 카드 */}
      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-5">
        {items.map((s) => (
          <div key={s.strategy} className="card text-center">
            <p className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>
              전략 {s.strategy}
            </p>
            <p
              className="mt-1 text-2xl font-bold"
              style={{ color: s.accuracy >= 0.5 ? "var(--green)" : "var(--red)" }}
            >
              {(s.accuracy * 100).toFixed(1)}%
            </p>
            <p className="mt-0.5 text-[11px]" style={{ color: "var(--text-secondary)" }}>
              {s.correct_predictions}/{s.total_predictions}건
            </p>
          </div>
        ))}
        {items.length === 0 && (
          <div className="card col-span-full text-center">
            <p className="py-6 text-sm" style={{ color: "var(--text-secondary)" }}>
              아직 예측 데이터가 없습니다.
            </p>
          </div>
        )}
      </div>

      {/* 정확도 차트 */}
      {chartData.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>전략별 정확도 비교</h3>
          <div className="mt-4" style={{ height: 280 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} barCategoryGap="30%">
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                <XAxis dataKey="strategy" tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number) => [`${v}%`, "정확도"]} />
                <Bar dataKey="accuracy" radius={[8, 8, 0, 0]}>
                  {chartData.map((entry) => (
                    <Cell key={entry.strategy} fill={STRATEGY_COLORS[entry.strategy] ?? "#94a3b8"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* 시그널 분포 */}
      {items.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>시그널 분포</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>전략</th>
                  <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>BUY</th>
                  <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>SELL</th>
                  <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>HOLD</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>기간</th>
                </tr>
              </thead>
              <tbody>
                {items.map((s) => (
                  <tr key={s.strategy} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>{s.strategy}</td>
                    <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--green)" }}>
                      {((s.signal_distribution.BUY ?? 0) * 100).toFixed(0)}%
                    </td>
                    <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--red)" }}>
                      {((s.signal_distribution.SELL ?? 0) * 100).toFixed(0)}%
                    </td>
                    <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                      {((s.signal_distribution.HOLD ?? 0) * 100).toFixed(0)}%
                    </td>
                    <td className="py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {s.period_start?.slice(0, 10)} ~ {s.period_end?.slice(0, 10)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 백테스트 탭 ───────────────────────────────────────────────────────── */
function BacktestTab() {
  const runBacktest = useRunBacktest();
  const compareStrategies = useCompareStrategies();
  const [strategy, setStrategy] = useState("A");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  function handleBacktest() {
    const payload: BacktestRequest = { strategy };
    if (startDate) payload.start_date = startDate;
    if (endDate) payload.end_date = endDate;
    runBacktest.mutate(payload);
  }

  function handleCompare() {
    compareStrategies.mutate({
      strategies: ["A", "B", "RL"],
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    });
  }

  const result = runBacktest.data;
  const comparison = compareStrategies.data;

  return (
    <div className="space-y-4">
      {/* 백테스트 실행 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>단일 전략 백테스트</h3>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>전략</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="mt-1 block rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
            >
              <option value="A">Strategy A</option>
              <option value="B">Strategy B</option>
              <option value="RL">RL</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>시작일</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="mt-1 block rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
            />
          </div>
          <div>
            <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>종료일</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="mt-1 block rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
            />
          </div>
          <button onClick={handleBacktest} disabled={runBacktest.isPending} className="btn-primary">
            {runBacktest.isPending ? "실행 중..." : "백테스트 실행"}
          </button>
        </div>

        {/* 단일 백테스트 결과 */}
        {result && (
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <MetricCard label="총 수익률" value={formatPct(result.total_return)} color={result.total_return >= 0 ? "var(--green)" : "var(--red)"} />
            <MetricCard label="연환산 수익률" value={formatPct(result.annualized_return)} color={result.annualized_return >= 0 ? "var(--green)" : "var(--red)"} />
            <MetricCard label="MDD" value={formatPct(result.max_drawdown)} color="var(--red)" />
            <MetricCard label="Sharpe" value={result.sharpe_ratio?.toFixed(2) ?? "—"} color="var(--text-primary)" />
            <MetricCard label="승률" value={`${(result.win_rate * 100).toFixed(1)}%`} color="var(--text-primary)" />
            <MetricCard label="Profit Factor" value={result.profit_factor?.toFixed(2) ?? "—"} color="var(--text-primary)" />
            <MetricCard label="총 거래" value={`${result.total_trades}건`} color="var(--text-primary)" />
            <MetricCard label="평균 보유일" value={result.avg_holding_days != null ? `${result.avg_holding_days.toFixed(1)}일` : "—"} color="var(--text-primary)" />
          </div>
        )}
      </div>

      {/* 전략 비교 */}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>전략 A/B/RL 비교</h3>
            <p className="mt-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>세 전략을 동일 기간에 백테스트하여 비교합니다.</p>
          </div>
          <button onClick={handleCompare} disabled={compareStrategies.isPending} className="btn-primary">
            {compareStrategies.isPending ? "비교 중..." : "전략 비교 실행"}
          </button>
        </div>

        {comparison && (
          <div className="mt-4">
            <p className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>
              최고 전략: <strong style={{ color: "var(--brand-500)" }}>{comparison.best_strategy}</strong>
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                    <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>순위</th>
                    <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>전략</th>
                    <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>총 수익률</th>
                    <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>연환산</th>
                    <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>MDD</th>
                    <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>Sharpe</th>
                    <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>승률</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.strategies
                    .sort((a, b) => b.total_return - a.total_return)
                    .map((s, idx) => (
                      <tr key={s.strategy} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                        <td className="py-2">
                          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold text-white"
                            style={{ background: idx === 0 ? "var(--green)" : idx === 1 ? "var(--brand-500)" : "var(--text-secondary)" }}>
                            {idx + 1}
                          </span>
                        </td>
                        <td className="py-2 font-semibold" style={{ color: "var(--text-primary)" }}>{s.strategy}</td>
                        <td className="py-2 text-right font-mono text-xs" style={{ color: s.total_return >= 0 ? "var(--green)" : "var(--red)" }}>
                          {formatPct(s.total_return)}
                        </td>
                        <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                          {formatPct(s.annualized_return)}
                        </td>
                        <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--red)" }}>
                          {formatPct(s.max_drawdown)}
                        </td>
                        <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                          {s.sharpe_ratio?.toFixed(2) ?? "—"}
                        </td>
                        <td className="py-2 text-right font-mono text-xs" style={{ color: "var(--text-primary)" }}>
                          {(s.win_rate * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
      <p className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>{label}</p>
      <p className="mt-0.5 text-lg font-bold" style={{ color }}>{value}</p>
    </div>
  );
}

/* ── LLM 피드백 탭 ────────────────────────────────────────────────────── */
function LLMFeedbackTab() {
  const [strategy, setStrategy] = useState<string | null>("A");
  const { data: ctx, isLoading } = useLLMContext(strategy);

  return (
    <div className="space-y-4">
      {/* 전략 선택 */}
      <div className="flex flex-wrap gap-1.5">
        {["A", "B", "RL"].map((s) => (
          <button
            key={s}
            onClick={() => setStrategy(s)}
            className={[
              "rounded-xl px-3 py-1.5 text-xs font-semibold transition-all",
              strategy === s ? "text-white" : "text-slate-600",
            ].join(" ")}
            style={
              strategy === s
                ? { background: STRATEGY_COLORS[s] ?? "var(--brand-500)" }
                : { background: "rgba(255,255,255,0.72)" }
            }
          >
            전략 {s}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="card"><div className="h-40 skeleton" /></div>
      ) : ctx ? (
        <div className="space-y-4">
          {/* 메타 정보 */}
          <div className="card">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
                전략 {ctx.strategy} 피드백 컨텍스트
              </h3>
              {ctx.cached && (
                <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                  style={{ background: "var(--blue-bg)", color: "var(--blue)" }}>CACHED</span>
              )}
              <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                생성: {ctx.generated_at?.slice(0, 19).replace("T", " ")}
              </span>
            </div>
          </div>

          {/* 에러 패턴 */}
          {ctx.error_patterns.length > 0 && (
            <div className="card">
              <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>감지된 에러 패턴</h3>
              <div className="mt-3 space-y-2">
                {ctx.error_patterns.map((pattern, idx) => (
                  <div key={idx} className="flex items-start gap-2 rounded-2xl p-3" style={{ background: "var(--red-bg)" }}>
                    <span className="mt-0.5 text-xs" style={{ color: "var(--red)" }}>!</span>
                    <span className="text-sm" style={{ color: "var(--red)" }}>{pattern}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 시그널 편향 */}
          {Object.keys(ctx.signal_bias).length > 0 && (
            <div className="card">
              <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>시그널 편향</h3>
              <div className="mt-3 flex flex-wrap gap-4">
                {Object.entries(ctx.signal_bias).map(([signal, ratio]) => (
                  <div key={signal} className="text-center">
                    <p className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>{signal}</p>
                    <p className="text-xl font-bold" style={{
                      color: signal === "BUY" ? "var(--green)" : signal === "SELL" ? "var(--red)" : "var(--text-primary)"
                    }}>
                      {(ratio * 100).toFixed(0)}%
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 피드백 텍스트 */}
          <div className="card">
            <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>프롬프트 주입 컨텍스트</h3>
            <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-relaxed"
              style={{ background: "var(--bg-secondary)", color: "var(--text-primary)" }}>
              {ctx.feedback_text || "(피드백 없음)"}
            </pre>
          </div>
        </div>
      ) : (
        <div className="card">
          <p className="py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
            선택한 전략의 피드백 데이터가 없습니다.
          </p>
        </div>
      )}
    </div>
  );
}

/* ── 피드백 사이클 탭 ──────────────────────────────────────────────────── */
function CycleTab() {
  const runCycle = useRunFeedbackCycle();
  const retrainAll = useRetrainAll();
  const retrainTicker = useRetrainTicker();
  const [ticker, setTicker] = useState("");
  const [scope, setScope] = useState<"full" | "llm_only" | "rl_only" | "backtest_only">("full");

  return (
    <div className="space-y-4">
      {/* 전체 사이클 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>피드백 사이클 수동 실행</h3>
        <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
          S3 Data Lake 데이터를 기반으로 LLM 피드백, RL 재학습, 백테스트를 일괄 실행합니다.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <label className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>범위</label>
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as typeof scope)}
              className="mt-1 block rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
            >
              <option value="full">전체 (LLM + RL + Backtest)</option>
              <option value="llm_only">LLM 피드백만</option>
              <option value="rl_only">RL 재학습만</option>
              <option value="backtest_only">백테스트만</option>
            </select>
          </div>
          <button onClick={() => runCycle.mutate(scope)} disabled={runCycle.isPending} className="btn-primary">
            {runCycle.isPending ? "실행 중..." : "사이클 실행"}
          </button>
        </div>

        {runCycle.data && (
          <div className="mt-4 rounded-2xl p-4" style={{ background: "var(--bg-secondary)" }}>
            <p className="text-xs font-semibold" style={{ color: "var(--green)" }}>
              사이클 완료 — {runCycle.data.duration_seconds.toFixed(1)}초 소요
            </p>
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              {runCycle.data.llm_feedback && (
                <div className="text-xs" style={{ color: "var(--text-primary)" }}>
                  LLM: {runCycle.data.llm_feedback.strategies_processed}개 전략 처리
                </div>
              )}
              {runCycle.data.rl_retrain && (
                <div className="text-xs" style={{ color: "var(--text-primary)" }}>
                  RL: {runCycle.data.rl_retrain.successful}/{runCycle.data.rl_retrain.tickers_retrained} 종목 성공
                </div>
              )}
              {runCycle.data.backtest && (
                <div className="text-xs" style={{ color: "var(--text-primary)" }}>
                  Backtest: 최고 전략 {runCycle.data.backtest.best_strategy}
                </div>
              )}
            </div>
            {runCycle.data.saved_to_s3 && (
              <p className="mt-1 text-[11px]" style={{ color: "var(--text-secondary)" }}>결과 S3에 저장됨</p>
            )}
          </div>
        )}
      </div>

      {/* RL 재학습 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>RL 개별 종목 재학습</h3>
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
          <button onClick={() => { retrainTicker.mutate(ticker); setTicker(""); }} disabled={retrainTicker.isPending || !ticker} className="btn-primary">
            {retrainTicker.isPending ? "학습 중..." : "개별 재학습"}
          </button>
          <button onClick={() => retrainAll.mutate()} disabled={retrainAll.isPending} className="btn-secondary">
            {retrainAll.isPending ? "전체 학습 중..." : "전체 종목 재학습"}
          </button>
        </div>

        {retrainTicker.data && (
          <p className="mt-2 text-xs font-semibold" style={{
            color: retrainTicker.data.success ? "var(--green)" : "var(--red)"
          }}>
            {retrainTicker.data.ticker}: {retrainTicker.data.success
              ? `성공 (초과수익 ${formatPct(retrainTicker.data.excess_return ?? 0)}, 배포: ${retrainTicker.data.deployed ? "O" : "X"})`
              : `실패: ${retrainTicker.data.error}`
            }
          </p>
        )}

        {retrainAll.data && (
          <div className="mt-3 rounded-2xl p-3" style={{ background: "var(--bg-secondary)" }}>
            <p className="text-xs font-semibold" style={{ color: "var(--green)" }}>
              전체 재학습 완료: {retrainAll.data.successful}/{retrainAll.data.total_tickers} 성공, {retrainAll.data.failed} 실패
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── 메인 페이지 ───────────────────────────────────────────────────────── */
export default function Feedback() {
  const [activeTab, setActiveTab] = useState<Tab>("accuracy");

  return (
    <div className="page-shell space-y-5">
      {/* Hero */}
      <section className="hero-section">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>피드백 루프</p>
            <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
              성과 분석
            </h1>
            <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
              S3 Data Lake 기반으로 예측 정확도를 분석하고, 백테스트와 피드백 사이클을 실행합니다.
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
      {activeTab === "accuracy" && <AccuracyTab />}
      {activeTab === "backtest" && <BacktestTab />}
      {activeTab === "llm" && <LLMFeedbackTab />}
      {activeTab === "cycle" && <CycleTab />}
    </div>
  );
}
