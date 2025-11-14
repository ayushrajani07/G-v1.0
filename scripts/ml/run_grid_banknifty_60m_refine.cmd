@echo off
setlocal
set ROOT=%~dp0\..\..
pushd "%ROOT%"
set PYTHONPATH=%ROOT%
"%ROOT%\.venv\Scripts\python.exe" scripts\ml\path_forecast_grid_eval.py --discover --indices BANKNIFTY --tags this_month --offsets 0 --horizons 60 --windows 60,180 --k 10,15,20 --modes auto,hybrid --bucket-ms 60000 --at mid --last-days 15 --scales 1.0
popd
endlocal
