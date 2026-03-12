/**
 * ui/src/components/Layout.tsx — Toss-like navigation shell
 */
import { NavLink, Outlet, useNavigate } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/dashboard", label: "홈" },
  { to: "/strategy", label: "Strategy A/B" },
  { to: "/market", label: "주식 관리" },
  { to: "/portfolio", label: "내 계좌" },
  { to: "/settings", label: "설정" },
];

export default function Layout() {
  const navigate = useNavigate();

  function handleLogout() {
    localStorage.removeItem("alpha_token");
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-30 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-[68px] w-full max-w-[1180px] items-center justify-between px-4 md:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-[10px] w-[10px] items-center justify-center rounded-[3px] bg-[#0019FF] text-white">
              <svg viewBox="0 0 24 24" className="h-[10px] w-[10px] fill-none stroke-current stroke-[2]">
                <path d="M13 2L4 14h6l-1 8 9-12h-6z" />
              </svg>
            </div>
            <div>
              <p className="text-[16px] font-extrabold tracking-[-0.02em] text-[#191F28]">투자 Agent</p>
              <p className="text-[11px] font-medium text-[#8B95A1]">복잡한 주식을 더 쉽게</p>
            </div>
          </div>

          <nav className="hidden items-center gap-1.5 md:flex">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-full px-4 py-2 text-sm font-semibold transition-all duration-200 ${
                    isActive
                      ? "bg-[#0019FF] text-white shadow-[0_8px_18px_rgba(0,25,255,0.26)]"
                      : "bg-[#F2F4F6] text-[#4E5968] hover:scale-105"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <button onClick={handleLogout} className="btn-secondary h-9 px-4 text-xs md:text-sm">
            로그아웃
          </button>
        </div>

        <div className="mx-auto flex w-full max-w-[1180px] gap-2 overflow-x-auto px-4 pb-3 md:hidden md:px-8">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-full px-3.5 py-2 text-xs font-semibold transition-all ${
                  isActive ? "bg-[#0019FF] text-white" : "bg-[#F2F4F6] text-[#4E5968]"
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
