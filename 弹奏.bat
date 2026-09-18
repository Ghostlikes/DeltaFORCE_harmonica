@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 三角洲行动 口琴自动弹奏
:menu
echo ============================================
echo   三角洲行动 口琴玩法 - 自动演奏
echo   曲目: I Really Want to Stay at Your House
echo ============================================
echo   1 = 干跑(只打印时间轴,不按键)
echo   2 = 自动演奏(8 秒倒计时, 期间切到游戏; F10 停止)
echo   3 = 耳朵校准(确认中键/右键作用)
echo   4 = 输入自检(验证键鼠注入)
echo   5 = 只弹第 1 小节测试
echo   0 = 退出
echo ============================================
set /p c=请输入编号后回车:
if "%c%"=="1" python play.py --dry-run
if "%c%"=="2" python play.py --countdown 8
if "%c%"=="3" python play.py --calib
if "%c%"=="4" python dev\selftest2.py vk
if "%c%"=="5" python play.py --from-measure 1 --to-measure 1 --countdown 5
if "%c%"=="0" exit /b
echo.
pause
goto menu
