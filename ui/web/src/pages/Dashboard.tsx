/**
 * ui/src/pages/Dashboard.tsx
 * Main dashboard page.
 */
import TossTradingDashboard from "@/components/TossTradingDashboard";
import StrategyDashboard from "@/components/StrategyDashboard";
import { usePortfolio, useTradingAccountOverview } from "@/hooks/usePortfolio";

export default function Dashboard() {
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio();
  const { data: accountOverview, isLoading: accountLoading } = useTradingAccountOverview();

  return (
    <>
      <TossTradingDashboard
        portfolio={portfolio ?? null}
        accountOverview={accountOverview ?? null}
        isLoading={portfolioLoading || accountLoading}
      />
      <div className="page-shell mt-6">
        <StrategyDashboard />
      </div>
    </>
  );
}
