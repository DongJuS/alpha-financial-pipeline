/**
 * ui/src/pages/Dashboard.tsx
 * Main dashboard page.
 */
import TossTradingDashboard from "@/components/TossTradingDashboard";
import { usePortfolio } from "@/hooks/usePortfolio";

export default function Dashboard() {
  const { data: portfolio, isLoading } = usePortfolio();

  return <TossTradingDashboard portfolio={portfolio ?? null} isLoading={isLoading} />;
}
