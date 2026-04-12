import { useEffect, useState } from "react";

import {
  useModelConfig,
  useUpdateModelConfig,
  useAddModelRole,
  useDeleteModelRole,
  type ModelRoleItem,
  type ModelRoleUpdateItem,
  type AddModelRoleRequest,
} from "@/hooks/useModels";

type ModelRoleForm = Record<string, ModelRoleUpdateItem>;

function toFormRows(rows: ModelRoleItem[]): ModelRoleForm {
  return Object.fromEntries(
    rows.map((row) => [
      row.config_key,
      {
        config_key: row.config_key,
        llm_model: row.llm_model,
        persona: row.persona,
        is_enabled: row.is_enabled,
      },
    ])
  );
}

function RoleEditor({
  row,
  form,
  onChange,
  onDelete,
  supportedModels,
}: {
  row: ModelRoleItem;
  form: ModelRoleUpdateItem | undefined;
  onChange: (configKey: string, next: Partial<ModelRoleUpdateItem>) => void;
  onDelete?: (configKey: string) => void;
  supportedModels: Array<{ model: string; label: string; provider: string; description: string }>;
}) {
  const isEnabled = form?.is_enabled ?? row.is_enabled;

  return (
    <article
      className="rounded-[24px] border p-4 transition-opacity"
      style={{
        background: "var(--bg-elevated)",
        borderColor: isEnabled ? "var(--line-soft)" : "var(--loss-bg)",
        opacity: isEnabled ? 1 : 0.5,
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
            {row.role_label}
          </h3>
          <span className="chip">{row.agent_id}</span>
          <span className="chip">{row.strategy_code === "A" ? "Strategy A" : "Strategy B"}</span>
        </div>
        {onDelete && (
          <button
            type="button"
            onClick={() => onDelete(row.config_key)}
            className="rounded-full p-1 text-xs transition-colors hover:bg-[var(--loss-bg)]"
            style={{ color: "var(--loss)" }}
            title="역할 삭제"
          >
            ✕
          </button>
        )}
        <button
          type="button"
          role="switch"
          aria-checked={isEnabled}
          onClick={() => onChange(row.config_key, { is_enabled: !isEnabled })}
          className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors"
          style={{ background: isEnabled ? "var(--green)" : "var(--text-tertiary)" }}
        >
          <span
            className="pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transition-transform"
            style={{ transform: isEnabled ? "translateX(1.25rem)" : "translateX(0.125rem)", marginTop: "0.125rem" }}
          />
        </button>
      </div>
      {!isEnabled && (
        <p className="mt-1 text-xs font-semibold" style={{ color: "var(--loss)" }}>
          비활성 — 다음 사이클부터 실행에서 제외됩니다.
        </p>
      )}
      <p className="mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
        이 역할의 모델과 페르소나를 운영합니다.
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
  const addMutation = useAddModelRole();
  const deleteMutation = useDeleteModelRole();
  const [form, setForm] = useState<ModelRoleForm>({});
  const [addTarget, setAddTarget] = useState<{ strategy: "A" | "B"; role: string } | null>(null);
  const [newModel, setNewModel] = useState("");
  const [newPersona, setNewPersona] = useState("");

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
        is_enabled: next.is_enabled ?? prev[configKey]?.is_enabled ?? true,
      },
    }));
  }

  function handleSave() {
    mutation.mutate(Object.values(form));
  }

  function handleAddRole() {
    if (!addTarget || !newModel || !newPersona.trim()) return;
    addMutation.mutate({
      strategy_code: addTarget.strategy,
      role: addTarget.role,
      llm_model: newModel,
      persona: newPersona.trim(),
    }, {
      onSuccess: () => {
        setAddTarget(null);
        setNewModel("");
        setNewPersona("");
      },
    });
  }

  function handleDelete(configKey: string) {
    if (!confirm("이 역할을 삭제하시겠습니까?")) return;
    deleteMutation.mutate(configKey);
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
              토너먼트에 참여하는 predictor의 모델과 페르소나를 관리합니다.
            </p>
          </div>
          <span className="chip">Parallel tournament</span>
        </div>

        {isLoading ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 2 }).map((_, index) => (
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
                onDelete={handleDelete}
                supportedModels={data?.supported_models ?? []}
              />
            ))}
            <button
              type="button"
              onClick={() => {
                setAddTarget({ strategy: "A", role: "predictor" });
                setNewModel(data?.supported_models?.[0]?.model ?? "");
              }}
              className="flex min-h-[200px] items-center justify-center rounded-[24px] border-2 border-dashed transition-colors hover:border-[var(--green)]"
              style={{ borderColor: "var(--line-soft)", color: "var(--text-tertiary)" }}
            >
              <span className="text-3xl">+</span>
            </button>
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
              토론에 참여하는 역할의 모델과 페르소나를 운영합니다.
            </p>
          </div>
          <span className="chip">Debate orchestration</span>
        </div>

        {isLoading ? (
          <div className="grid gap-3 md:grid-cols-2">
            {Array.from({ length: 3 }).map((_, index) => (
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
                onDelete={handleDelete}
                supportedModels={data?.supported_models ?? []}
              />
            ))}
            <button
              type="button"
              onClick={() => {
                setAddTarget({ strategy: "B", role: "challenger" });
                setNewModel(data?.supported_models?.[0]?.model ?? "");
              }}
              className="flex min-h-[200px] items-center justify-center rounded-[24px] border-2 border-dashed transition-colors hover:border-[var(--green)]"
              style={{ borderColor: "var(--line-soft)", color: "var(--text-tertiary)" }}
            >
              <span className="text-3xl">+</span>
            </button>
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

      {addTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setAddTarget(null)}>
          <div
            className="w-full max-w-md rounded-[24px] p-6 shadow-xl"
            style={{ background: "var(--bg-elevated)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
              {addTarget.strategy === "A" ? "Strategy A" : "Strategy B"} 역할 추가
            </h3>

            {addTarget.strategy === "B" && (
              <label className="mt-4 block">
                <span className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>역할</span>
                <select
                  value={addTarget.role}
                  onChange={(e) => setAddTarget({ ...addTarget, role: e.target.value })}
                >
                  <option value="proposer">Proposer</option>
                  <option value="challenger">Challenger</option>
                  <option value="synthesizer">Synthesizer</option>
                </select>
              </label>
            )}

            <label className="mt-4 block">
              <span className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>모델</span>
              <select value={newModel} onChange={(e) => setNewModel(e.target.value)}>
                {(data?.supported_models ?? []).map((m) => (
                  <option key={m.model} value={m.model}>{m.label} · {m.provider}</option>
                ))}
              </select>
            </label>

            <label className="mt-4 block">
              <span className="mb-1 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>페르소나</span>
              <textarea
                value={newPersona}
                onChange={(e) => setNewPersona(e.target.value)}
                rows={3}
                placeholder="이 역할의 분석 관점을 설명하세요"
                className="min-h-[96px]"
              />
            </label>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setAddTarget(null)}
              >
                취소
              </button>
              <button
                type="button"
                className="btn-primary disabled:opacity-50"
                disabled={!newModel || !newPersona.trim() || addMutation.isPending}
                onClick={handleAddRole}
              >
                {addMutation.isPending ? "추가 중..." : "추가"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
