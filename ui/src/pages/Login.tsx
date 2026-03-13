import { FormEvent, useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { api } from "@/utils/api";

type LoginResponse = {
  token: string;
  expires_in: number;
};

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const token = localStorage.getItem("alpha_token");

  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("admin1234");
  const [error, setError] = useState("");
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
      const { data } = await api.post<LoginResponse>("/auth/login", {
        email,
        password,
      });
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
    <div className="relative min-h-screen overflow-hidden bg-white px-4 py-8 md:px-10 md:py-14">
      <div className="pointer-events-none absolute -left-24 top-[-110px] h-72 w-72 rounded-full bg-[#EAF1FF] blur-2xl" />
      <div className="pointer-events-none absolute -right-24 bottom-[-120px] h-72 w-72 rounded-full bg-[#F2F4F6] blur-2xl" />

      <div className="relative mx-auto grid w-full max-w-5xl gap-5 md:grid-cols-[1.1fr_1fr]">
        <section className="rounded-[32px] bg-[#F2F4F6] px-6 py-7 shadow-[0_14px_30px_rgba(25,31,40,0.06)] md:px-7 md:py-8">
          <p className="text-[13px] font-semibold text-[#8B95A1]">ALPHA INVESTING</p>
          <h1 className="mt-2 text-[36px] font-extrabold leading-tight tracking-[-0.03em] text-[#191F28]">
            복잡한 투자,
            <br />
            쇼핑처럼 쉽게
          </h1>
          <p className="mt-3 max-w-sm text-sm text-[#8B95A1]">
            전략, 리스크, 실행 현황을 한 흐름으로 연결한 자동투자 대시보드입니다.
          </p>

          <div className="mt-5 grid grid-cols-2 gap-3">
            <div className="rounded-2xl bg-white px-3 py-3">
              <p className="text-[11px] font-semibold text-[#8B95A1]">Runtime</p>
              <p className="mt-1 text-sm font-bold text-[#191F28]">Docker Active</p>
            </div>
            <div className="rounded-2xl bg-white px-3 py-3">
              <p className="text-[11px] font-semibold text-[#8B95A1]">Mode</p>
              <p className="mt-1 text-sm font-bold text-[#191F28]">Paper Trading</p>
            </div>
          </div>
        </section>

        <section className="card w-full max-w-md justify-self-center md:max-w-none">
          <div className="mb-5">
            <p className="text-[12px] font-semibold text-[#8B95A1]">WELCOME BACK</p>
            <h2 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em] text-[#191F28]">로그인</h2>
            <p className="mt-2 text-sm text-[#8B95A1]">대시보드 접근을 위해 계정 인증이 필요합니다.</p>
          </div>

          <form className="space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="mb-1 block text-sm font-semibold text-[#191F28]">이메일</label>
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
              <label className="mb-1 block text-sm font-semibold text-[#191F28]">비밀번호</label>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error && <div className="rounded-2xl bg-[#FFECEC] px-3 py-2 text-sm text-[#C92A2A]">{error}</div>}

            <button type="submit" disabled={submitting} className="btn-primary w-full disabled:opacity-60">
              {submitting ? "로그인 중..." : "로그인"}
            </button>
          </form>

          <div className="mt-5 rounded-2xl bg-white px-3 py-2.5">
            <p className="text-xs text-[#8B95A1]">기본 테스트 계정</p>
            <p className="mt-1 text-xs font-semibold text-[#191F28]">admin@example.com / admin1234</p>
          </div>
          <p className="mt-4 text-[11px] text-[#8B95A1]">실거래 전환 전 Settings에서 readiness를 반드시 확인하세요.</p>
        </section>
      </div>
    </div>
  );
}
