/**
 * ui/src/pages/DataLake.tsx
 * S3 Data Lake 현황 대시보드 — 실제 API 연동
 */
import { useState } from "react";
import {
  useDatalakeOverview,
  useDatalakeObjects,
  useDeleteDatalakeObject,
  type DataLakeOverview,
} from "@/hooks/useDatalake";

function SizeBar({ ratio }: { ratio: number }) {
  return (
    <div className="h-1.5 w-full rounded-full" style={{ background: "var(--bg-secondary)" }}>
      <div
        className="h-1.5 rounded-full"
        style={{
          width: `${Math.max(ratio * 100, 2)}%`,
          background: "linear-gradient(90deg, var(--brand-500), #49a3ff)",
        }}
      />
    </div>
  );
}

function OverviewCard({ overview }: { overview: DataLakeOverview }) {
  const maxSize = Math.max(...overview.prefixes.map((p) => p.size), 1);

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          버킷 개요
        </h3>
        <span
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={{ background: "var(--green-bg)", color: "var(--green)" }}
        >
          {overview.bucket_name}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
          <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>총 객체</p>
          <p className="mt-1 text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {overview.total_objects.toLocaleString()}
          </p>
        </div>
        <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
          <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>총 크기</p>
          <p className="mt-1 text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {overview.total_size_display}
          </p>
        </div>
        <div className="rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
          <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>접두사</p>
          <p className="mt-1 text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {overview.prefixes.length}
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        <h4 className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>
          접두사별 분포
        </h4>
        {overview.prefixes.map((p) => (
          <div key={p.prefix} className="rounded-xl p-2.5" style={{ background: "var(--bg-secondary)" }}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-semibold" style={{ color: "var(--brand-500)" }}>
                {p.prefix}/
              </span>
              <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                {p.count}개 · {p.size_display}
              </span>
            </div>
            <div className="mt-1.5">
              <SizeBar ratio={p.size / maxSize} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ObjectBrowser() {
  const [prefix, setPrefix] = useState("");
  const { data: objects, isLoading } = useDatalakeObjects(prefix);
  const deleteMutation = useDeleteDatalakeObject();

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          객체 탐색기
        </h3>
        {prefix && (
          <button
            className="text-xs font-semibold"
            style={{ color: "var(--brand-500)" }}
            onClick={() => {
              const parts = prefix.split("/").filter(Boolean);
              parts.pop();
              setPrefix(parts.length ? parts.join("/") + "/" : "");
            }}
          >
            ← 상위 폴더
          </button>
        )}
      </div>
      <p className="mt-1 font-mono text-xs" style={{ color: "var(--text-tertiary)" }}>
        {prefix || "/"}
      </p>

      {isLoading ? (
        <div className="mt-3 h-40 skeleton" />
      ) : (
        <div className="mt-3 space-y-1">
          {objects?.common_prefixes.map((cp) => (
            <button
              key={cp}
              className="flex w-full items-center gap-2 rounded-xl p-2.5 text-left transition-colors hover:bg-slate-50"
              onClick={() => setPrefix(cp)}
            >
              <span className="text-sm">📁</span>
              <span className="text-xs font-semibold" style={{ color: "var(--brand-500)" }}>
                {cp}
              </span>
            </button>
          ))}
          {objects?.objects.map((obj) => (
            <div
              key={obj.key}
              className="flex items-center justify-between rounded-xl p-2.5"
              style={{ background: "var(--bg-secondary)" }}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-mono" style={{ color: "var(--text-primary)" }}>
                  {obj.key.split("/").pop()}
                </p>
                <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                  {obj.size_display}
                  {obj.last_modified && ` · ${new Date(obj.last_modified).toLocaleString("ko-KR")}`}
                </p>
              </div>
              <button
                className="ml-2 rounded-lg px-2 py-1 text-[11px] font-semibold text-red-600 hover:bg-red-50"
                onClick={() => {
                  if (confirm(`'${obj.key}' 를 삭제하시겠습니까?`)) {
                    deleteMutation.mutate(obj.key);
                  }
                }}
                disabled={deleteMutation.isPending}
              >
                삭제
              </button>
            </div>
          ))}
          {objects?.objects.length === 0 && objects?.common_prefixes.length === 0 && (
            <p className="py-6 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>
              이 경로에 객체가 없습니다.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function DataLakePage() {
  const { data: overview, isLoading } = useDatalakeOverview();

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>데이터</p>
        <h1
          className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]"
          style={{ color: "var(--text-primary)" }}
        >
          Data Lake
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          S3 (MinIO) 기반 Parquet 데이터 레이크의 저장 현황입니다.
        </p>
      </section>

      {isLoading ? (
        <div className="card">
          <div className="h-60 skeleton" />
        </div>
      ) : overview ? (
        <OverviewCard overview={overview} />
      ) : (
        <div className="card">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            데이터 레이크 정보를 불러올 수 없습니다.
          </p>
        </div>
      )}

      <ObjectBrowser />
    </div>
  );
}
