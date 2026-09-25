"""Strict chronological dataset splitting with embargo controls to prevent future-data leakage."""
from dataclasses import dataclass
from typing import Dict, List, Tuple


class LeakageError(ValueError):
    """Raised if any train observation overlaps with or succeeds test observations."""
    pass


@dataclass(frozen=True)
class ChronologicalFold:
    """Represents a single anchored walk-forward fold."""
    fold_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    embargo_bars: int

    def validate(self):
        """Assert strict chronological causality and embargo boundary."""
        if self.train_start > self.train_end:
            raise LeakageError(f"Invalid train range in fold {self.fold_index}")
        if self.test_start > self.test_end:
            raise LeakageError(f"Invalid test range in fold {self.fold_index}")
        if self.train_end + self.embargo_bars > self.test_start:
            raise LeakageError(
                f"Embargo violated in fold {self.fold_index}: train_end={self.train_end}, "
                f"test_start={self.test_start}, embargo={self.embargo_bars}"
            )


def create_anchored_folds(
    total_bars: int,
    n_folds: int = 5,
    min_train_bars: int = 100,
    embargo_bars: int = 10,
) -> List[ChronologicalFold]:
    """
    Generate anchored walk-forward folds where training sets expand forward in time
    and test sets are strictly non-overlapping out-of-sample segments with an embargo buffer.
    """
    if total_bars < min_train_bars + embargo_bars + n_folds * 10:
        raise LeakageError(f"Insufficient total bars ({total_bars}) for {n_folds} anchored folds")

    available_test_bars = total_bars - min_train_bars - embargo_bars
    test_fold_size = available_test_bars // n_folds

    if test_fold_size < 5:
        raise LeakageError(f"Test fold size too small ({test_fold_size} bars)")

    folds = []
    current_test_start = min_train_bars + embargo_bars

    for fold_idx in range(n_folds):
        train_start = 0
        train_end = current_test_start - embargo_bars - 1
        test_start = current_test_start

        if fold_idx == n_folds - 1:
            test_end = total_bars - 1
        else:
            test_end = test_start + test_fold_size - 1

        fold = ChronologicalFold(
            fold_index=fold_idx + 1,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            embargo_bars=embargo_bars,
        )
        fold.validate()
        folds.append(fold)
        current_test_start = test_end + 1

    return folds
