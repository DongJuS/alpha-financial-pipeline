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
    <div className="min-h-screen bg-surface-muted flex items-center justify-center p-6">
      <div className="w-full max-w-md card">
        <div className="mb-6">
          <p className="text-xs uppercase tracking-wide text-gray-500">Alpha Trading System</p>
          <h1 className="text-2xl font-bold text-gray-900 mt-1">로그인</h1>
          <p className="text-sm text-gray-500 mt-2">대시보드 접근을 위해 계정 인증이 필요합니다.</p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">이메일</label>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-surface-border rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
              placeholder="admin@example.com"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">비밀번호</label>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-surface-border rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
            />
          </div>

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full px-4 py-2 bg-brand text-white rounded-xl text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-60"
          >
            {submitting ? "로그인 중..." : "로그인"}
          </button>
        </form>

        <p className="text-xs text-gray-400 mt-5">기본 테스트 계정: admin@example.com / admin1234</p>
      </div>
    </div>
  );
}
