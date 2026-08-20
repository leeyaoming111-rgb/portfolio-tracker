import unittest

import numpy as np

from portfolio_optimizer import (
    build_optimization_report,
    size_candidate_position,
)


class PortfolioOptimizerTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        days = 180
        market = rng.normal(0.0004, 0.01, days)
        defensive = rng.normal(0.0002, 0.006, days)
        self.returns = {
            "US.AAA": market + rng.normal(0, 0.008, days),
            "US.BBB": market * 0.9 + rng.normal(0, 0.009, days),
            "US.CCC": defensive + rng.normal(0, 0.004, days),
        }
        self.positions = [
            {"code": "US.AAA", "stock_name": "AAA", "weight_pct": 45.0, "val_nzd": 45000},
            {"code": "US.BBB", "stock_name": "BBB", "weight_pct": 35.0, "val_nzd": 35000},
            {"code": "US.CCC", "stock_name": "CCC", "weight_pct": 20.0, "val_nzd": 20000},
        ]

    def test_report_returns_normalized_hrp_weights_and_risk_metrics(self):
        report = build_optimization_report(
            self.positions,
            self.returns,
            total_nav=110000,
            cash_nzd=10000,
            max_weight_pct=60,
        )

        self.assertAlmostEqual(sum(row["hrp_weight_pct"] for row in report["positions"]), 100.0, places=1)
        self.assertGreater(report["metrics"]["annualized_volatility_pct"], 0)
        self.assertGreaterEqual(report["metrics"]["effective_positions"], 1)
        self.assertEqual(report["coverage"]["used_positions"], 3)
        self.assertEqual(report["method"], "hierarchical_risk_parity")

    def test_report_excludes_assets_without_enough_history(self):
        returns = {**self.returns, "US.SHORT": np.array([0.01, -0.01] * 10)}
        positions = self.positions + [
            {"code": "US.SHORT", "stock_name": "SHORT", "weight_pct": 5.0, "val_nzd": 5000}
        ]

        report = build_optimization_report(
            positions,
            returns,
            total_nav=115000,
            cash_nzd=10000,
            min_observations=60,
        )

        self.assertIn("US.SHORT", report["coverage"]["excluded_tickers"])
        short_row = next(row for row in report["positions"] if row["code"] == "US.SHORT")
        self.assertIsNone(short_row["hrp_weight_pct"])

    def test_candidate_sizing_is_capped_by_cash_and_position_limit(self):
        candidate = self.returns["US.CCC"] + np.random.default_rng(9).normal(0, 0.003, 180)
        result = size_candidate_position(
            positions=self.positions,
            existing_returns=self.returns,
            candidate_code="US.NEW",
            candidate_returns=candidate,
            expected_return_pct=30,
            conviction=4,
            total_nav=110000,
            available_cash_nzd=3000,
            current_position_nzd=0,
            candidate_price_nzd=100,
            max_position_pct=10,
        )

        self.assertLessEqual(result["suggested_trade_nzd"], 3000)
        self.assertLessEqual(result["suggested_total_weight_pct"], 10)
        self.assertEqual(result["suggested_shares"], 30)
        self.assertFalse(result["requires_sale"])

    def test_candidate_sizing_never_recommends_negative_trade(self):
        result = size_candidate_position(
            positions=self.positions,
            existing_returns=self.returns,
            candidate_code="US.AAA",
            candidate_returns=self.returns["US.AAA"],
            expected_return_pct=5,
            conviction=1,
            total_nav=110000,
            available_cash_nzd=5000,
            current_position_nzd=45000,
            candidate_price_nzd=100,
            max_position_pct=10,
        )

        self.assertEqual(result["suggested_trade_nzd"], 0)
        self.assertGreater(result["current_weight_pct"], result["suggested_total_weight_pct"])
        self.assertTrue(result["requires_sale"])


if __name__ == "__main__":
    unittest.main()
