"""Quality guidelines: Report any issues; never correct them without saying anything."""
import pandas as pd

AVG_FACTOR = 3.0     # average > 3 x the median (or < median / 3) of departments for this product
SPREAD_FACTOR = 5.0  # max price > 5 x min price in the same department


def flag_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Add the quality_flag column: ok, inconsistent_stats or suspect_outlier."""
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
