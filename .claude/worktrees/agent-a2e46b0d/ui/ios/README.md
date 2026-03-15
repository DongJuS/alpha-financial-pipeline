# iOS UI Notes

This folder is reserved for iPhone-specific UI work.

Current direction:
- Keep the laptop web UI as the source of truth for product structure.
- Rebuild mobile screens through content reflow, not by shrinking the desktop layout.
- Add iOS-specific polish here only when we need it:
  - bottom navigation patterns
  - safe-area support
  - larger touch targets
  - mobile-first card ordering
  - Safari/PWA interaction tuning

Suggested next steps:
1. Define shared tokens that can be reused from `ui/web`.
2. Extract mobile navigation and page-shell patterns.
3. Build iPhone dashboard, strategy, and portfolio views around the same API contracts.
