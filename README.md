# SME Bulk GHI & Multiline Underwriting Engine

End-to-end Python underwriting and pricing prototype for an **SME Bulk Group Health Insurance (GHI)** tender with attached commercial lines (**GPA, Fire, Marine**). Built around a realistic broker/TPA submission containing messy census data, claim anomalies, partial-year exposure, shock claims, and sector misclassifications.

## Input-to-Output Summary

| Stage | What Goes In | What Happens Behind the Scenes | What Comes Out |
| :--- | :--- | :--- | :--- |
| **1. Synthetic Broker & TPA Dump** | Config rules & sector/multiline parameters | Simulates 40 SME accounts, member rosters, and ~8 months of claims with messy real-world anomalies | `broker_accounts.csv`, `broker_census.csv`, `tpa_claims.csv` |
| **2. Ingestion & Hygiene** | Raw broker & TPA CSVs | Normalizes dates/IDs/relations, imputes missing dependent ages, and quarantines bad/duplicate rows | Clean warehouse tables + quarantine & sector-mismatch audit CSVs |
| **3. Exposure, IBNR & Pricing Engine** | Clean tables + pricing assumptions | Computes earned life-years, applies IBNR & annualization, caps shock losses, blends via credibility ($Z$), trends for inflation, and triages risk | `account_pricing_summary.csv` (`Green_STP`, `Amber_Load_Or_Copay`, `Red_Referral`) |
| **4. Quote & Underwriting Outputs** | Pricing summary + audit logs | Builds three commercial quote options per account and flags referral/subjectivity conditions | `Broker_Commercial_Quote_Pack.xlsx` + `Internal_Underwriting_Note.txt` |

### Quick Takeaways for Reviewers
* **Inputs:** Messy multi-account census and claim feeds with mid-term churn, inverted dates, orphan IDs, duplicate rows, billing errors, shock claims, and broker sector mismatches.
* **Core Logic:** Earned exposure instead of raw headcount, IBNR + annualization, shock capping at ₹2.5L, credibility blending with sector benchmarks, and multiline bundling discounts (`GPA`, `Fire`, `Marine`).
* **Outputs:** A 3-sheet Excel quote pack (**Option A: As-Is**, **Option B: Co-Pay Shield**, **Option C: Multiline Bundle**), a plain-text internal underwriting memo.
