# Azure Legacy VM Reporting Tool

Inventories every deployed **v1, v2 and v3 Azure Virtual Machine** (and **Virtual Machine Scale Set**)
across one or more Azure tenants, calculates their **current monthly cost**, and projects what they
will cost in **February 2027** after the announced Azure price hikes.

It is a single Python 3 command-line tool with **no third-party dependencies** and is **read-only**:
it changes nothing in Azure.

```text
azure-legacy-vm-report --format console,csv,html --open
```

## Quick start

```sh
# Try it without touching Azure (synthetic data across two demo tenants)
./azure-legacy-vm-report --demo --format console,html --open

# Scan the tenant your Azure CLI is currently signed in to
az login --use-device-code --allow-no-subscriptions
./azure-legacy-vm-report --format console,csv,html --open

# Scan all logged-in tenants
./azure-legacy-vm-report --all-tenants --format console,csv,html --open

# From WSL, when Microsoft sign-in only works from Windows (Global Secure Access)
./azure-legacy-vm-report-windows login <tenant-id>
./azure-legacy-vm-report-windows --tenant <tenant-id> --format console,csv,html --open
```

## How legacy v1, v2 and v3 SKUs & workload types are identified

The tool scans across all VM-backed compute types in a tenant:

- **Standalone Virtual Machines (`Microsoft.Compute/virtualMachines`)**
- **Virtual Machine Scale Sets (`Microsoft.Compute/virtualMachineScaleSets`)** — both Uniform and Flexible orchestration (automatically deduplicating child VMs of Flexible scale sets so instances are never double-counted).
- **AKS Node Pools (`Microsoft.ContainerService/managedClusters`)** — correlates backing `MC_*` VM Scale Sets with their parent AKS cluster and node pool name (`AKS Node Pool (<cluster>/<pool>)`), including `enableAutoScaling` (`minCount..maxCount`), and surfaces any legacy AKS node pools even if scaled to zero.
- **Azure Batch Pools (`Microsoft.Batch/batchAccounts/pools`)** and **Azure Machine Learning Compute (`Microsoft.MachineLearningServices/workspaces/computes`)**.
- **Workload classification (`deployment_kind`):** tags and resource metadata classify each resource as `Standalone VM`, `VM Scale Set`, `AKS Node Pool (<cluster>/<pool>)`, `OpenShift / ARO Node`, `Databricks Node`, `AVD Session Host`, `DevTest Lab VM`, `Batch Pool`, `ML Compute`, or `Ephemeral / CI Job VM`.

In Azure Resource Manager, many **v1** VM sizes do **not** have a `_v1` suffix in `hardwareProfile.vmSize`
(for example `Standard_B2s`, `Standard_B4ms`, `Standard_D2`, `Standard_DS2`, `Standard_F4s`, `Standard_G2`,
`Standard_L8s`, `Standard_NP10s`, `Standard_HC44rs`). The classifier detects both:

- **Explicit `_v1`, `_v2` and `_v3` SKUs**, including constrained-core variants (such as
  `Standard_DS14-4_v2` or `Standard_E16-4s_v3`) and isolated/HPC/GPU variants (`Standard_E64i_v3`,
  `Standard_HB120rs_v2`, `Standard_NC6s_v3`, `Standard_NV12s_v3`, `Standard_DC4s_v3`).
- **Unversioned v1 SKUs** across `Av1` (`Standard_A0`–`Standard_A11`, `Basic_A0`–`Basic_A4`), `Bv1`
  (`Standard_B1ls`–`Standard_B20ms`), `D` and `Ds` (`Standard_D1`–`Standard_D14`,
  `Standard_DS1`–`Standard_DS14`), `F` and `Fs` (`Standard_F1`–`Standard_F16s`), `G` and `Gs`
  (`Standard_G1`–`Standard_GS5`), `Ls` (`Standard_L4s`–`Standard_L32s`), `NP` (`Standard_NP10s`–`Standard_NP40s`),
  `HC` (`Standard_HC44rs`), `HB` (`Standard_HB60rs`), `H` (`Standard_H8`–`Standard_H16mr`), `M`
  (`Standard_M8ms`–`Standard_M128m`), `NC`/`ND`/`NV` v1, and `DCs` v1.

Modern generations (`v4`, `v5`, `v6`, `v7`) are automatically skipped and counted separately.

## February 2027 price-hike models

Microsoft's October 2026 notifications announced two February 2027 pricing updates taking effect on
**01/02/2027**:

1. **Global +25% legacy VM price hike:** ~25% worldwide increase on legacy End-of-Life v1 and v2
   series (`Bv1, D, Ds, F, Fs, G, Gs, Ls, NP, HC` and `Av2, Amv2, Dv2, Dsv2, Fsv2, Lsv2`).
