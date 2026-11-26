from pathlib import Path
import numpy as np
import pandas as pd


def generate_messy_broker_data(output_dir: str = "data/raw_broker_dump", seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    sectors = ["Manufacturing", "IT/ITES", "Logistics", "Retail", "Services"]
    sector_probs = [0.24, 0.24, 0.18, 0.18, 0.16]
    sector_base_burn = {
        "Manufacturing": 11500.0,
        "IT/ITES": 8200.0,
        "Logistics": 12800.0,
        "Retail": 9400.0,
        "Services": 8600.0,
    }
    brokers = ["Marsh_SME_Desk", "Prudent_Commercial", "Aon_MidMarket", "Bajaj_Broker_Channel"]
    family_plans = ["1+3", "1+5"]
    si_slabs = [200000, 300000, 500000]
    multiline_options = ["None", "GPA", "GPA+Fire", "GPA+Marine", "GPA+Fire+Marine"]

    policy_start = pd.Timestamp("2026-04-01")
    policy_end = pd.Timestamp("2027-03-31")
    cutoff_date = pd.Timestamp("2026-11-26")  # ~8 months of elapsed claims

    num_accounts = 40
    accounts_rows = []
    census_rows = []
    claims_rows = []

    claim_counter = 100000

    for acc_idx in range(1, num_accounts + 1):
        account_id = f"ACC_{acc_idx:03d}"
        true_sector = rng.choice(sectors, p=sector_probs)

        # Inject broker industry misclassification on ~12% of accounts
        declared_sector = true_sector
        if rng.random() < 0.12:
            declared_sector = "IT/ITES" if true_sector in ["Manufacturing", "Logistics"] else rng.choice(sectors)

        broker = rng.choice(brokers)
        family_plan = rng.choice(family_plans, p=[0.65, 0.35])
        si_slab = int(rng.choice(si_slabs, p=[0.35, 0.45, 0.20]))
        multiline_bundle = rng.choice(multiline_options, p=[0.35, 0.25, 0.18, 0.12, 0.10])

        headcount = int(rng.integers(35, 180))
        expiring_premium = float(headcount * sector_base_burn[declared_sector] * rng.uniform(0.92, 1.12))

        # Simulate mid-term churn on ~20% of accounts
        heavy_churn_account = rng.random() < 0.20

        accounts_rows.append(
            {
                "Account_ID": account_id,
                "Company_Name": f"{true_sector[:4].upper()}_Enterprise_{acc_idx:02d} Pvt Ltd",
                "Broker_Declared_Sector": declared_sector,
                "_True_Sector_Audit": true_sector,
                "Broker_Name": broker,
                "Family_Definition": family_plan,
                "Sum_Insured_INR": si_slab,
                "Policy_Start_Date": policy_start.strftime("%Y-%m-%d"),
                "Policy_End_Date": policy_end.strftime("%Y-%m-%d"),
                "Expiring_Premium_INR": round(expiring_premium, 2),
                "Attached_Multiline": multiline_bundle,
            }
        )

        # Build roster of employees and dependents
        for emp_idx in range(1, headcount + 1):
            emp_id = f"{acc_idx:03d}_E{emp_idx:04d}"
            emp_age = int(rng.integers(22, 56))
            emp_gender = rng.choice(["M", "F"])

            add_date = policy_start
            if rng.random() < 0.15:
                add_date = policy_start + pd.Timedelta(days=int(rng.integers(10, 180)))

            del_date = policy_end
            if heavy_churn_account and rng.random() < 0.45:
                del_date = policy_start + pd.Timedelta(days=int(rng.integers(45, 210)))
            elif rng.random() < 0.08:
                del_date = policy_start + pd.Timedelta(days=int(rng.integers(30, 220)))

            # Format dates inconsistently across rows
            add_str = add_date.strftime("%d/%m/%Y") if rng.random() < 0.4 else add_date.strftime("%Y-%m-%d")
            del_str = del_date.strftime("%d-%m-%Y") if rng.random() < 0.3 else del_date.strftime("%Y-%m-%d")

            # Drop leading zeros or pad IDs inconsistently on some rows
            raw_emp_id = emp_id.lstrip("0") if rng.random() < 0.15 else f" {emp_id} " if rng.random() < 0.1 else emp_id

            members_for_emp = [("Self", emp_age, emp_gender)]

            if rng.random() < 0.65:
                spouse_age = max(19, emp_age + int(rng.integers(-6, 5)))
                spouse_gender = "F" if emp_gender == "M" else "M"
                members_for_emp.append(("Spouse", spouse_age, spouse_gender))

            num_children = int(rng.choice([0, 1, 2], p=[0.45, 0.35, 0.20]))
            for _ in range(num_children):
                child_age = int(rng.integers(1, 18))
                members_for_emp.append(("Child", child_age, rng.choice(["M", "F"])))

            if family_plan == "1+5" and rng.random() < 0.55:
                parent_age = int(rng.integers(54, 78))
                members_for_emp.append(("Parent", parent_age, rng.choice(["M", "F"])))

            for rel_idx, (rel, age, gender) in enumerate(members_for_emp):
                member_id = f"{emp_id}_{rel[0]}{rel_idx}"
                # Inject missing dependent ages (~6% of dependents)
                age_val = np.nan if (rel != "Self" and rng.random() < 0.06) else age

                census_rows.append(
                    {
                        "Account_ID": account_id,
                        "Emp_Code": raw_emp_id,
                        "Member_ID": member_id,
                        "Relation": rel,
                        "Age": age_val,
                        "Gender": gender,
                        "Addition_Date": add_str,
                        "Deletion_Date": del_str,
                    }
                )

                # Generate claims up to cutoff_date
                claim_prob = 0.09 if rel == "Self" else (0.24 if rel == "Parent" else 0.11)
                if true_sector in ["Manufacturing", "Logistics"] and rel == "Self":
                    claim_prob += 0.03

                if rng.random() < claim_prob:
                    claim_counter += 1
                    claim_id = f"CLM_{claim_counter}"

                    max_offset_days = max(1, (min(del_date, cutoff_date) - add_date).days)
                    adm_date = add_date + pd.Timedelta(days=int(rng.integers(0, max_offset_days + 1)))
                    los_days = int(rng.choice([1, 2, 3, 4, 5, 7], p=[0.20, 0.30, 0.22, 0.14, 0.09, 0.05]))
                    dis_date = adm_date + pd.Timedelta(days=los_days)

                    # Inject shock claim on ~3% of claims
                    is_shock = rng.random() < 0.03
                    if is_shock:
                        billed_amt = float(rng.uniform(320000, 850000))
                        icd_chapter = rng.choice(["Oncology (C00-D49)", "Circulatory/Cardiac (I00-I99)"])
                    else:
                        billed_amt = float(rng.uniform(18000, 165000))
                        icd_chapter = rng.choice(
                            [
                                "Infectious/Fever (A00-B99)",
                                "Digestive (K00-K95)",
                                "Musculoskeletal (M00-M99)",
                                "Respiratory (J00-J99)",
                            ]
                        )

                    approved_amt = round(billed_amt * float(rng.uniform(0.75, 0.98)), 2)
                    paid_amt = round(approved_amt * float(rng.uniform(0.85, 1.0)), 2)
                    claim_type = rng.choice(["Cashless", "Reimbursement"], p=[0.65, 0.35])

                    # Inject date inversion anomaly (~2% of claims)
                    adm_out, dis_out = adm_date.strftime("%Y-%m-%d"), dis_date.strftime("%Y-%m-%d")
                    if rng.random() < 0.02:
                        adm_out, dis_out = dis_date.strftime("%Y-%m-%d"), adm_date.strftime("%Y-%m-%d")

                    # Inject billing anomaly: paid > billed (~1.5% of claims)
                    if rng.random() < 0.015:
                        paid_amt = round(billed_amt * 1.15, 2)

                    # Inject orphan member ID (~2% of claims)
                    claim_member_id = f"{member_id}_ORPHAN" if rng.random() < 0.02 else member_id

                    claim_row = {
                        "Claim_Ref": claim_id,
                        "Account_ID": account_id,
                        "Member_ID": claim_member_id,
                        "Admission_Date": adm_out,
                        "Discharge_Date": dis_out,
                        "ICD_Chapter": icd_chapter,
                        "Claim_Type": claim_type,
                        "Billed_Amt": round(billed_amt, 2),
                        "Approved_Amt": approved_amt,
                        "Paid_Amt": paid_amt,
                    }
                    claims_rows.append(claim_row)

                    # Inject exact duplicate claim row (~2.5% of claims)
                    if rng.random() < 0.025:
                        claims_rows.append(claim_row.copy())

    accounts_df = pd.DataFrame(accounts_rows)
    census_df = pd.DataFrame(census_rows)
    claims_df = pd.DataFrame(claims_rows)

    accounts_df.to_csv(out_path / "broker_accounts.csv", index=False)
    census_df.to_csv(out_path / "broker_census.csv", index=False)
    claims_df.to_csv(out_path / "tpa_claims.csv", index=False)

    print(f"Generated messy broker dataset in '{out_path}':")
    print(f"  Accounts: {len(accounts_df)} | Census rows: {len(census_df)} | Claims rows: {len(claims_df)}")


if __name__ == "__main__":
    generate_messy_broker_data()