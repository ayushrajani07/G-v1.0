@echo off
setlocal
set ROOT=%~dp0\..\..
pushd "%ROOT%"
set PYTHONPATH=%ROOT%
"%ROOT%\.venv\Scripts\python.exe" scripts\ml\path_forecast_grid_eval.py --discover --indices NIFTY --tags this_week --offsets 0 --horizons 30,60 --windows 60,180 --k 10,15 --modes auto,hybrid --bucket-ms 60000 --at mid --last-days 10 --scales 1.3,1.5,2.0
popd
endlocal
