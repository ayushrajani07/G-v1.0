param(
    [int[]]$Ports = @(8003,9500)
)

foreach ($port in $Ports) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            $pid_list = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($pidv in $pid_list) {
                try {
                    Write-Host ("Stopping process on port {0} (PID={1})" -f $port, $pidv) -ForegroundColor Yellow
                    Stop-Process -Id $pidv -Force -ErrorAction SilentlyContinue
                } catch {
                    Write-Host ("Failed to stop PID {0} on port {1}: {2}" -f $pidv, $port, $($_.Exception.Message)) -ForegroundColor Red
                }
            }
        } else {
            Write-Host ("No listener on port {0}" -f $port)
        }
    } catch {
        Write-Host ("Error checking port {0}: {1}" -f $port, $($_.Exception.Message)) -ForegroundColor Red
    }
}

Start-Sleep -Milliseconds 300
Write-Host "Done." -ForegroundColor Green
