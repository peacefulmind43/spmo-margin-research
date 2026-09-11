"""Validation only; account transition maths stays in the two simulators."""
import numpy as np


def time_input(value, shape, name):
    arr = np.asarray(value, dtype=float)
    if arr.ndim and arr.shape not in {shape, (shape[-1],)}:
        raise ValueError(f"{name} must be scalar, horizon-length, or paths-shaped")
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} must be finite")
    return np.broadcast_to(arr, shape)


def validate_account(leverage, equity, cost, slippage, band, shield,
                     contribution, max_leverage, max_loan, resuming=False):
    values = [leverage, equity, cost, slippage, band, shield, contribution]
    if not np.isfinite(values).all() or leverage < 0 or equity <= 0:
        raise ValueError("finite nonnegative leverage and positive equity required")
    if not (0 <= cost < 1 and 0 <= slippage < 1 and band >= 0 and 0 <= shield <= 1):
        raise ValueError("invalid cost, slippage, band or tax shield")
    if contribution < 0:
        raise ValueError("use the explicit withdrawals input for withdrawals")
    if max_leverage is not None and (not np.isfinite(max_leverage) or max_leverage < 1 or leverage > max_leverage):
        raise ValueError("initial leverage exceeds the configured opening limit")
    if max_loan < 0 or np.isnan(max_loan) or (not resuming and equity * (leverage - 1) > max_loan):
        raise ValueError("initial borrowing exceeds the configured loan limit")
    if leverage * cost >= 1:
        raise ValueError("transaction cost is too large for this leverage")
