from pathlib import Path
import numpy as np
import pandas as pd

SRC_DIR = Path(__file__).resolve().parent
DATA_ROOT = SRC_DIR / "data"

raw_dir = DATA_ROOT / "raw_broker_dump"
clean_dir = DATA_ROOT / "cleaned_warehouse"
quarantine_dir = DATA_ROOT / "quarantine"
pricing_dir = DATA_ROOT / "pricing_outputs"
deliverables_dir = DATA_ROOT / "deliverables"


def run_pricing_engine(
    clean_dir: Path | None = None,
    output_dir: Path | None = None,
    cutoff_date_str: str = "2026-11-26",
    shock_cap_inr: float = 250000.0,
    medical_inflation: float = 0.13,
    full_credibility_lives: float = 500.0,
    ibnr_factors: dict[str, float] | None = None,
    sector_benchmark_burn: dict[str, float] | None = None,
    multiline_discount_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    clean_path = clean_dir or (SRC_DIR / "data" / "cleaned_warehouse")
    out_path = output_dir or (SRC_DIR / "data" / "pricing_outputs")
    out_path.mkdir(parents=True, exist_ok=True)

    if ibnr_factors is None:
        ibnr_factors = {"Cashless": 1.08, "Reimbursement": 1.18}
    if sector_benchmark_burn is None:
        sector_benchmark_burn = {
            "Manufacturing": 11500.0,
            "IT/ITES": 8200.0,
            "Logistics": 12800.0,
            "Retail": 9400.0,
            "Services": 8600.0,
        }
    if multiline_discount_map is None:
        multiline_discount_map = {
            "None": 0.00,
            "GPA": 0.03,
            "GPA+Fire": 0.05,
            "GPA+Marine": 0.05,
            "GPA+Fire+Marine": 0.07,
        }

    cutoff_date = pd.Timestamp(cutoff_date_str)

    accounts = pd.read_csv(clean_path / "accounts_clean.csv")
    census = pd.read_csv(clean_path / "census_clean.csv")
    claims = pd.read_csv(clean_path / "claims_clean.csv")

    accounts["Policy_Start_Date"] = pd.to_datetime(accounts["Policy_Start_Date"])
    accounts["Policy_End_Date"] = pd.to_datetime(accounts["Policy_End_Date"])
    census["Addition_Date_Clean"] = pd.to_datetime(census["Addition_Date_Clean"])
    census["Deletion_Date_Clean"] = pd.to_datetime(census["Deletion_Date_Clean"])
    claims["Admission_Date_Clean"] = pd.to_datetime(claims["Admission_Date_Clean"])

    # 1. Compute Earned Life-Years per member up to cutoff_date
    census = census.merge(
        accounts[["Account_ID", "Policy_Start_Date", "Policy_End_Date"]],
        on="Account_ID",
        how="left",
    )
    eff_start = np.maximum(census["Addition_Date_Clean"], census["Policy_Start_Date"])
    eff_end = np.minimum(
        np.minimum(census["Deletion_Date_Clean"], census["Policy_End_Date"]),
        cutoff_date,
    )
    active_days = ((eff_end - eff_start).dt.days + 1).clip(lower=0)
    census["Earned_Life_Years"] = active_days / 365.0

    exposure_summary = (
        census.groupby("Account_ID", as_index=False)
        .agg(
            Total_Roster_Lives=("Member_ID", "count"),
            Earned_Life_Years=("Earned_Life_Years", "sum"),
            Avg_Age=("Age_Clean", "mean"),
            Parent_Share=("Relation", lambda s: (s == "Parent").mean()),
        )
    )

    # 2. Apply IBNR uplift per claim and split Attritional vs. Shock loss
    claims["IBNR_Factor"] = claims["Claim_Type"].map(ibnr_factors).fillna(1.12)
    claims["Ultimate_Paid_INR"] = claims["Paid_Amt"] * claims["IBNR_Factor"]
    claims["Attritional_INR"] = np.minimum(claims["Ultimate_Paid_INR"], shock_cap_inr)
    claims["Shock_Excess_INR"] = np.maximum(0.0, claims["Ultimate_Paid_INR"] - shock_cap_inr)

    claims_summary = (
        claims.groupby("Account_ID", as_index=False)
        .agg(
            Claim_Count=("Claim_ID", "count"),
            Raw_Paid_INR=("Paid_Amt", "sum"),
            Ultimate_Paid_INR=("Ultimate_Paid_INR", "sum"),
            Attritional_INR=("Attritional_INR", "sum"),
            Shock_Excess_INR=("Shock_Excess_INR", "sum"),
        )
    )

    # 3. Merge into Accounts & Annualize to 12 months
    df = accounts.merge(exposure_summary, on="Account_ID", how="left").merge(
        claims_summary, on="Account_ID", how="left"
    )
    df["Earned_Life_Years"] = df["Earned_Life_Years"].fillna(0.0).clip(lower=0.1)
    df["Total_Roster_Lives"] = df["Total_Roster_Lives"].fillna(0).astype(int)
    for col in ["Claim_Count", "Raw_Paid_INR", "Ultimate_Paid_INR", "Attritional_INR", "Shock_Excess_INR"]:
        df[col] = df[col].fillna(0.0)

    elapsed_days = max(1, (cutoff_date - df["Policy_Start_Date"].min()).days + 1)
    annualization_factor = 365.0 / elapsed_days

    df["Annualized_Ultimate_INR"] = df["Ultimate_Paid_INR"] * annualization_factor
    df["Annualized_Attritional_INR"] = df["Attritional_INR"] * annualization_factor
    df["Annualized_Shock_INR"] = df["Shock_Excess_INR"] * annualization_factor

    df["Annualized_Burn_Per_Life"] = df["Annualized_Attritional_INR"] / df["Earned_Life_Years"]
    df["Benchmark_Burn_Per_Life"] = df["Broker_Declared_Sector"].map(sector_benchmark_burn).fillna(9500.0)

    # 4. Credibility blending + Medical Inflation + Catastrophe Pool Load (e.g., 8% of attritional)
    df["Credibility_Z"] = np.minimum(1.0, np.sqrt(df["Earned_Life_Years"] / full_credibility_lives))
    df["Blended_Burn_Per_Life"] = (
        df["Credibility_Z"] * df["Annualized_Burn_Per_Life"]
        + (1.0 - df["Credibility_Z"]) * df["Benchmark_Burn_Per_Life"]
    )
    df["Trended_Burn_Per_Life"] = df["Blended_Burn_Per_Life"] * (1.0 + medical_inflation) * 1.08
    df["Technical_Renewal_Premium_INR"] = (df["Trended_Burn_Per_Life"] * df["Earned_Life_Years"]).round(2)

    # Multiline bundled GHI discount (conditional on binding attached commercial lines)
    df["Multiline_Discount_Pct"] = df["Attached_Multiline"].map(multiline_discount_map).fillna(0.0)
    df["Bundled_GHI_Quote_INR"] = (
        df["Technical_Renewal_Premium_INR"] * (1.0 - df["Multiline_Discount_Pct"])
    ).round(2)

    # 5. Projected Loss Ratio & UW Triage
    df["Annualized_Expiring_LR"] = np.where(
        df["Expiring_Premium_INR"] > 0,
        df["Annualized_Ultimate_INR"] / df["Expiring_Premium_INR"],
        0.0,
    )
    df["Projected_Technical_LR"] = np.where(
        df["Expiring_Premium_INR"] > 0,
        df["Technical_Renewal_Premium_INR"] / df["Expiring_Premium_INR"],
        0.0,
    )

    def _triage(row: pd.Series) -> str:
        if row["Projected_Technical_LR"] > 0.95 or row["Parent_Share"] > 0.25:
            return "Red_Referral"
        if row["Projected_Technical_LR"] > 0.68 or row["Parent_Share"] > 0.12:
            return "Amber_Load_Or_Copay"
        return "Green_STP"

    df["UW_Triage_Tier"] = df.apply(_triage, axis=1)
    df["Sector_Mismatch_Flag"] = df["Broker_Declared_Sector"] != df["_True_Sector_Audit"]

    out_file = out_path / "account_pricing_summary.csv"
    df.to_csv(out_file, index=False)

    print(f"Pricing engine complete -> '{out_file}'")
    print("Triage breakdown:")
    print(df["UW_Triage_Tier"].value_counts().to_string())
    return df


if __name__ == "__main__":
    run_pricing_engine()