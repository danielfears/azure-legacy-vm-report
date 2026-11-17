# Azure Legacy VM Reporting Tool

Inventories every deployed **v1, v2 and v3 Azure Virtual Machine** (and **Virtual Machine Scale Set**)
across one or more Azure tenants, calculates their **current monthly cost**, and projects what they
will cost in **February 2027** after the announced Azure price hikes.

It is a single Python 3 command-line tool with **no third-party dependencies** and is **read-only**:
it changes nothing in Azure.

```text
azure-legacy-vm-report
```

## Quick start

```powershell
# Install once (puts `azure-legacy-vm-report` on your PATH)
pip install -e .

# Scan your signed-in Azure CLI tenant -> writes & opens the interactive HTML report
az login --use-device-code --allow-no-subscriptions
azure-legacy-vm-report

# Add extra output formats with simple flags
azure-legacy-vm-report --csv              # HTML + CSV spreadsheets
azure-legacy-vm-report --csv --json       # HTML + CSV + JSON
azure-legacy-vm-report --all              # HTML + CSV + JSON + Markdown + terminal summary

# Try it offline with synthetic data (no Azure login required)
azure-legacy-vm-report --demo
```

```sh
# Or run directly from a checkout without installing:
# Windows PowerShell:  .\azure-legacy-vm-report.ps1
# Linux / macOS:       ./azure-legacy-vm-report
# WSL -> Windows CLI:  ./azure-legacy-vm-report-windows
```

## Required Azure permissions (RBAC)

Strictly **read-only**; optional billing and reservation enrichments degrade gracefully if unavailable:

| Role | Purpose | If absent |
|---|---|---|
| **Reader** *(required)* | Discovers VMs, VMSS, AKS/Batch/ML pools, schedules, Management Groups, Advisor alerts and regional Compute vCPU quotas. | Unreadable subscriptions are skipped. |
| **Cost Management Reader** *(recommended)* | Queries per-VM `ActualCost` and `UsageQuantity` and auto-detects negotiated EA/MCA/MACC discounts vs Retail PAYG. | Falls back to schedule-adjusted Retail rates. |
| **Reservations Reader** *(optional)* | Matches active Single, Management Group and Shared VM Reserved Instances (including Instance Size Flexibility). | Marks RIs as unchecked / PAYG. |

## Scope & authentication

Scans the active `az` CLI tenant by default, or multi-tenant / Service Principal targets via CLI flags or [`config.example.json`](config.example.json) (`clientSecretEnv` names an environment variable; secrets are never stored in config files):

```sh
azure-legacy-vm-report --all-tenants
azure-legacy-vm-report --tenant <tenant-id-or-domain> --subscription <sub-guid>
export AZURE_LEGACY_VM_REPORT_SP_SECRET="..." && azure-legacy-vm-report --config config.json
azure-legacy-vm-report --cloud AzureUSGovernment   # AzureCloud | AzureUSGovernment | AzureChinaCloud
```

## What it discovers & models

- **All VM-backed compute:** Standalone VMs, Uniform & Flexible VM Scale Sets (child VMs deduplicated), AKS node pools (correlated to `<cluster>/<pool>`, including scaled-to-zero pools), Azure Batch pools and Azure ML compute.
- **Legacy SKU classification:** Detects explicit `_v1`, `_v2` and `_v3` SKUs (including constrained-core `Standard_DS14-4_v2` / `E16-4s_v3` and HPC/GPU series) plus unversioned `v1` SKUs (`Standard_B1ls`–`B20ms`, `D1`–`D14`, `DS1`–`DS14`, `F1`–`F16s`, `G1`–`GS5`, `L4s`–`L32s`, `A0`–`A11`, `NP`, `HC`, `HB`, `H`, `M`, `NC`/`ND`/`NV`, `DCs`). Modern `v4`–`v7` SKUs — and active non-EoL `_v2`/`_v3` families (`Bsv2`, `Basv2`, `Bpsv2`, `Lsv3`, `Lasv3`, `NCasT4_v3`) in `0%`-hike regions — are skipped automatically so migrated `Bv1 -> Bsv2` workloads drop off subsequent scans (pass `--include-regional-skus` to include them everywhere).
- **Current monthly spend (`--cost-source auto|last-month|mtd|retail`):** Queries Cost Management actual billed spend (capturing negotiated EA/MCA/MACC discounts, AHB/BYOL, and real start/stop or autoscale duty cycles, with MTD extrapolation for new VMs). Where Cost Management is unavailable, infers duty-cycle hours from Portal auto-shutdown schedules, runbook tags and AKS/Monitor autoscale rules before falling back to `730h/mo` Retail rates.
- **Migration sizing & Wave Planner:**
  - **Wave 1 — Drop-in `v5` resize (`az vm resize` / `az vmss update`):** Maps temp-disk VMs to `Ddsv5` / `Edsv5` / `Dldsv5` (preventing ARM temp-disk resize errors), 7 GiB/vCPU `D11`–`D15` / `DS11`–`DS15` to `E`-series, and constrained-core SKUs to matching `E*-*ds_v5` active vCPU caps.
  - **Wave 2 — Managed pool rolling replace (`az aks nodepool add`):** Targets cheaper diskless `Dsv5` / `Esv5` / `Dlsv5` SKUs on AKS, Databricks, OpenShift, Batch and ML pools.
  - **Wave 3 — Gen2 / NVMe & specialised rebuild:** Covers `v6`/`v7` strategic targets and proportional `NVadsA10_v5` / `NC` GPU replacements, quoting live PAYG and **3-Year RI** rates alongside observed EA/MCA discounts.
