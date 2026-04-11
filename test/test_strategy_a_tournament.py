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


class StrategyATournamentEdgeCaseTest(unittest.TestCase):
    """에지 케이스: 빈 입력, 경계값, ��단적 상황."""

    def test_select_winner_empty_rows(self) -> None:
        """빈 리스트 → 기본값 predictor_1."""
        winner = StrategyATournament._select_winner([], min_samples=3)
        self.assertEqual(winner, "predictor_1")

    def test_select_winner_single_row_qualified(self) -> None:
        """단일 후보자 — ��소 표본 충족."""
        rows = [{"agent_id": "predictor_1", "correct": 5, "total": 5}]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_1")

    def test_select_winner_all_zero_correct(self) -> None:
        """모든 후보의 correct=0 → ratio=0, total이 큰 후보 선택."""
        rows = [
            {"agent_id": "predictor_1", "correct": 0, "total": 10},
            {"agent_id": "predictor_2", "correct": 0, "total": 20},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_2")

    def test_select_winner_min_samples_one(self) -> None:
        """min_samples=1 → 모든 후보가 자격."""
        rows = [
            {"agent_id": "predictor_1", "correct": 1, "total": 1},
            {"agent_id": "predictor_2", "correct": 1, "total": 2},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=1)
        self.assertEqual(winner, "predictor_1")

    def test_select_winner_zero_total_excluded(self) -> None:
        """total=0인 후보는 제외."""
        rows = [
            {"agent_id": "predictor_1", "correct": 0, "total": 0},
            {"agent_id": "predictor_2", "correct": 3, "total": 5},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=1)
        self.assertEqual(winner, "predictor_2")

    def test_select_winner_none_values_treated_as_zero(self) -> None:
        """total/correct가 None이면 0으로 처리."""
        rows = [
            {"agent_id": "predictor_1", "correct": None, "total": None},
            {"agent_id": "predictor_2", "correct": 4, "total": 5},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_2")

    def test_select_winner_many_tied_candidates(self) -> None:
        """10명의 후보가 동일한 비율/샘플 → agent_id 오름차순."""
        rows = [
            {"agent_id": f"predictor_{i}", "correct": 5, "total": 10}
            for i in range(10, 0, -1)
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_1")

    def test_select_winner_perfect_ratio(self) -> None:
        """correct == total → ratio=1.0이 승리."""
        rows = [
            {"agent_id": "predictor_1", "correct": 100, "total": 100},
            {"agent_id": "predictor_2", "correct": 99, "total": 100},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_1")


class StrategyATournamentTieHandlingTest(unittest.TestCase):
    """동점 처리 및 추가 에지 케이스."""

    def test_select_winner_two_way_tie_ratio_same_total(self) -> None:
        """동일 ratio + 동일 total → agent_id 오름차순 타이브레이커."""
        rows = [
            {"agent_id": "predictor_5", "correct": 7, "total": 10},
            {"agent_id": "predictor_2", "correct": 7, "total": 10},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_2")

    def test_select_winner_negative_correct_treated_as_zero(self) -> None:
        """correct가 음수인 비정상 데이터 → int 변환 후 ratio 계산."""
        rows = [
            {"agent_id": "predictor_1", "correct": -1, "total": 5},
            {"agent_id": "predictor_2", "correct": 3, "total": 5},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_2")

    def test_select_winner_correct_exceeds_total(self) -> None:
        """correct > total 비정상 데이터 → ratio > 1.0이지만 동작."""
        rows = [
            {"agent_id": "predictor_1", "correct": 15, "total": 10},
            {"agent_id": "predictor_2", "correct": 8, "total": 10},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=3)
        self.assertEqual(winner, "predictor_1")

    def test_select_winner_large_min_samples(self) -> None:
        """min_samples가 매우 크면 아무도 자격 없음 → 기본값."""
        rows = [
            {"agent_id": "predictor_1", "correct": 90, "total": 100},
            {"agent_id": "predictor_2", "correct": 85, "total": 100},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=1000)
        self.assertEqual(winner, "predictor_1")

    def test_select_winner_only_one_qualified(self) -> None:
        """한 명만 min_samples를 충족하면 그 사람이 우승."""
        rows = [
            {"agent_id": "predictor_1", "correct": 1, "total": 2},
            {"agent_id": "predictor_2", "correct": 4, "total": 5},
            {"agent_id": "predictor_3", "correct": 1, "total": 1},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=5)
        self.assertEqual(winner, "predictor_2")

    def test_select_winner_mixed_none_and_valid(self) -> None:
        """일부 None + 일부 유효 데이터."""
        rows = [
            {"agent_id": "predictor_1", "correct": None, "total": 10},
            {"agent_id": "predictor_2", "correct": 5, "total": None},
            {"agent_id": "predictor_3", "correct": 7, "total": 10},
        ]
        winner = StrategyATournament._select_winner(rows, min_samples=5)
        self.assertEqual(winner, "predictor_3")


if __name__ == "__main__":
    unittest.main()
