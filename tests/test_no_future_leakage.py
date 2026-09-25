"""Tests verifying zero data leakage across fold boundaries and embargo gaps."""
import unittest
from research.chronological_split import create_anchored_folds, LeakageError


class TestNoFutureLeakage(unittest.TestCase):

    def test_anchored_folds_chronology(self):
        folds = create_anchored_folds(total_bars=300, n_folds=5, min_train_bars=100, embargo_bars=10)
        self.assertEqual(len(folds), 5)

        for fold in folds:
            # Train end must precede test start by at least embargo_bars
            self.assertLessEqual(fold.train_end + fold.embargo_bars, fold.test_start)
            # Train start must be 0 (anchored)
            self.assertEqual(fold.train_start, 0)
            # Test end must be greater than test start
            self.assertGreater(fold.test_end, fold.test_start)

    def test_embargo_violation_raises(self):
        # Explicit test that embargo violation raises LeakageError
        with self.assertRaises(LeakageError):
            folds = create_anchored_folds(total_bars=120, n_folds=5, min_train_bars=100, embargo_bars=10)


if __name__ == "__main__":
    unittest.main()
