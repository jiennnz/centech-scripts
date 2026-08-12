param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$StartDate,

    [Parameter(Mandatory = $true, Position = 1)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$EndDate,

    [Parameter(Position = 2)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$RunDate = (Get-Date).ToString('yyyy-MM-dd')
)

$ErrorActionPreference = 'Stop'

if ($EndDate -lt $StartDate) {
    throw 'EndDate must not be before StartDate.'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$storeConfig = Join-Path $repoRoot 'financial\sales_export_comparison\rules\century.yaml'
$sessionFiles = @(
    'flexepos/.auth/session-1.json',
    'flexepos/.auth/session-2.json'
)

foreach ($session in $sessionFiles) {
    if (-not (Test-Path (Join-Path $repoRoot $session))) {
        throw "Saved FlexePOS session not found: $session"
    }
}

$stores = @()
$insideStores = $false
foreach ($line in Get-Content $storeConfig) {
    if ($line -match '^stores:\s*$') {
        $insideStores = $true
        continue
    }
    if ($insideStores -and $line -match '^\S') {
        break
    }
    if ($insideStores -and $line -match '^\s+-\s+"(\d+)"\s*$') {
        $stores += $Matches[1]
    }
}

if ($stores.Count -eq 0) {
    throw "No stores were found in $storeConfig"
}

$outputDirectory = Join-Path $repoRoot "flexepos\runs\$RunDate\${StartDate}_${EndDate}\payroll"
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

$completedStores = @()
$pendingStores = @()
foreach ($store in $stores) {
    $storeDirectory = Join-Path $outputDirectory $store
    $summaryPath = Join-Path $storeDirectory 'payroll_summary.json'
    $timeclocksPath = Join-Path $storeDirectory 'employee_timeclocks.json'
    $isComplete = $false

    if ((Test-Path $summaryPath) -and (Test-Path $timeclocksPath)) {
        try {
            $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json
            $timeclockData = Get-Content $timeclocksPath -Raw | ConvertFrom-Json
            $employeeRecords = @($timeclockData.employees)
            $failedRecords = @($employeeRecords | Where-Object { $_.status -eq 'failed' })
            $isComplete = (
                $summary.employeeCount -gt 0 -and
                $employeeRecords.Count -eq $summary.employeeCount -and
                $failedRecords.Count -eq 0
            )
        }
        catch {
            $isComplete = $false
        }
    }

    if ($isComplete) {
        $completedStores += $store
    }
    else {
        $pendingStores += $store
    }
}

$queue = [System.Collections.Queue]::new()
foreach ($store in $pendingStores) {
    $queue.Enqueue($store)
}

$timer = [System.Diagnostics.Stopwatch]::StartNew()
$activeJobs = @()
$failedStores = @()

Write-Host "Payroll scrape: $StartDate through $EndDate"
Write-Host "Stores: $($stores.Count); concurrent sessions: 2"
Write-Host "Resuming: $($completedStores.Count) complete; $($pendingStores.Count) remaining"
Write-Host 'Press Ctrl+C to cancel.'

try {
    while ($queue.Count -gt 0 -or $activeJobs.Count -gt 0) {
        while ($queue.Count -gt 0 -and $activeJobs.Count -lt $sessionFiles.Count) {
            $store = [string]$queue.Dequeue()
            $usedSessions = @($activeJobs | ForEach-Object { $_.PayrollSession })
            $session = $sessionFiles |
                Where-Object { $_ -notin $usedSessions } |
                Select-Object -First 1
            $staleProgressPath = Join-Path $outputDirectory "$store\payroll_progress.json"
            Remove-Item $staleProgressPath -Force -ErrorAction SilentlyContinue

            $job = Start-Job -ArgumentList @(
                $repoRoot,
                $RunDate,
                $StartDate,
                $EndDate,
                $store,
                $session
            ) -ScriptBlock {
                param($repoRoot, $runDate, $startDate, $endDate, $store, $session)

                Set-Location $repoRoot
                $storeTimer = [System.Diagnostics.Stopwatch]::StartNew()
                & npm.cmd --prefix flexepos run payroll -- `
                    --store $store `
                    --start $startDate `
                    --end $endDate `
                    --mode headless `
                    --auth-state $session `
                    --output-dir "runs/$runDate/${startDate}_${endDate}/payroll/$store"
                $exitCode = $LASTEXITCODE
                $storeTimer.Stop()

                [pscustomobject]@{
                    PayrollResult = $true
                    Store = $store
                    Session = $session
                    ExitCode = $exitCode
                    DurationMs = $storeTimer.ElapsedMilliseconds
                }
            }

            $job | Add-Member -NotePropertyName PayrollStore -NotePropertyValue $store
            $job | Add-Member -NotePropertyName PayrollSession -NotePropertyValue $session
            $progressId = 11 + [array]::IndexOf($sessionFiles, $session)
            $job | Add-Member -NotePropertyName PayrollProgressId -NotePropertyValue $progressId
            $job | Add-Member -NotePropertyName PayrollCompletedEmployees -NotePropertyValue 0
            $job | Add-Member -NotePropertyName PayrollTotalEmployees -NotePropertyValue 0
            $job | Add-Member -NotePropertyName PayrollEmployeeStatus -NotePropertyValue 'starting'
            $activeJobs += $job
        }

        $currentFinishedCount = $completedStores.Count + $failedStores.Count
        $currentOverallPercent = [math]::Floor(($currentFinishedCount / $stores.Count) * 100)
        Write-Progress `
            -Id 1 `
            -Activity 'Scraping payroll timeclocks' `
            -Status "$currentFinishedCount of $($stores.Count) complete; $($failedStores.Count) failed" `
            -PercentComplete $currentOverallPercent

        foreach ($activeJob in @($activeJobs)) {
            $progressPath = Join-Path $outputDirectory "$($activeJob.PayrollStore)\payroll_progress.json"
            if (Test-Path $progressPath) {
                try {
                    $storeProgress = Get-Content $progressPath -Raw | ConvertFrom-Json
                    $activeJob.PayrollCompletedEmployees = [int]$storeProgress.completedEmployees
                    $activeJob.PayrollTotalEmployees = [int]$storeProgress.totalEmployees
                    $activeJob.PayrollEmployeeStatus = [string]$storeProgress.status
                }
                catch {
                    # The worker may be replacing the progress file while it is read.
                }
            }

            $employeePercent = if ($activeJob.PayrollTotalEmployees -gt 0) {
                [math]::Floor(
                    ($activeJob.PayrollCompletedEmployees / $activeJob.PayrollTotalEmployees) * 100
                )
            }
            else {
                0
            }
            Write-Progress `
                -Id $activeJob.PayrollProgressId `
                -ParentId 1 `
                -Activity "Store $($activeJob.PayrollStore)" `
                -Status "$($activeJob.PayrollCompletedEmployees)/$($activeJob.PayrollTotalEmployees) employees; $($activeJob.PayrollEmployeeStatus)" `
                -PercentComplete $employeePercent
        }

        $finishedJobs = @(Wait-Job -Job $activeJobs -Any -Timeout 1)
        foreach ($finishedJob in $finishedJobs) {
            if ($null -eq $finishedJob) {
                continue
            }

            $receiveErrors = @()
            $jobOutput = @(
                Receive-Job `
                    -Job $finishedJob `
                    -ErrorAction SilentlyContinue `
                    -ErrorVariable +receiveErrors
            )
            $result = $jobOutput |
                Where-Object { $_.PayrollResult -eq $true } |
                Select-Object -Last 1

            if ($null -ne $result -and $result.ExitCode -eq 0) {
                $completedStores += [string]$result.Store
                Write-Host "Completed store $($result.Store) in $([TimeSpan]::FromMilliseconds($result.DurationMs))"
            }
            else {
                $failedStore = if ($null -ne $result) { [string]$result.Store } else { [string]$finishedJob.PayrollStore }
                $failedStores += $failedStore
                Write-Warning "Store $failedStore failed; continuing."
                if ($receiveErrors.Count -gt 0) {
                    $failureDetail = $receiveErrors |
                        ForEach-Object { $_.Exception.Message } |
                        Where-Object { $_ -and $_ -notmatch '^npm warn Unknown env config' } |
                        Select-Object -Last 1
                    if ($failureDetail) {
                        Write-Warning $failureDetail
                    }
                }
            }

            Remove-Job -Job $finishedJob -Force
            Write-Progress `
                -Id $finishedJob.PayrollProgressId `
                -ParentId 1 `
                -Activity "Store $($finishedJob.PayrollStore)" `
                -Completed
            $activeJobs = @($activeJobs | Where-Object { $_.Id -ne $finishedJob.Id })
        }

        $finishedCount = $completedStores.Count + $failedStores.Count
        $percent = [math]::Floor(($finishedCount / $stores.Count) * 100)
        $activeStoreLabels = @($activeJobs | ForEach-Object { $_.PayrollStore }) -join ', '
        Write-Progress `
            -Id 1 `
            -Activity 'Scraping payroll timeclocks' `
            -Status "$finishedCount of $($stores.Count) complete; $($failedStores.Count) failed; active: $activeStoreLabels" `
            -PercentComplete $percent
    }
}
finally {
    Write-Progress -Id 1 -Activity 'Scraping payroll timeclocks' -Completed
    foreach ($job in @($activeJobs)) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    $timer.Stop()
}

$benchmark = [ordered]@{
    run_date = $RunDate
    start_date = $StartDate
    end_date = $EndDate
    store_count = $stores.Count
    completed_stores = $completedStores.Count
    failed_stores = $failedStores.Count
    failed_store_numbers = @($failedStores)
    concurrent_sessions = $sessionFiles.Count
    sessions = @($sessionFiles)
    total_ms = $timer.ElapsedMilliseconds
    total_duration = $timer.Elapsed.ToString()
}

$benchmarkPath = Join-Path $outputDirectory 'overall_benchmark.json'
$benchmark | ConvertTo-Json -Depth 4 | Set-Content -Path $benchmarkPath -Encoding UTF8

Write-Host ''
Write-Host "Completed: $($completedStores.Count)/$($stores.Count) stores"
Write-Host "Failed: $($failedStores.Count)"
Write-Host "Overall duration: $($timer.Elapsed)"
Write-Host "Benchmark: $benchmarkPath"

if ($failedStores.Count -gt 0) {
    exit 1
}