- **Readiness enrichments:** Matches active RIs (vs the **01/07/2026** legacy RI purchase/renewal block), joins Azure Advisor idle/right-size recommendations, checks cumulative regional `v5` vCPU family quota headroom across all subscriptions, and rolls up CAF parent Management Groups and cost-allocation tags.

### February 2027 price-hike models (effective `01/02/2027`)

| Option | Behaviour |
|---|---|
| `--hike-model service-health` *(default)* | **+25%** globally on End-of-Life `v1`/`v2` series (`Bv1, D/Ds, F/Fs, G/Gs, Ls, NP, HC, Av2, Amv2, Dv2/Dsv2, Fsv2, Lsv2`), plus regional hikes (`northeurope` +17%, `francecentral`/`francesouth` +11%, `westeurope`/`norwayeast`/`norwaywest` +9%, `southeastasia` +8%) on non-excluded `v2`/`v3` series (`0%` elsewhere unless `--v3-hike` is set). |
| `--hike-model legacy-25` | Blanket **+25%** across all `v1`, `v2` and `v3` legacy SKUs. |
| `--v1-hike P --v2-hike P --v3-hike P` | Custom percentage hike per generation (also adjustable live in the HTML report). |

## Output formats

Running `azure-legacy-vm-report` with no flags writes and opens the **HTML** dashboard in `~/azure-legacy-vm-reports` (`--out-dir DIR`, `0700`/`0600` permissions on POSIX). Add `--csv`, `--json`, `--md`, `--console` or `--all` for extra formats (`--format FMT[,FMT]` selects an exact subset; `--no-open` skips launching a browser):

- `….html`: Offline interactive dashboard with a 5-card KPI brief, tabbed zero-scroll views (*By Subscription*, *By SKU*, *By Wave*, *By Management Group*, *VM Inventory*), live Stay-vs-Migrate tickboxes, `v5`/`v6` PAYG & 3Y RI tier switcher, *Stop Advisor idle VMs* toggle, and *Hiked* / *Active* filters.
- `…-vms.csv`, `…-skus.csv`, `…-subscriptions.csv`, `…-summary.csv`: Spreadsheet exports (protected against CSV formula injection).
- `….json` & `….md`: Full machine-readable JSON payload and GitHub-flavoured Markdown summary.

## Network & privacy

- **Read-only Azure & pricing calls:** Contacts Azure Resource Manager (`management.azure.com` or selected `--cloud`) and the public Azure Retail Prices API (`prices.azure.com`; skip with `--offline-prices`).
- **Cached GitHub release check:** Checks `api.github.com/repos/danielfears/azure-legacy-vm-report/releases/latest` at most once per 24 hours (`2.5s` timeout, silent fail-open if blocked) to surface an update link when running an outdated version. Skipped automatically on `--demo` and `--offline-prices`, or disabled via `--no-update-check` / `AZURE_LEGACY_VM_REPORT_NO_UPDATE_CHECK=1`.
- **Zero browser telemetry:** Generated HTML reports enforce `Content-Security-Policy: default-src 'none'` and make zero network requests when opened.

## Development & tests

```sh
python -m unittest discover -s tests -v
azure-legacy-vm-report --demo --all --no-open
```
