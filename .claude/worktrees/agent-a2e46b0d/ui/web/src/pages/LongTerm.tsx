export default function LongTerm() {
  return (
    <div className="page-shell space-y-5">
      <section className="hero-section">
        <span className="eyebrow">Long-term investing</span>
        <h1
          className="mt-4 text-[32px] font-extrabold tracking-[-0.04em]"
          style={{ color: "var(--text-primary)" }}
        >
          장기투자
        </h1>
        <p className="mt-3 max-w-[720px] text-sm leading-6 md:text-base" style={{ color: "var(--text-secondary)" }}>
          장기 관점의 포트폴리오와 운용 원칙을 정리할 전용 화면입니다. 세부 콘텐츠는 다음 단계에서 채워도
          되도록 기본 라우트만 먼저 열어두었습니다.
        </p>
      </section>

      <section className="card">
        <p className="text-base font-bold tracking-[-0.02em]" style={{ color: "var(--text-primary)" }}>
          준비 중
        </p>
        <p className="mt-2 text-sm leading-6" style={{ color: "var(--text-secondary)" }}>
          장기투자 전략, 리밸런싱 기준, 자산 배분 화면은 이후 단계에서 여기에 연결할 수 있습니다.
        </p>
      </section>
    </div>
  );
}