2. **Regional VM price hike (8%–17%):** across seven regions (`northeurope` +17%, `francecentral` +11%,
   `francesouth` +11%, `westeurope` +9%, `norwayeast` +9%, `norwaywest` +9%, `southeastasia` +8%) for
   VM series not on the excluded list (which includes `v3` series such as `Dv3, Dsv3, Ev3, Esv3`).
   In addition, 1-year and 3-year Reserved Instance purchases and renewals for `Dv3, Dsv3, Ev3, Esv3`
   ended on **01/07/2026**, and self-service RI exchanges end on **01/02/2027**.

You can choose how the February 2027 projection is calculated on the CLI (and toggle between models
live inside the interactive HTML report):

| Option | Behaviour |
|---|---|
| `--hike-model service-health` (default) | Applies **+25%** globally to End-of-Life `v1` and `v2` series, and the regional **+8% to +17%** hike to non-excluded `v2`/`v3` series in the 7 affected regions (`0%` in UK South / UK West unless `--v3-hike` is set). |
| `--hike-model legacy-25` | Applies a blanket **+25%** across all `v1`, `v2` and `v3` legacy SKUs. |
| `--v1-hike P --v2-hike P --v3-hike P` | Custom percentage hike per generation (for example `--v1-hike 25 --v2-hike 25 --v3-hike 15`). |

## How current monthly cost is calculated (`--cost-source`)

By default (`--cost-source auto`), the tool queries **both** **Azure Cost Management** (`Microsoft.CostManagement/query`) and the **Azure Retail Prices API** (`https://prices.azure.com/api/retail/prices`):

1. **Actual billed spend (`auto` / `last-month` / `mtd`):**
   - Queries per-VM `ActualCost` and `UsageQuantity` (billed compute hours) for the **last complete calendar month** and **current month-to-date (MTD)**.
   - Using actual billed spend automatically captures **every scheduling mechanism** (built-in Portal auto-shutdown, Azure Automation start/stop runbooks, Logic Apps, AKS Cluster Autoscaler, Azure Monitor Autoscale, AVD scaling plans, and manual start/stop), as well as Azure Hybrid Benefit (AHB) and negotiated EA/MCA/CSP rates.
   - For newly deployed VMs that had `0` spend last month, `auto` falls back to their **extrapolated current month-to-date** spend.
2. **Multi-source schedule, runbook & autoscaler inference (`retail-scheduled` & fallback):**
   - **Portal VM Auto-shutdown (`microsoft.devtestlab/schedules`):** Azure's built-in VM Auto-shutdown blade (`Operations -> Auto-shutdown` on any standard IaaS VM) stores its schedule as a `Microsoft.DevTestLab/schedules` resource (`shutdown-computevm-<vmName>`).
   - **Automation Runbook / Tag schedules:** inspects VM and scale-set tags (`Autoshutdown`, `Autostartup`, `Schedule`, `StartStopSchedule`, `ShutdownSchedule`, `StopTime`, `StartTime`, `Uptime`, `PowerSchedule`, `WorkingHours`).
   - **AKS Cluster Autoscaler & Azure Monitor Autoscale (`microsoft.insights/autoscalesettings`):** surfaces `AKS Autoscale (min..max)` and `Autoscale On/Off (min..max)`.
   - When Cost Management is unavailable for a subscription (or when you select **Retail Rate × Inferred Schedule Hours** in the HTML report), VMs with active start/stop runbook tags (`~260h/mo`), daily auto-shutdown schedules (`~365h/mo`), or ephemeral CI/image-builder tags (`~20h/mo`) are costed using their inferred duty cycle rather than blindly assuming 730h/mo (24×7).

## Output formats

`--format` accepts `console` (default), `csv`, `json`, `md`, `html` or `all`. Files are written to
`--out-dir` (default `~/azure-legacy-vm-reports` with `0700` directory and `0600` file permissions):

- `…-vms.csv`: every legacy VM and VM Scale Set with SKU, generation, OS/AHB, power state, hourly rate,
  current monthly cost, February 2027 monthly cost, monthly/annual increase, retirement date and target SKU.
- `…-skus.csv`: aggregated cost and instance count per legacy SKU.
- `…-subscriptions.csv`: aggregated cost and instance count per subscription.
- `…-summary.csv`: generation summary (`v1`, `v2`, `v3`, `Total`) per tenant and across all tenants.
- `….json`: complete structured report.
- `….md`: GitHub-flavoured Markdown report.
- `….html`: self-contained dark-themed interactive dashboard with live scenario buttons, editable
  `v1 %` / `v2 %` / `v3 %` inputs, deallocated-VM cost toggle, sortable columns and instant search.

## Development & tests

```sh
python3 -m unittest discover -s tests -v
./azure-legacy-vm-report --demo --format all
```
