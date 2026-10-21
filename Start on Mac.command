#!/bin/sh
cd "$(dirname "$0")" || exit 1
bundled_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ -x "$bundled_python" ]; then
    bot_python="$bundled_python"
else
    bot_python=python3
fi
if ! "$bot_python" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
    echo "Install Python 3.10 or newer from https://www.python.org/downloads/ and try again."
    read -r _reply
    exit 1
fi
if [ ! -f .env ] && [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    "$bot_python" bot.py --setup || exit 1
fi
"$bot_python" bot.py
echo "Press Enter to close."
read -r _reply
