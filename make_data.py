"""Synthetic retail-loan book for the lab. No real customer data; everything is generated."""
from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENTS = ["Salaried", "Self-employed", "SME", "Agri"]
PRODUCTS = ["Personal loan", "Auto loan", "Credit card", "Home loan"]
REGIONS = ["North", "South", "East", "West"]


def loan_book(n: int = 2000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    seg = rng.choice(SEGMENTS, n, p=[0.5, 0.25, 0.15, 0.10])
    prod = rng.choice(PRODUCTS, n, p=[0.35, 0.25, 0.25, 0.15])
    score = np.clip(rng.normal(690, 70, n), 300, 900).round().astype(int)
    income = np.round(rng.lognormal(11.0, 0.5, n), -2)
    amount = np.round(income * rng.uniform(0.5, 6.0, n), -3)
    dti = np.round(np.clip(rng.normal(0.38, 0.14, n), 0.05, 0.95), 3)
    tenure = rng.choice([12, 24, 36, 48, 60, 84], n)
    dpd = rng.choice([0, 0, 0, 0, 30, 60, 90], n)
    # Default probability rises with low score, high debt-to-income and days past due.
    z = -2.2 - (score - 690) / 60 + 3.0 * (dti - 0.38) + dpd / 45 + (seg == "Self-employed") * 0.3
    p = 1 / (1 + np.exp(-z))
    default = (rng.uniform(size=n) < p).astype(int)
    return pd.DataFrame(
        {
            "loan_id": [f"LN{100000 + i}" for i in range(n)],
            "segment": seg,
            "product": prod,
            "region": rng.choice(REGIONS, n),
            "credit_score": score,
            "annual_income": income.astype(int),
            "loan_amount": amount.astype(int),
            "dti": dti,
            "tenure_months": tenure,
            "days_past_due": dpd,
            "defaulted": default,
        }
    )


if __name__ == "__main__":
    df = loan_book()
    df.to_csv("loans.csv", index=False)
    print(df.head())
    print(f"{len(df)} rows, default rate {df.defaulted.mean():.1%}")
