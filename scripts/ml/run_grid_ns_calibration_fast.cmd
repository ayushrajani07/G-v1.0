@echo off
setlocal
set ROOT=%~dp0\..\..
pushd "%ROOT%"
set PYTHONPATH=%ROOT%
"%ROOT%\.venv\Scripts\python.exe" scripts\ml\path_forecast_grid_eval.py --discover --indices NIFTY,SENSEX --tags this_week --offsets 0 --horizons 30,60 --windows 60,180 --k 10,15 --modes auto --bucket-ms 60000 --at mid --last-days 10 --scales 0.7,0.9,1.0,1.1
popd
endlocal
