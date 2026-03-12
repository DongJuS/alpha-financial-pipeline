/**
 * ui/src/components/Layout.tsx — Toss-like top navigation layout
 */
import { NavLink, Outlet, useNavigate } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/dashboard", label: "대시보드" },
  { to: "/strategy", label: "전략" },
  { to: "/portfolio", label: "포트폴리오" },
  { to: "/market", label: "시장" },
  { to: "/settings", label: "설정" },
];

export default function Layout() {
  const navigate = useNavigate();

  function handleLogout() {
    localStorage.removeItem("alpha_token");
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-[#F7F9FC]">
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/92 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-[1120px] items-center justify-between px-5 md:px-8">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#3182F6] text-white">
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-[2]">
                <path d="M13 2L4 14h6l-1 8 9-12h-6z" />
              </svg>
            </div>
            <div>
              <p className="text-[15px] font-extrabold tracking-[-0.02em] text-[#191F28]">Alpha Trade</p>
              <p className="text-[11px] text-[#8B95A1]">Autonomous Investing</p>
            </div>
          </div>

          <nav className="hidden items-center gap-1 md:flex">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-xl px-3 py-2 text-sm font-semibold transition-colors ${
                    isActive ? "bg-[#E8F3FF] text-[#2563EB]" : "text-[#4E5968] hover:bg-[#F2F4F6]"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <button onClick={handleLogout} className="btn-secondary h-9 px-3 text-xs md:text-sm">
            로그아웃
          </button>
        </div>
        <div className="mx-auto flex w-full max-w-[1120px] gap-2 overflow-x-auto px-5 pb-3 md:hidden md:px-8">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${
                  isActive ? "bg-[#E8F3FF] text-[#2563EB]" : "bg-[#F2F4F6] text-[#4E5968]"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  );
}
