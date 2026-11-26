from pathlib import Path
import numpy as np
import pandas as pd


def _parse_mixed_dates(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.strip().str.replace("-", "/", regex=False)
    # Try ISO first, then day-first
    parsed = pd.to_datetime(cleaned, format="%Y/%m/%d", errors="coerce")
    mask_na = parsed.isna()
    if mask_na.any():
        parsed.loc[mask_na] = pd.to_datetime(cleaned.loc[mask_na], format="%d/%m/%Y", errors="coerce")
    return parsed


def run_ingestion_hygiene(
    raw_dir: str = "data/raw_broker_dump",
    clean_dir: str = "data/cleaned_warehouse",
    quarantine_dir: str = "data/quarantine",
) -> dict[str, pd.DataFrame]:
    raw_path = Path(raw_dir)
    clean_path = Path(clean_dir)
    quar_path = Path(quarantine_dir)
    clean_path.mkdir(parents=True, exist_ok=True)
    quar_path.mkdir(parents=True, exist_ok=True)

    accounts = pd.read_csv(raw_path / "broker_accounts.csv")
    census = pd.read_csv(raw_path / "broker_census.csv")
    claims = pd.read_csv(raw_path / "tpa_claims.csv")

    # 1. Standardize core keys & dates
    accounts["Account_ID"] = accounts["Account_ID"].astype(str).str.strip()
    accounts["Policy_Start_Date"] = pd.to_datetime(accounts["Policy_Start_Date"], errors="coerce")
    accounts["Policy_End_Date"] = pd.to_datetime(accounts["Policy_End_Date"], errors="coerce")

    # Log broker sector mismatches for underwriting review (do not drop account)
    sector_audit = accounts[
        accounts["Broker_Declared_Sector"] != accounts["_True_Sector_Audit"]
    ][["Account_ID", "Company_Name", "Broker_Declared_Sector", "_True_Sector_Audit", "Broker_Name"]].copy()
    sector_audit.to_csv(quar_path / "sector_mismatch_audit.csv", index=False)

    census["Account_ID"] = census["Account_ID"].astype(str).str.strip()
    census["Member_ID"] = census["Member_ID"].astype(str).str.strip()
    census["Emp_Code"] = census["Emp_Code"].astype(str).str.strip()
    census["Relation"] = census["Relation"].astype(str).str.strip().str.title()
    census["Addition_Date_Clean"] = _parse_mixed_dates(census["Addition_Date"])
    census["Deletion_Date_Clean"] = _parse_mixed_dates(census["Deletion_Date"])

    # Quarantine census rows with invalid date ranges or impossible ages
    census_bad_mask = (
        census["Addition_Date_Clean"].isna()
        | census["Deletion_Date_Clean"].isna()
        | (census["Deletion_Date_Clean"] < census["Addition_Date_Clean"])
        | ((census["Age"].notna()) & ((census["Age"] < 0) | (census["Age"] > 105)))
    )
    census_quar = census[census_bad_mask].copy()
    census_quar["reject_reason"] = "INVALID_CENSUS_DATE_OR_AGE"
    census_clean = census[~census_bad_mask].copy()

    # Fill missing dependent ages using median age by Relation (flagging imputed rows)
    census_clean["Age_Imputed"] = census_clean["Age"].isna()
    rel_medians = census_clean.groupby("Relation")["Age"].transform("median")
    census_clean["Age_Clean"] = census_clean["Age"].fillna(rel_medians).fillna(30).round(1)

    # 2. Clean & quarantine TPA claims
    claims = claims.rename(columns={"Claim_Ref": "Claim_ID"})
    claims["Account_ID"] = claims["Account_ID"].astype(str).str.strip()
    claims["Member_ID"] = claims["Member_ID"].astype(str).str.strip()
    claims["Admission_Date_Clean"] = pd.to_datetime(claims["Admission_Date"], errors="coerce")
    claims["Discharge_Date_Clean"] = pd.to_datetime(claims["Discharge_Date"], errors="coerce")

    valid_members = set(census_clean["Member_ID"].unique())
    account_windows = accounts.set_index("Account_ID")[["Policy_Start_Date", "Policy_End_Date"]]
    claims = claims.join(account_windows, on="Account_ID")

    reasons = []
    for row in claims.itertuples(index=False):
        r = []
        if pd.isna(row.Admission_Date_Clean) or pd.isna(row.Discharge_Date_Clean):
            r.append("INVALID_CLAIM_DATE")
        elif row.Discharge_Date_Clean < row.Admission_Date_Clean:
            r.append("DISCHARGE_BEFORE_ADMISSION")
        if pd.notna(row.Policy_Start_Date) and pd.notna(row.Admission_Date_Clean):
            if row.Admission_Date_Clean < row.Policy_Start_Date or row.Admission_Date_Clean > row.Policy_End_Date:
                r.append("CLAIM_OUTSIDE_POLICY_PERIOD")
        if row.Member_ID not in valid_members:
            r.append("ORPHAN_MEMBER_ID")
        if row.Paid_Amt < 0 or row.Billed_Amt <= 0 or row.Paid_Amt > row.Billed_Amt * 1.02:
            r.append("BILLING_AMOUNT_ANOMALY")
        reasons.append("|".join(r) if r else "")

    claims["reject_reason"] = reasons

    # Flag exact duplicates (after initial row checks)
    dup_mask = (claims["reject_reason"] == "") & claims.duplicated(
        subset=["Account_ID", "Member_ID", "Admission_Date_Clean", "Billed_Amt", "Paid_Amt"],
        keep="first",
    )
    claims.loc[dup_mask, "reject_reason"] = "DUPLICATE_CLAIM_ROW"

    claims_quar = claims[claims["reject_reason"] != ""].copy()
    claims_clean = claims[claims["reject_reason"] == ""].copy()
    claims_clean["LOS_Days"] = (
        (claims_clean["Discharge_Date_Clean"] - claims_clean["Admission_Date_Clean"]).dt.days + 1
    ).clip(lower=1)

    # Save outputs
    accounts.to_csv(clean_path / "accounts_clean.csv", index=False)
    census_clean.to_csv(clean_path / "census_clean.csv", index=False)
    claims_clean.to_csv(clean_path / "claims_clean.csv", index=False)

    census_quar.to_csv(quar_path / "census_quarantine.csv", index=False)
    claims_quar.to_csv(quar_path / "claims_quarantine.csv", index=False)

    print("Ingestion & Hygiene complete:")
    print(f"  Census clean: {len(census_clean)} | quarantined: {len(census_quar)}")
    print(f"  Claims clean: {len(claims_clean)} | quarantined: {len(claims_quar)}")
    print(f"  Broker sector mismatches logged: {len(sector_audit)}")

    return {
        "accounts": accounts,
        "census_clean": census_clean,
        "claims_clean": claims_clean,
        "claims_quarantine": claims_quar,
        "sector_audit": sector_audit,
    }


if __name__ == "__main__":
    run_ingestion_hygiene()