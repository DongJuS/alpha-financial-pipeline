import { NavLink, Outlet, useNavigate } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/dashboard", label: "홈", description: "자산 현황" },
  { to: "/strategy", label: "전략", description: "A/B 교차검증" },
  { to: "/market", label: "마켓", description: "실시간 데이터" },
  { to: "/long-term", label: "장기투자", description: "준비 중인 화면" },
  { to: "/paper-trading", label: "모의 투자", description: "KIS 페이퍼 계좌" },
  { to: "/portfolio", label: "내 계좌", description: "성과와 리스크" },
  { to: "/settings", label: "설정", description: "운영 정책" },
];

function BrandMark() {
  return (
    <div
      className="flex h-12 w-12 items-center justify-center rounded-2xl"
      style={{
        background: "linear-gradient(135deg, var(--brand-500), #49a3ff)",
        boxShadow: "0 18px 32px rgba(31, 99, 247, 0.28)",
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width="22"
        height="22"
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

function navClass(isActive: boolean) {
  return [
    "group flex min-w-fit items-center gap-2 rounded-2xl px-3 py-2.5 transition-all",
    isActive ? "text-white shadow-lg" : "text-slate-600 hover:-translate-y-0.5 hover:bg-white/80 hover:text-slate-900",
  ].join(" ");
}

export default function Layout() {
  const navigate = useNavigate();

  function handleLogout() {
    localStorage.removeItem("alpha_token");
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen pb-8">
      <header className="sticky top-0 z-40 px-3 pt-3 md:px-5">
        <div
          className="mx-auto max-w-[1280px] rounded-[30px] border border-white/70 px-4 py-4 shadow-[0_18px_48px_rgba(15,23,42,0.08)] backdrop-blur-xl md:px-6"
          style={{ background: "rgba(249, 251, 255, 0.84)" }}
        >
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="flex items-start gap-3">
                <BrandMark />
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="text-[20px] font-bold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
                      투자 Agent
                    </h1>
                    <span className="eyebrow">Capital protection first</span>
                  </div>
                  <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    의심스러울 때는 HOLD. 전략 A/B를 교차 검증하며 자본을 먼저 지키는 투자 오퍼레이션.
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 md:justify-end">
                <div
                  className="hidden rounded-full px-3 py-1.5 text-xs font-semibold md:inline-flex"
                  style={{ background: "var(--green-bg)", color: "var(--green)" }}
                >
                  Paper-first protocol
                </div>
                <button onClick={handleLogout} className="btn-secondary">
                  로그아웃
                </button>
              </div>
            </div>

            <div className="hidden items-center justify-between gap-4 md:flex">
              <nav className="flex flex-wrap items-center gap-2">
                {NAV_ITEMS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) => navClass(isActive)}
                    style={({ isActive }) =>
                      isActive
                        ? {
                            background: "linear-gradient(135deg, var(--brand-500), #4b9dff)",
                          }
                        : undefined
                    }
                  >
                    <span className="text-sm font-semibold">{item.label}</span>
                    <span className="text-[11px] font-medium opacity-70">{item.description}</span>
                  </NavLink>
                ))}
              </nav>

              <div className="flex items-center gap-2 text-xs font-semibold">
                <span className="chip">투명성 로그 90일</span>
                <span className="chip">신뢰도 0.6 미만 HOLD</span>
                <span className="chip">데이터 30분 초과 시 예측 중단</span>
              </div>
            </div>

            <nav className="flex gap-2 overflow-x-auto pb-1 md:hidden">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    [
                      "whitespace-nowrap rounded-2xl px-3 py-2 text-sm font-semibold transition-all",
                      isActive ? "text-white shadow-lg" : "text-slate-600",
                    ].join(" ")
                  }
                  style={({ isActive }) =>
                    isActive
                      ? { background: "linear-gradient(135deg, var(--brand-500), #4b9dff)" }
                      : { background: "rgba(255, 255, 255, 0.72)" }
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </div>
      </header>

      <main className="relative z-10">
        <Outlet />
      </main>
    </div>
  );
}
