import { FormEvent, useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "@/utils/api";

type LoginResponse = {
  token: string;
  expires_in: number;
};

const PRINCIPLES = [
  {
    title: "자본 보호",
    body: "일일 손실 제한과 종목 비중 캡은 어떤 LLM 출력보다 우선합니다.",
  },
  {
    title: "투명성",
    body: "모든 시그널은 이유와 함께 기록되며, 토론 전문도 추적 가능합니다.",
  },
  {
    title: "정확성",
    body: "데이터가 오래되었거나 확신이 낮으면 기본값은 BUY가 아니라 HOLD입니다.",
  },
];

function BrandMark() {
  return (
    <div
      className="flex h-14 w-14 items-center justify-center rounded-[20px]"
      style={{
        background: "linear-gradient(135deg, var(--brand-500), #49a3ff)",
        boxShadow: "0 24px 46px rgba(31, 99, 247, 0.26)",
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width="26"
        height="26"
        fill="none"
        stroke="white"
        strokeWidth="2.3"
        aria-hidden="true"
      >
        <path d="M13 2L4 14h6l-1 8 9-12h-6z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const token = localStorage.getItem("alpha_token");

  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("admin1234");
  const [error, setError] = useState(
    searchParams.get("expired") === "true"
      ? "세션이 만료되었습니다. 다시 로그인해 주세요."
      : ""
  );
  const [submitting, setSubmitting] = useState(false);

  const redirectPath = useMemo(() => {
    const fromState = (location.state as { from?: string } | null)?.from;
    return fromState && fromState.startsWith("/") ? fromState : "/dashboard";
  }, [location.state]);

  if (token) {
    return <Navigate to="/dashboard" replace />;
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError("");
    try {
      const { data } = await api.post<LoginResponse>("/auth/login", { email, password });
      localStorage.setItem("alpha_token", data.token);
      navigate(redirectPath, { replace: true });
    } catch (err: unknown) {
      const fallback = "로그인에 실패했습니다. 이메일/비밀번호를 확인하세요.";
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : fallback);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden px-4 py-8 md:px-6">
      <div className="mx-auto grid min-h-[calc(100vh-4rem)] w-full max-w-[1240px] gap-6 lg:grid-cols-[1.1fr_420px] lg:items-center">
        <section className="hero-section p-7 md:p-10">
          <div className="max-w-[620px] space-y-6">
            <div className="flex items-center gap-4">
              <BrandMark />
              <div>
                <span className="eyebrow">SOUL operating system</span>
                <h1
                  className="mt-3 text-[36px] font-extrabold leading-tight tracking-[-0.04em] md:text-[52px]"
                  style={{ color: "var(--text-primary)" }}
                >
                  투자보다 먼저,
                  <br />
                  자본을 지키는 AI.
                </h1>
              </div>
            </div>

            <p className="max-w-[560px] text-base md:text-lg" style={{ color: "var(--text-secondary)" }}>
              Toss 투자 UX의 명확한 정보 위계와 미래지향적 인터페이스 감각을 결합해, 실시간 시장 데이터와
              전략 토론을 한 화면에서 투명하게 운영합니다.
            </p>

            <div className="grid gap-3 md:grid-cols-3">
              {PRINCIPLES.map((item) => (
                <article key={item.title} className="inner-card h-full">
                  <p className="text-sm font-bold tracking-[-0.02em]" style={{ color: "var(--text-primary)" }}>
                    {item.title}
                  </p>
                  <p className="mt-2 text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
                    {item.body}
                  </p>
                </article>
              ))}
            </div>

            <div className="flex flex-wrap gap-2">
              <span className="chip">Paper trading default</span>
              <span className="chip">Conflict to HOLD</span>
              <span className="chip">Freshness 30m guard</span>
              <span className="chip">Confidence floor 0.6</span>
            </div>
          </div>
        </section>

        <section className="card p-7 md:p-8">
          <div className="space-y-1">
            <span className="eyebrow">Access console</span>
            <h2 className="mt-3 text-[28px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
              대시보드 로그인
            </h2>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              실시간 전략, 포트폴리오, 운영 정책을 같은 컨텍스트에서 관리합니다.
            </p>
          </div>

          <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="mb-2 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                이메일
              </label>
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@example.com"
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                비밀번호
              </label>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error && (
              <div
                className="rounded-2xl px-4 py-3 text-sm"
                style={{ background: "var(--profit-bg)", color: "var(--profit)" }}
              >
                {error}
              </div>
            )}

            <button type="submit" disabled={submitting} className="btn-primary w-full disabled:opacity-50">
              {submitting ? "로그인 중..." : "대시보드 열기"}
            </button>
          </form>

          <div className="mt-5 grid gap-3">
            <div className="inner-card">
              <p className="text-xs font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
                Test account
              </p>
              <p className="mt-2 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                admin@example.com / admin1234
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <div className="inner-card">
                <p className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>
                  Trading mode
                </p>
                <p className="mt-2 text-sm font-semibold" style={{ color: "var(--green)" }}>
                  Paper trading active
                </p>
              </div>
              <div className="inner-card">
                <p className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>
                  Audit posture
                </p>
                <p className="mt-2 text-sm font-semibold" style={{ color: "var(--brand-500)" }}>
                  Decision logging enabled
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
