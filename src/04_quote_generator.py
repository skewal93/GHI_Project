from pathlib import Path
import pandas as pd

SRC_DIR = Path(__file__).resolve().parent
DATA_ROOT = SRC_DIR / "data"


def generate_quote_pack(
    pricing_csv: Path | None = None,
    quarantine_dir: Path | None = None,
    deliverables_dir: Path | None = None,
) -> None:
    p_csv = pricing_csv or (DATA_ROOT / "pricing_outputs" / "account_pricing_summary.csv")
    q_dir = quarantine_dir or (DATA_ROOT / "quarantine")
    out_dir = deliverables_dir or (DATA_ROOT / "deliverables")
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(p_csv)

    # Build 3 commercial quote options per account
    df["Option_A_AsIs_Quote_INR"] = df["Technical_Renewal_Premium_INR"].round(2)

    restructure_eligible = df["UW_Triage_Tier"].isin(["Amber_Load_Or_Copay", "Red_Referral"])
    df["Option_B_Copay_Shield_Quote_INR"] = df.apply(
        lambda r: round(r["Technical_Renewal_Premium_INR"] * 0.88, 2)
        if r["UW_Triage_Tier"] in ["Amber_Load_Or_Copay", "Red_Referral"]
        else round(r["Technical_Renewal_Premium_INR"], 2),
        axis=1,
    )
    df["Option_C_Multiline_Quote_INR"] = df["Bundled_GHI_Quote_INR"].round(2)

    def _recommended_option(row: pd.Series) -> str:
        if row["Attached_Multiline"] != "None" and row["Multiline_Discount_Pct"] > 0:
            return "Option_C_Multiline_Bundle"
        if row["UW_Triage_Tier"] in ["Amber_Load_Or_Copay", "Red_Referral"]:
            return "Option_B_Copay_Shield"
        return "Option_A_AsIs_Renewal"

    def _broker_conditions(row: pd.Series) -> str:
        notes = []
        if row["Sector_Mismatch_Flag"]:
            notes.append("Verify true business activity / GST sector classification")
        if row["Parent_Share"] > 0.15:
            notes.append("Subject to 20% parental co-pay & room-rent cap acceptance")
        if row["UW_Triage_Tier"] == "Red_Referral":
            notes.append("Requires Senior UW sign-off & updated active census")
        if row["Attached_Multiline"] != "None":
            notes.append(f"Multiline GHI discount valid only if {row['Attached_Multiline']} is bound")
        return "; ".join(notes) if notes else "Standard STP terms; subject to clean final census"

    df["Recommended_Quote_Option"] = df.apply(_recommended_option, axis=1)
    df["Broker_Conditions"] = df.apply(_broker_conditions, axis=1)

    # Tab 1: Executive Portfolio Summary
    summary_df = pd.DataFrame(
        [
            {
                "Metric": "Total Accounts Quoted",
                "Value": int(len(df)),
            },
            {
                "Metric": "Total Expiring GHI Premium (INR)",
                "Value": round(float(df["Expiring_Premium_INR"].sum()), 2),
            },
            {
                "Metric": "Option A - As-Is Technical Quote (INR)",
                "Value": round(float(df["Option_A_AsIs_Quote_INR"].sum()), 2),
            },
            {
                "Metric": "Option B - Co-Pay & Sub-Limit Shield Quote (INR)",
                "Value": round(float(df["Option_B_Copay_Shield_Quote_INR"].sum()), 2),
            },
            {
                "Metric": "Option C - Multiline Bundled Quote (INR)",
                "Value": round(float(df["Option_C_Multiline_Quote_INR"].sum()), 2),
            },
            {
                "Metric": "Green (STP) Accounts",
                "Value": int((df["UW_Triage_Tier"] == "Green_STP").sum()),
            },
            {
                "Metric": "Amber (Load / Co-Pay) Accounts",
                "Value": int((df["UW_Triage_Tier"] == "Amber_Load_Or_Copay").sum()),
            },
            {
                "Metric": "Red (Senior UW Referral) Accounts",
                "Value": int((df["UW_Triage_Tier"] == "Red_Referral").sum()),
            },
        ]
    )

    # Tab 2: Account-level Broker Quote Sheet
    quote_cols = [
        "Account_ID",
        "Company_Name",
        "Broker_Name",
        "Broker_Declared_Sector",
        "Family_Definition",
        "Sum_Insured_INR",
        "Earned_Life_Years",
        "UW_Triage_Tier",
        "Expiring_Premium_INR",
        "Option_A_AsIs_Quote_INR",
        "Option_B_Copay_Shield_Quote_INR",
        "Attached_Multiline",
        "Option_C_Multiline_Quote_INR",
        "Recommended_Quote_Option",
        "Broker_Conditions",
    ]
    account_quotes_df = df[quote_cols].copy()

    # Load quarantine counts if available
    quar_summary_rows = []
    for fname in ["census_quarantine.csv", "claims_quarantine.csv", "sector_mismatch_audit.csv"]:
        fpath = q_dir / fname
        if fpath.exists():
            qdf = pd.read_csv(fpath)
            quar_summary_rows.append({"Audit_File": fname, "Exception_Rows": int(len(qdf))})
    quar_summary_df = pd.DataFrame(quar_summary_rows)

    xlsx_path = out_dir / "Broker_Commercial_Quote_Pack.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Executive_Summary", index=False)
        account_quotes_df.to_excel(writer, sheet_name="Account_Quotes", index=False)
        if not quar_summary_df.empty:
            quar_summary_df.to_excel(writer, sheet_name="Data_Audit_Counts", index=False)

    # Write Internal Underwriting Memo
    red_accounts = df[df["UW_Triage_Tier"] == "Red_Referral"]["Account_ID"].tolist()
    mismatch_accounts = df[df["Sector_Mismatch_Flag"]]["Account_ID"].tolist()

    memo_lines = [
        "# Internal Bulk Underwriting Memo — SME GHI + Multiline Tender",
        "",
        "## Portfolio Snapshot",
        f"- **Accounts evaluated:** {len(df)}",
        f"- **Total expiring GHI premium:** ₹{df['Expiring_Premium_INR'].sum():,.2f}",
        f"- **Option A (As-Is) total:** ₹{df['Option_A_AsIs_Quote_INR'].sum():,.2f}",
        f"- **Option B (Co-Pay / Sub-Limit Shield) total:** ₹{df['Option_B_Copay_Shield_Quote_INR'].sum():,.2f}",
        f"- **Option C (Multiline Bundled) total:** ₹{df['Option_C_Multiline_Quote_INR'].sum():,.2f}",
        "",
        "## Referral & Risk Flags",
        f"- **Red Referral Accounts ({len(red_accounts)}):** {', '.join(red_accounts) if red_accounts else 'None'}",
        f"- **Broker Sector Mismatches ({len(mismatch_accounts)}):** {', '.join(mismatch_accounts) if mismatch_accounts else 'None'}",
        "",
        "## Underwriting Conditions for Broker",
        "- Apply 20% parental co-pay and room-rent sub-limits on high-parent-share / Amber-Red accounts.",
        "- Lock multiline GHI discounts strictly contingent on binding attached GPA, Fire, or Marine policies.",
        "- Confirm final active member roster and dependent DOBs prior to policy issuance.",
    ]

    txt_path = out_dir / "Internal_Underwriting_Note.txt"
    txt_path.write_text("\n".join(memo_lines), encoding="utf-8")

    print(f"Quote pack saved -> '{xlsx_path}'")
    print(f"UW memo saved  -> '{txt_path}'")


if __name__ == "__main__":
    generate_quote_pack()