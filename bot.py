#!/usr/bin/env python3
"""Telegram TXT lead shuffler. Python 3.10+, no third-party packages."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from shuffle_core import ShuffleError, shuffle_leads

MAX_BYTES = 19_000_000
ENV_PATH = Path(__file__).resolve().with_name(".env")
LOG = logging.getLogger("lead_shuffler")
HELP = (
    "Send me a .txt file with one lead per line (up to 19 MB).\n\n"
    "I'll jumble the whole lines and send you a new .txt file. Every source "
    "line moves to a different position; each lead's details stay together. "
    "Duplicates and blank lines are kept, so identical lines may look unchanged.\n\n"
    "Upload the original file again whenever you want another shuffle.\n"
    "/help — instructions\n/id — your Telegram user ID\n/privacy — file handling"
)


class TelegramError(RuntimeError):
    """Safe error that never includes a token-bearing request URL."""

    def __init__(self, code: int = 0, retry_after: int = 0):
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Telegram request failed (code {code}).")


def _api_result(raw: bytes):
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise TelegramError() from None
    if not isinstance(payload, dict):
        raise TelegramError()
    if not payload.get("ok"):
        raise TelegramError(
            payload.get("error_code", 0),
            payload.get("parameters", {}).get("retry_after", 0),
        )
    return payload.get("result")


class TelegramAPI:
    def __init__(self, token: str):
        self._root = f"https://api.telegram.org/bot{token}/"
        self._files = f"https://api.telegram.org/file/bot{token}/"

    def call(self, method: str, fields=None, document=None, timeout=90):
        fields = fields or {}
        if document is None:
            body = urlencode(fields).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        else:
            # Filenames are generated locally, never taken from the uploaded name.
            filename, contents = document
            boundary = "LeadShuffle" + secrets.token_hex(24)
            parts = []
            for key, value in fields.items():
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
                    f'\r\n\r\n{value}\r\n'.encode("utf-8")
                )
            parts.extend([
                (f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
                 f'filename="{filename}"\r\nContent-Type: application/octet-stream'
                 '\r\n\r\n').encode("ascii"),
                contents,
                f"\r\n--{boundary}--\r\n".encode("ascii"),
            ])
            body = b"".join(parts)
            content_type = f"multipart/form-data; boundary={boundary}"
        request = Request(self._root + method, data=body,
                          headers={"Content-Type": content_type})
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as error:
            with error:
                raw = error.read()
            try:
                return _api_result(raw)
            except TelegramError as api_error:
                if not api_error.code:
                    raise TelegramError(error.code) from None
                raise api_error from None
        except (URLError, OSError, TimeoutError):
            raise TelegramError() from None
        return _api_result(raw)

    def say(self, chat_id: int, text: str):
        return self.call("sendMessage", {"chat_id": chat_id, "text": text})

    def download(self, file_id: str) -> bytes:
        info = self.call("getFile", {"file_id": file_id})
        if info.get("file_size", 0) > MAX_BYTES:
            raise ShuffleError("Please send a .txt file smaller than 19 MB.")
        path = info.get("file_path")
        if not path:
            raise TelegramError()
        try:
            with urlopen(self._files + quote(path, safe="/"), timeout=90) as response:
                data = response.read(MAX_BYTES + 1)
        except (HTTPError, URLError, OSError, TimeoutError):
            raise TelegramError() from None
        if len(data) > MAX_BYTES:
            raise ShuffleError("Please send a .txt file smaller than 19 MB.")
        return data


def handle_message(api: TelegramAPI, message: dict, allowed_ids: set[int]):
    chat = message.get("chat", {})
    # Lead files are only handled in direct messages to this bot.
    if chat.get("type") != "private":
        return
    chat_id = chat["id"]
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "")
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text else ""
    if command == "/id":
        api.say(chat_id, f"Your Telegram user ID: {user_id}")
        return
    if allowed_ids and user_id not in allowed_ids:
        api.say(chat_id, "This is a private bot. Your account is not on its allowed list.")
        return
    if command == "/privacy":
        api.say(chat_id, "The bot processes files in memory and does not save lead files "
                "or log their contents. Your uploaded and returned files remain in your "
                "Telegram chat until you delete them there.")
        return
    document = message.get("document")
    if not document:
        api.say(chat_id, HELP)
        return
    if not document.get("file_name", "").lower().endswith(".txt"):
        api.say(chat_id, "Please upload a .txt file with one lead per line.")
        return
    if document.get("file_size", 0) > MAX_BYTES:
        api.say(chat_id, "That file is too large. Please send a .txt file smaller than 19 MB.")
        return
    try:
        data = api.download(document["file_id"])
        shuffled, count = shuffle_leads(data)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"shuffled_leads_{stamp}_{secrets.token_hex(3)}.txt"
        api.call("sendDocument", {
            "chat_id": chat_id,
            "caption": f"Done — {count:,} lines shuffled. Every source line moved. "
                       "Identical duplicates may look unchanged.",
        }, document=(filename, shuffled), timeout=120)
    except ShuffleError as error:
        api.say(chat_id, str(error))
    except TelegramError as error:
        LOG.warning("File request failed (code %s).", error.code)
        api.say(chat_id, "I couldn't download or return that file. Please upload it again "
                "in a moment. If it keeps failing, try a smaller .txt file.")


def load_config(path: Path = ENV_PATH):
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                os.environ.setdefault(key.strip(), value)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token):
        raise ValueError("Add your BotFather token to .env, or run: python3 bot.py --setup")
    raw_ids = os.environ.get("ALLOWED_USER_IDS", "").strip()
    try:
        allowed = {int(value.strip()) for value in raw_ids.split(",") if value.strip()}
    except ValueError:
        raise ValueError("ALLOWED_USER_IDS must be comma-separated numeric Telegram user IDs.") from None
    if any(value <= 0 for value in allowed):
        raise ValueError("ALLOWED_USER_IDS must contain positive user IDs.")
    return token, allowed


def setup():
    print("Create a bot with https://t.me/BotFather using /newbot, then copy its token.")
    token = getpass.getpass("Paste your bot token (hidden): ").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token):
        raise ValueError("That does not look like a BotFather token. Run setup again.")
    if ENV_PATH.exists():
        raise ValueError("A .env file already exists. Edit it to change the token.")
    fd = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(f"TELEGRAM_BOT_TOKEN={token}\nALLOWED_USER_IDS=\n")
    print("Saved .env. Start the bot with: python3 bot.py")


def run(api: TelegramAPI, allowed_ids: set[int]):
    me = api.call("getMe")
    if api.call("getWebhookInfo").get("url"):
        raise ValueError("This token already uses a webhook. Use a new BotFather bot, "
                         "or remove its webhook before running this polling bot.")
    LOG.info("Running @%s. Open it in Telegram and upload a .txt file. Ctrl+C stops it.",
             me.get("username", "your_bot"))
    offset = 0
    delay = 1
    while True:
        try:
            updates = api.call("getUpdates", {
                "offset": offset, "timeout": 30,
                "allowed_updates": json.dumps(["message"]),
            }, timeout=45)
        except TelegramError as error:
            if error.code in (401, 404):
                raise ValueError("Telegram rejected the token. Check your BotFather token in .env.") from None
            if error.code == 409:
                raise ValueError("Another copy of this bot is running. Stop it and restart this copy.") from None
            wait = max(delay, error.retry_after)
            LOG.warning("Telegram connection interrupted (code %s); retrying in %ss.", error.code, wait)
            time.sleep(wait)
            delay = min(delay * 2, 30)
            continue
        delay = 1
        for update in updates:
            try:
                if "message" in update:
                    handle_message(api, update["message"], allowed_ids)
            except TelegramError as error:
                LOG.warning("Could not respond (code %s). Upload again to retry.", error.code)
                if error.retry_after:
                    time.sleep(error.retry_after)
            except Exception as error:
                # Do not print request URLs, tokens, message bodies or lead content.
                LOG.error("Could not process a message (%s). Upload again to retry.", type(error).__name__)
            offset = update["update_id"] + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true", help="save your token locally")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.setup:
            setup()
            return
        token, allowed_ids = load_config()
        run(TelegramAPI(token), allowed_ids)
    except KeyboardInterrupt:
        print("\nBot stopped.")
    except (ValueError, TelegramError, OSError) as error:
        if isinstance(error, OSError):
            LOG.error("Could not read or write local configuration (%s).", type(error).__name__)
        else:
            LOG.error("%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
