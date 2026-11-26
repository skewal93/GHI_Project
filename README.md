# SME Bulk GHI & Multiline Underwriting Engine

End-to-end Python underwriting and pricing prototype for an **SME Bulk Group Health Insurance (GHI)** tender with attached commercial lines (**GPA, Fire, Marine**). Built around a realistic broker/TPA submission containing messy census data, claim anomalies, partial-year exposure, shock claims, and sector misclassifications.

## Workflow Overview

1. **`01_synthetic_generator.py`**: Generates 40 SME accounts with employee/dependent rosters and claims up to a mid-year cutoff, injecting date format inconsistencies, inverted dates, orphan member IDs, duplicate claims, billing anomalies, shock claims, and broker sector mismatches.
2. **`02_ingestion_hygiene.py`**: Standardizes dates and identifiers, imputes missing dependent ages by relation median, logs broker sector discrepancies, and quarantines invalid/duplicate records instead of silently dropping them.
3. **`03_pricing_engine.py`**: Computes **Earned Life-Years** (accounting for mid-term additions and deletions), applies claim-type **IBNR** uplift and annualization, splits **attritional vs. shock losses** at a ₹2,50,000 cap, blends experience with sector benchmarks via credibility weighting ($Z$), trends for medical inflation, and flags `Green_STP`, `Amber_Load_Or_Copay`, and `Red_Referral` accounts.
4. **`04_quote_generator.py`**: Produces `Broker_Commercial_Quote_Pack.xlsx` (Option A As-Is Renewal, Option B Co-Pay & Sub-Limit Shield, Option C Multiline Bundled Quote) and `Internal_Underwriting_Note.txt`.

## How to Run

```bash
cd src
python 01_synthetic_generator.py
python 02_ingestion_hygiene.py
python 03_pricing_engine.py
python 04_quote_generator.py
