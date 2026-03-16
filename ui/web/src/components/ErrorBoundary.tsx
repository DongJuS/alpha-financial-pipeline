import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "var(--bg-primary, #f8f9fa)",
            padding: "2rem",
          }}
        >
          <div
            style={{
              maxWidth: 480,
              width: "100%",
              background: "var(--bg-elevated, #fff)",
              borderRadius: 24,
              padding: "2rem",
              boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
              textAlign: "center",
            }}
          >
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: "50%",
                background: "var(--loss-bg, #fee2e2)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 1rem",
                fontSize: 24,
              }}
            >
              !
            </div>
            <h2
              style={{
                fontSize: 20,
                fontWeight: 700,
                color: "var(--text-primary, #1a1a2e)",
                marginBottom: 8,
              }}
            >
              예기치 않은 오류가 발생했습니다
            </h2>
            <p
              style={{
                fontSize: 14,
                color: "var(--text-secondary, #6b7280)",
                marginBottom: 16,
                lineHeight: 1.5,
              }}
            >
              화면을 다시 불러오거나, 문제가 지속되면 새로고침해 주세요.
            </p>
            {this.state.error && (
              <pre
                style={{
                  fontSize: 11,
                  color: "var(--loss, #dc2626)",
                  background: "var(--loss-bg, #fee2e2)",
                  borderRadius: 12,
                  padding: "0.75rem 1rem",
                  textAlign: "left",
                  overflow: "auto",
                  maxHeight: 120,
                  marginBottom: 16,
                }}
              >
                {this.state.error.message}
              </pre>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
              <button
                onClick={this.handleReset}
                style={{
                  padding: "10px 20px",
                  borderRadius: 12,
                  fontSize: 14,
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                  background: "var(--brand-500, #3b82f6)",
                  color: "#fff",
                }}
              >
                다시 시도
              </button>
              <button
                onClick={() => window.location.reload()}
                style={{
                  padding: "10px 20px",
                  borderRadius: 12,
                  fontSize: 14,
                  fontWeight: 600,
                  border: "1px solid var(--line-soft, #e5e7eb)",
                  cursor: "pointer",
                  background: "transparent",
                  color: "var(--text-primary, #1a1a2e)",
                }}
              >
                새로고침
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
