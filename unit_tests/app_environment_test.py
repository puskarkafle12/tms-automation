import unittest

from config import app_environment
from utils.strategies.aliases import BUY_STRATEGIES, CANONICAL_STRATEGIES, SELL_STRATEGIES
from utils.strategies.handlers import HANDLERS


class TestAppEnvironment(unittest.TestCase):
    def test_default_environment_is_testing(self):
        self.assertTrue(app_environment.is_testing() or app_environment.is_production())

    def test_public_app_url_local_in_testing(self):
        original = app_environment.ENVIRONMENT
        try:
            app_environment.ENVIRONMENT = "test"
            self.assertEqual(app_environment.public_app_url(), "http://localhost:3000")
        finally:
            app_environment.ENVIRONMENT = original


class TestStrategyCatalogCoverage(unittest.TestCase):
    def test_handlers_cover_core_strategies(self):
        core = set(HANDLERS)
        expected_core = (CANONICAL_STRATEGIES - {"Time-Based Buy", "Time-Based Exit"})
        self.assertEqual(core, expected_core)

    def test_buy_and_sell_sets_match_handlers_plus_wrappers(self):
        self.assertEqual(
            CANONICAL_STRATEGIES,
            set(HANDLERS) | {"Time-Based Buy", "Time-Based Exit"},
        )
        self.assertEqual(len(BUY_STRATEGIES), 9)
        self.assertEqual(len(SELL_STRATEGIES), 9)


if __name__ == "__main__":
    unittest.main()
