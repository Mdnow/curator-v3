@echo off
title Проверка куратора (verify)
echo ============================================
echo   Кнопка проверки: КУРАТОР v3
echo   Проверяет код перед тем, как ему верить.
echo ============================================
echo.
set ERR=0

echo [1/3] Проверка синтаксиса Python...
cd /d "C:\dev\opencode\ежедневник\curator-v3"
python -m py_compile backend\main.py backend\auth.py backend\crypto.py backend\db.py backend\models.py backend\ai.py backend\routes\notes.py backend\routes\tasks.py backend\routes\dreams.py backend\routes\chat.py backend\routes\favorites.py backend\routes\backup.py backend\routes\goals.py backend\routes\insights.py backend\routes\health.py test_all.py test_feat.py
if errorlevel 1 (
    echo   ! ОШИБКА: синтаксис Python сломан.
    set ERR=1
) else (
    echo   OK
)
echo.

echo [2/3] Проверка ошибок кода (ruff)...
python -m ruff check
if errorlevel 1 (
    echo   ! ОШИБКА: найдены ошибки в коде.
    set ERR=1
) else (
    echo   OK
)
echo.

echo [3/3] Проверка фронтенда (node --check)...
node --check frontend\js\app.js
if errorlevel 1 (
    echo   ! ОШИБКА: фронтенд сломан.
    set ERR=1
) else (
    echo   OK
)
echo.

echo ============================================
if %ERR%==0 (
    echo   ВСЁ ЧИСТО - код готов.
) else (
    echo   НЕ ГОТОВО - есть ошибки, смотри выше.
)
echo ============================================
echo.
pause
