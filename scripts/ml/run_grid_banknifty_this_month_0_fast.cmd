@echo off
setlocal
set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized
"C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\python.exe" scripts\ml\path_forecast_grid_eval.py --discover --indices BANKNIFTY --tags this_month --offsets 0 --horizons 30,60 --windows 60,120 --k 10,15 --modes auto --bucket-ms 60000 --at mid --last-days 10
endlocal
