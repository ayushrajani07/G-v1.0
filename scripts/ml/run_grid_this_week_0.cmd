@echo off
setlocal
set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized
"C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\python.exe" scripts\ml\path_forecast_grid_eval.py --discover --indices NIFTY,SENSEX,BANKNIFTY --tags this_week --offsets 0 --horizons 30,60 --windows 0,60,120,180 --k 10,15,20 --modes auto,hybrid,retrieval --bucket-ms 60000 --at end
endlocal
