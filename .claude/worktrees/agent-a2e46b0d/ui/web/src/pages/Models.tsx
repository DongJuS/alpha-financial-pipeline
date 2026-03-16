import { useEffect, useState } from "react";

import {
  useModelConfig,
  useUpdateModelConfig,
  type ModelRoleItem,
  type ModelRoleUpdateItem,
} from "@/hooks/useModels";

type ModelRoleForm = Record<string, ModelRoleUpdateItem>;

const ROLE_COPY: Record<string, string> = {
  strategy_a_predictor_1: "전략 A의 첫 번째 가치 관점 슬롯입니다.",
  strategy_a_predictor_2: "전략 A의 기술 분석 슬롯입니다.",
  strategy_a_predictor_3: "전략 A의 모멘텀 슬롯입니다.",
  strategy_a_predictor_4: "전략 A의 역추세 슬롯입니다.",
  strategy_a_predictor_5: "전략 A의 거시/대안 시나리오 슬롯입니다.",
  strategy_b_proposer: "초기 가설과 매매 방향을 제시하는 역할입니다.",
  strategy_b_challenger_1: "주장의 취약점을 빠르게 찌르는 반론 역할입니다.",
  strategy_b_challenger_2: "거시 변수와 대안을 점검하는 반론 역할입니다.",
  strategy_b_synthesizer: "최종 결론과 HOLD 정책을 정리하는 역할입니다.",
};

function toFormRows(rows: ModelRoleItem[]): ModelRoleForm {
  return Object.fromEntries(
    rows.map((row) => [
      row.config_key,
      {
        config_key: row.config_key,
        llm_model: row.llm_model,
        persona: row.persona,
      },
    ])
  );
}

function RoleEditor({
  row,
  form,
  onChange,
  supportedModels,
}: {
  row: ModelRoleItem;
  form: ModelRoleUpdateItem | undefined;
  onChange: (configKey: string, next: Partial<ModelRoleUpdateItem>) => void;
  supportedModels: Array<{ model: string; label: string; provider: string; description: string }>;
}) {
  return (
    <article
      className="rounded-[24px] border p-4"
      style={{ background: "var(--bg-elevated)", borderColor: "var(--line-soft)" }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
          {row.role_label}
        </h3>
        <span className="chip">{row.agent_id}</span>
        <span className="chip">{row.strategy_code === "A" ? "Strategy A" : "Strategy B"}</span>
      </div>
      <p className="mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
        {ROLE_COPY[row.config_key] ?? "이 역할의 모델과 페르소나를 운영합니다."}
      </p>

      <div className="mt-4 space-y-3">
        <label className="block">
          <span className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            모델 선택
          </span>
          <select
            value={form?.llm_model ?? row.llm_model}
            onChange={(e) => onChange(row.config_key, { llm_model: e.target.value })}
          >
            {supportedModels.map((model) => (
              <option key={model.model} value={model.model}>
                {model.label} · {model.provider}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-[11px]" style={{ color: "var(--text-secondary)" }}>
            {
              supportedModels.find((item) => item.model === (form?.llm_model ?? row.llm_model))?.description
            }
          </span>
        </label>

        <label className="block">
          <span className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            페르소나
          </span>
          <textarea
            value={form?.persona ?? row.persona}
            onChange={(e) => onChange(row.config_key, { persona: e.target.value })}
            rows={3}
            className="min-h-[96px]"
          />
        </label>
      </div>
    </article>
  );
}

export default function Models() {
  const { data, isLoading } = useModelConfig();
  const mutation = useUpdateModelConfig();
  const [form, setForm] = useState<ModelRoleForm>({});

  useEffect(() => {
    if (!data) return;
    setForm(toFormRows([...data.strategy_a, ...data.strategy_b]));
  }, [data]);

  function updateRow(configKey: string, next: Partial<ModelRoleUpdateItem>) {
    setForm((prev) => ({
      ...prev,
      [configKey]: {
        config_key: configKey,
        llm_model: next.llm_model ?? prev[configKey]?.llm_model ?? "",
        persona: next.persona ?? prev[configKey]?.persona ?? "",
      },
    }));
  }

  function handleSave() {
    mutation.mutate(Object.values(form));
  }

  return (
    <div className="page-shell max-w-6xl space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>
          모델 관리
        </p>
        <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
          페르소나와 역할 배치
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          Strategy A/B에서 어떤 모델이 어떤 역할을 맡을지 고정 슬롯으로 운영합니다. 규칙 기반 fallback은 허용하지 않고,
          LLM provider 간 재시도만 사용합니다.
        </p>
      </section>

      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
              Provider 상태
            </h2>
            <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
              API 키 또는 CLI가 연결된 provider만 실행에 사용됩니다.
            </p>
          </div>
          <div className="chip">Rule-based fallback disabled</div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {(data?.provider_status ?? []).map((provider) => (
            <article
              key={provider.provider}
              className="rounded-[22px] border p-4"
              style={{ background: "var(--bg-elevated)", borderColor: "var(--line-soft)" }}
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-bold capitalize" style={{ color: "var(--text-primary)" }}>
                  {provider.provider}
                </h3>
                <span
                  className="rounded-full px-2.5 py-1 text-[11px] font-semibold"
                  style={{
                    background: provider.configured ? "var(--green-bg)" : "var(--loss-bg)",
                    color: provider.configured ? "var(--green)" : "var(--loss)",
                  }}
                >
                  {provider.configured ? "READY" : "NOT CONFIGURED"}
                </span>
              </div>
              <p className="mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                기본 모델: {provider.default_model}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="card space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
              Strategy A Predictor 슬롯
            </h2>
            <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
              토너먼트에 참여하는 5개 predictor의 모델과 페르소나를 관리합니다.
            </p>
          </div>
          <span className="chip">Parallel tournament</span>
        </div>

        {isLoading ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="h-56 skeleton" />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(data?.strategy_a ?? []).map((row) => (
              <RoleEditor
                key={row.config_key}
                row={row}
                form={form[row.config_key]}
                onChange={updateRow}
                supportedModels={data?.supported_models ?? []}
              />
            ))}
          </div>
        )}
      </section>

      <section className="card space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
              Strategy B Debate 역할
            </h2>
            <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
              proposer, challenger, synthesizer의 모델과 페르소나를 분리 운영합니다.
            </p>
          </div>
          <span className="chip">Debate orchestration</span>
        </div>

        {isLoading ? (
          <div className="grid gap-3 md:grid-cols-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="h-56 skeleton" />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {(data?.strategy_b ?? []).map((row) => (
              <RoleEditor
                key={row.config_key}
                row={row}
                form={form[row.config_key]}
                onChange={updateRow}
                supportedModels={data?.supported_models ?? []}
              />
            ))}
          </div>
        )}
      </section>

      <section className="card flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
            적용 정책
          </h2>
          <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
            저장 후 다음 predictor/consensus cycle부터 새 모델 배치가 반영됩니다.
          </p>
        </div>
        <button className="btn-primary disabled:opacity-50" disabled={mutation.isPending || isLoading} onClick={handleSave}>
          {mutation.isPending ? "저장 중..." : "모델 설정 저장"}
        </button>
      </section>
    </div>
  );
}
