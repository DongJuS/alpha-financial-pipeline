/**
 * ui/src/pages/Notifications.tsx
 * 알림 센터 — 알림 설정 + 히스토리 + 통계 + 테스트 발송
 */
import { useState } from "react";
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
  useNotificationStats,
  useNotificationHistory,
  useSendTestNotification,
} from "@/hooks/useNotifications";

function StatsCards({ stats }: { stats: any }) {
  return (
    <div className="grid gap-3 md:grid-cols-4">
      <div className="card">
        <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>총 발송</p>
        <p className="mt-1 text-xl font-bold" style={{ color: "var(--text-primary)" }}>
          {stats.total_sent?.toLocaleString() ?? 0}
        </p>
      </div>
      <div className="card">
        <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>성공률</p>
        <p className="mt-1 text-xl font-bold" style={{ color: "var(--green)" }}>
          {stats.success_rate != null ? `${(stats.success_rate * 100).toFixed(1)}%` : "—"}
        </p>
      </div>
      {stats.by_type &&
        Object.entries(stats.by_type).map(([type, count]) => (
          <div key={type} className="card">
            <p className="text-[11px] font-medium" style={{ color: "var(--text-tertiary)" }}>{type}</p>
            <p className="mt-1 text-xl font-bold" style={{ color: "var(--text-primary)" }}>
              {(count as number).toLocaleString()}
            </p>
          </div>
        ))}
    </div>
  );
}

export default function NotificationsPage() {
  const { data: prefs, isLoading: prefsLoading } = useNotificationPreferences();
  const updatePrefs = useUpdateNotificationPreferences();
  const { data: stats } = useNotificationStats();
  const { data: history, isLoading: historyLoading } = useNotificationHistory(20);
  const sendTest = useSendTestNotification();
  const [testMsg, setTestMsg] = useState("테스트 알림입니다.");

  function togglePref(key: string) {
    if (!prefs) return;
    updatePrefs.mutate({ ...prefs, [key]: !prefs[key as keyof typeof prefs] });
  }

  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <p className="text-[13px] font-semibold" style={{ color: "var(--text-secondary)" }}>알림</p>
        <h1
          className="mt-1 text-[30px] font-extrabold tracking-[-0.03em]"
          style={{ color: "var(--text-primary)" }}
        >
          알림 센터
        </h1>
      </section>

      {stats && <StatsCards stats={stats} />}

      {/* 테스트 발송 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>테스트 발송</h3>
        <div className="mt-3 flex gap-2">
          <input
            type="text"
            value={testMsg}
            onChange={(e) => setTestMsg(e.target.value)}
            className="flex-1 rounded-xl border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
            placeholder="테스트 메시지를 입력하세요"
          />
          <button
            className="rounded-xl px-4 py-2 text-sm font-semibold text-white"
            style={{ background: "var(--brand-500)" }}
            onClick={() => sendTest.mutate({ message: testMsg, channel: "telegram" })}
            disabled={sendTest.isPending}
          >
            {sendTest.isPending ? "발송 중..." : "발송"}
          </button>
        </div>
        {sendTest.isSuccess && (
          <p className="mt-2 text-xs" style={{ color: "var(--green)" }}>
            테스트 알림이 발송되었습니다.
          </p>
        )}
        {sendTest.isError && (
          <p className="mt-2 text-xs" style={{ color: "var(--red)" }}>
            발송에 실패했습니다.
          </p>
        )}
      </div>

      {/* 알림 설정 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>알림 설정</h3>
        {prefsLoading ? (
          <div className="mt-3 h-40 skeleton" />
        ) : prefs ? (
          <div className="mt-3 space-y-3">
            {Object.entries(prefs).map(([key, value]) => (
              <div
                key={key}
                className="flex items-center justify-between rounded-xl p-3"
                style={{ background: "var(--bg-secondary)" }}
              >
                <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                  {key.replace(/_/g, " ")}
                </span>
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
          <p className="mt-3 text-sm" style={{ color: "var(--text-secondary)" }}>
            알림 설정을 불러올 수 없습니다.
          </p>
        )}
      </div>

      {/* 알림 히스토리 */}
      <div className="card">
        <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>최근 알림 히스토리</h3>
        {historyLoading ? (
          <div className="mt-3 h-40 skeleton" />
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>시간</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>채널</th>
                  <th className="pb-2 font-semibold" style={{ color: "var(--text-secondary)" }}>내용</th>
                  <th className="pb-2 font-semibold text-right" style={{ color: "var(--text-secondary)" }}>
                    상태
                  </th>
                </tr>
              </thead>
              <tbody>
                {(history ?? []).map((item, i) => (
                  <tr key={i} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="py-2 font-mono text-[11px]" style={{ color: "var(--text-secondary)" }}>
                      {item.sent_at?.slice(0, 16).replace("T", " ")}
                    </td>
                    <td className="py-2 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                      {item.channel}
                    </td>
                    <td
                      className="max-w-xs truncate py-2 text-xs"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {item.message}
                    </td>
                    <td className="py-2 text-right">
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                        style={{
                          background: item.status === "success" ? "var(--green-bg)" : "var(--red-bg)",
                          color: item.status === "success" ? "var(--green)" : "var(--red)",
                        }}
                      >
                        {item.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(history ?? []).length === 0 && (
              <p className="py-6 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>
                알림 기록이 없습니다.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
