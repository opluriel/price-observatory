"""Règles de qualité : on signale les anomalies, on ne les corrige jamais en silence."""
import pandas as pd

AVG_FACTOR = 3.0     # moyenne > 3 x la médiane (ou < médiane / 3) des départements pour ce produit
SPREAD_FACTOR = 5.0  # prix maxi > 5 x prix mini dans un même département


def flag_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute la colonne quality_flag : ok, inconsistent_stats ou suspect_outlier."""
    df = df.copy()
    df["quality_flag"] = "ok"

    inconsistent = (
        df[["price_min", "price_max", "price_avg"]].isna().any(axis=1)
        | (df["price_min"] > df["price_max"])
        | (df["price_avg"] < df["price_min"])
        | (df["price_avg"] > df["price_max"])
    )
    df.loc[inconsistent, "quality_flag"] = "inconsistent_stats"

    median = df.groupby(["period_start", "product"])["price_avg"].transform("median")
    off_median = (df["price_avg"] > AVG_FACTOR * median) | (df["price_avg"] < median / AVG_FACTOR)
    too_spread = df["price_max"] > SPREAD_FACTOR * df["price_min"]
    df.loc[(off_median | too_spread) & ~inconsistent, "quality_flag"] = "suspect_outlier"
    return df
