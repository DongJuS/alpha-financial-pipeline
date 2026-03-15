/**
 * ui/src/pages/Notifications.tsx
 * 알림 센터 — 알림 목록 및 설정
 */
import { useNotificationPreferences, useUpdateNotificationPreferences } from "@/hooks/useNotifications";

export default function NotificationsPage() {
  const { data: prefs, isLoading } = useNotificationPreferences();
  const updatePrefs = useUpdateNotificationPreferences();

  function togglePref(key: string) {
    if (!prefs) return;
    updatePrefs.mutate({ ...prefs, [key]: !prefs[key as keyof typeof prefs] });
  }

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>알림</p>
        <h1 className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--text-primary)" }}>
          알림 센터
        </h1>
      </section>

      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>알림 설정</h3>
        {isLoading ? (
          <div className="mt-3 h-40 skeleton" />
        ) : prefs ? (
          <div className="mt-3 space-y-3">
            {Object.entries(prefs).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between rounded-xl p-3" style={{ background: "var(--bg-secondary)" }}>
                <span className="text-sm" style={{ color: "var(--text-primary)" }}>{key.replace(/_/g, " ")}</span>
                <button
                  onClick={() => togglePref(key)}
                  className="rounded-full px-3 py-1 text-xs font-semibold"
                  style={{
                    background: value ? "var(--green-bg)" : "var(--bg-secondary)",
                    color: value ? "var(--green)" : "var(--text-secondary)",
                    border: `1px solid ${value ? "var(--green)" : "var(--border)"}`,
                  }}
                >
                  {value ? "ON" : "OFF"}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm" style={{ color: "var(--text-secondary)" }}>알림 설정을 불러올 수 없습니다.</p>
        )}
      </div>
    </div>
  );
}
