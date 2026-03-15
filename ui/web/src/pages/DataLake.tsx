/**
 * ui/src/pages/DataLake.tsx
 * S3 Data Lake 현황 대시보드
 */
import { useAccuracy } from "@/hooks/useFeedback";

export default function DataLakePage() {
  const { data: accuracy } = useAccuracy();

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>데이터</p>
        <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
          Data Lake
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          S3 (MinIO) 기반 Parquet 데이터 레이크의 저장 현황입니다.
        </p>
      </section>

      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>버킷 구조</h3>
        <div className="mt-3 space-y-2">
          {["daily_bars", "predictions", "signals", "portfolio_snapshots", "rl_training", "research", "backtest_results"].map((prefix) => (
            <div key={prefix} className="flex items-center gap-2 rounded-xl p-2" style={{ background: "var(--bg-secondary)" }}>
              <span className="text-xs font-mono font-semibold" style={{ color: "var(--brand-500)" }}>alpha-lake/</span>
              <span className="text-xs font-mono" style={{ color: "var(--text-primary)" }}>{prefix}/</span>
            </div>
          ))}
        </div>
      </div>

      {accuracy && (accuracy.length > 0) && (
        <div className="card">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>예측 데이터 요약</h3>
          <p className="mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
            {accuracy.reduce((sum, a) => sum + a.total_predictions, 0)}건의 예측 기록이 저장되어 있습니다.
          </p>
        </div>
      )}
    </div>
  );
}
