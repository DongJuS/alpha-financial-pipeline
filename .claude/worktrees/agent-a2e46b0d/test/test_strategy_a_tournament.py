import unittest

from src.agents.strategy_a_tournament import StrategyATournament


class StrategyATournamentWinnerSelectionTest(unittest.TestCase):
    def test_select_winner_returns_default_when_no_qualified_samples(self) -> None:
        rows = [
            {"agent_id": "predictor_1", "correct": 1, "total": 1},
            {"agent_id": "predictor_2", "correct": 2, "total": 2},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_1")

    def test_select_winner_prefers_higher_ratio_then_total(self) -> None:
        rows = [
            {"agent_id": "predictor_1", "correct": 4, "total": 5},  # 0.80
            {"agent_id": "predictor_2", "correct": 8, "total": 10},  # 0.80 (표본 더 큼)
            {"agent_id": "predictor_3", "correct": 6, "total": 10},  # 0.60
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_2")

    def test_select_winner_uses_agent_id_as_final_tie_breaker(self) -> None:
        rows = [
            {"agent_id": "predictor_3", "correct": 4, "total": 5},
            {"agent_id": "predictor_1", "correct": 4, "total": 5},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_1")


if __name__ == "__main__":
    unittest.main()
