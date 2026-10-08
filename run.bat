@echo off
title Mini E-Commerce Flask Server
cd /d "%~dp0"
set "PYTHONPATH=C:\Users\Zaky\AppData\Local\Programs\Python\Python314\Lib\site-packages;%PYTHONPATH%"
if exist "C:\Python314\python.exe" (
    "C:\Python314\python.exe" app.py
) else (
    python app.py
)
pause

