# Centech Scripts

This repository contains automation scripts for payroll processing and related data pipelines.

## Payroll Pipeline

For full setup and usage instructions, see the payroll operations guide:

[payroll/PAYROLL.md](payroll/PAYROLL.md)

---

## Requirements

- Python 3.10+
- AWS CLI installed and configured

---

## Setup

### 1. Create and activate virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2. Upgrade pip

```powershell
python -m pip install --upgrade pip
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure AWS

If you do not have credentials yet, ask DevOps for your Access Key ID and Secret Access Key and IAM account.
