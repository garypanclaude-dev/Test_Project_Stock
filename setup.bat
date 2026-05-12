@echo off
chcp 65001 >nul
echo ============================
echo  股票分析平台 - 初始安裝
echo ============================
echo.

echo [1/3] 建立 Python 虛擬環境並安裝套件...
cd backend
python -m venv venv
call venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt
if errorlevel 1 (
    echo 錯誤：Python 套件安裝失敗
    pause
    exit /b 1
)
call venv\Scripts\deactivate.bat
cd ..

echo.
echo [2/3] 安裝前端套件（已完成，跳過）...

echo.
echo [3/3] 安裝完成！
echo.
echo 請執行 start.bat 啟動平台
echo.
pause
