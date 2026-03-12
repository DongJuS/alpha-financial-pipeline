/**
 * ui/src/components/Layout.tsx — 사이드바 + 메인 영역 레이아웃
 */
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAppStore } from "@/stores/useAppStore";

const NAV_ITEMS = [
  { to: "/dashboard", label: "대시보드", icon: "📊" },
  { to: "/strategy", label: "전략 현황", icon: "🧠" },
  { to: "/portfolio", label: "포트폴리오", icon: "💼" },
  { to: "/market", label: "시장 데이터", icon: "📈" },
  { to: "/settings", label: "설정", icon: "⚙️" },
];

export default function Layout() {
  const { sidebarOpen, toggleSidebar } = useAppStore();
  const navigate = useNavigate();

  function handleLogout() {
    localStorage.removeItem("alpha_token");
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex h-screen bg-surface-muted">
      {/* 사이드바 */}
      <aside
        className={`
          ${sidebarOpen ? "w-60" : "w-16"}
          bg-white border-r border-surface-border
          flex flex-col transition-all duration-200 ease-in-out
          shrink-0
        `}
      >
        {/* 로고 */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-surface-border">
          <span className="text-2xl">⚡</span>
          {sidebarOpen && (
            <span className="text-lg font-bold text-gray-900">Alpha</span>
          )}
        </div>

        {/* 네비게이션 */}
        <nav className="flex-1 px-2 py-4 space-y-1">
          {NAV_ITEMS.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors
                ${isActive
                  ? "bg-brand-50 text-brand"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                }`
              }
            >
              <span className="text-xl shrink-0">{icon}</span>
              {sidebarOpen && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="px-2 pb-2 space-y-1">
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 text-sm"
          >
            <span>🚪</span>
            {sidebarOpen && <span>로그아웃</span>}
          </button>
          <button
            onClick={toggleSidebar}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-100 text-sm"
          >
            <span>{sidebarOpen ? "◀" : "▶"}</span>
            {sidebarOpen && <span>사이드바 접기</span>}
          </button>
        </div>
      </aside>

      {/* 메인 영역 */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
