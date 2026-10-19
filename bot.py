"""Private, single-owner Telegram document cleaner. Run one worker."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

from cleaner import MAX_BYTES, clean_bytes, export_records, format_record

ROOT = Path(__file__).resolve().parent
KEYBOARD = {"keyboard": [["Next lead", "Export file"], ["Clear file"]], "resize_keyboard": True}
HELP = ("Send a .txt or .rtf file (up to 5 MB). I will return cleaned_leads.txt in your nine-field format.\n\n"
        "/lead — next cleaned record\n/export — download the current cleaned file\n"
        "/reset — return to the first record\n/clear — remove this file from bot memory\n"
        "/myid — show your Telegram ID\n\n"
        "A new upload replaces the previous file. Missing fields show Not provided. "
        "Bank names are copied only when stated; no bank ownership or account checks are performed.")


def load_env():
    """Read simple KEY=value entries; existing environment values take priority."""
    file = ROOT / ".env"
    if file.exists():
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                os.environ.setdefault(key, value)


class TelegramError(Exception):
    def __init__(self, status=0, retry_after=5):
        super().__init__("Telegram request failed")
        self.status = status
        self.retry_after = min(60, max(1, retry_after))


class Telegram:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.files = f"https://api.telegram.org/file/bot{token}/"

    def call(self, method, payload, file_bytes=None):
        headers = {}
        if file_bytes is None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        else:
            boundary = "boundary" + uuid.uuid4().hex
            pieces = []
            for key, value in payload.items():
                pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="cleaned_leads.txt"\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n'.encode())
            pieces.extend([file_bytes, f"\r\n--{boundary}--\r\n".encode()])
            body = b"".join(pieces)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        try:
            with urlopen(Request(self.base + method, data=body, headers=headers), timeout=50) as response:
                result = json.load(response)
        except HTTPError as exc:
            delay = 5
            try:
                delay = int(json.loads(exc.read(16384)).get("parameters", {}).get("retry_after", 5))
            except (ValueError, TypeError):
                pass
            raise TelegramError(exc.code, delay) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise TelegramError() from None
        if not result.get("ok"):
            raise TelegramError(result.get("error_code", 0))
        return result["result"]

    def send(self, chat_id, text):
        return self.call("sendMessage", {"chat_id": chat_id, "text": text,
                                        "reply_markup": KEYBOARD})

    def document(self, chat_id, text, caption):
        return self.call("sendDocument", {"chat_id": chat_id, "caption": caption}, text.encode("utf-8"))

    def download(self, file_id):
        details = self.call("getFile", {"file_id": file_id})
        if details.get("file_size", 0) > MAX_BYTES:
            raise ValueError("File exceeds the 5 MB limit.")
        path = details.get("file_path")
        if not path:
            raise TelegramError()
        try:
            with urlopen(self.files + quote(path, safe="/"), timeout=50) as response:
                data = response.read(MAX_BYTES + 1)
        except (URLError, TimeoutError, OSError):
            raise TelegramError() from None
        if len(data) > MAX_BYTES:
            raise ValueError("File exceeds the 5 MB limit.")
        return data


class CleanerBot:
    def __init__(self, telegram, owner_id):
        self.telegram = telegram
        self.owner_id = owner_id
        self.records = []
        self.cursor = 0

    def handle(self, update):
        message = update.get("message", {})
        chat = message.get("chat", {})
        if chat.get("type") != "private":
            return
        sender = message.get("from", {}).get("id")
        text = message.get("text", "").strip()
        # The bootstrap command discloses only the requesting user's own ID.
        if text == "/myid":
            self.telegram.send(chat["id"], f"Your Telegram ID: {sender}")
            return
        if not self.owner_id or sender != self.owner_id:
            return
        chat_id = chat["id"]
        if "document" in message:
            document = message["document"]
            name = document.get("file_name", "")
            try:
                if Path(name).suffix.lower() not in {".txt", ".rtf"}:
                    raise ValueError("Upload a .txt or .rtf file.")
                if document.get("file_size", 0) > MAX_BYTES:
                    raise ValueError("File exceeds the 5 MB limit.")
                records = clean_bytes(self.telegram.download(document["file_id"]), name)
                output = export_records(records)
                if len(output.encode("utf-8")) > 15 * 1024 * 1024:
                    raise ValueError("Cleaned output is too large; split your input into smaller files.")
            except ValueError as exc:
                self.telegram.send(chat_id, f"Could not clean this upload: {exc}\nYour previous file is unchanged.")
                return
            self.telegram.document(chat_id, output, f"{len(records)} records cleaned. Use /lead to view one at a time.")
            self.records = records
            self.cursor = 0
        elif text in ("/start", "/help"):
            self.telegram.send(chat_id, HELP)
        elif text in ("/clear", "Clear file"):
            self.records = []
            self.cursor = 0
            self.telegram.send(chat_id, "Cleared from bot memory. Telegram messages and downloaded files remain in your chat.")
        elif text in ("/lead", "Next lead", "/export", "Export file", "/reset"):
            if not self.records:
                self.telegram.send(chat_id, "Upload a .txt or .rtf file first.")
            elif text in ("/export", "Export file"):
                self.telegram.document(chat_id, export_records(self.records), f"{len(self.records)} cleaned records.")
            elif text == "/reset":
                self.cursor = 0
                self.telegram.send(chat_id, "Back at the beginning. Use /lead.")
            elif self.cursor >= len(self.records):
                self.telegram.send(chat_id, "End of this file. Use /reset to start again or upload another file.")
            else:
                output = format_record(self.records[self.cursor])
                if len(output.encode("utf-16-le")) // 2 <= 4000:
                    self.telegram.send(chat_id, output)
                else:
                    self.telegram.document(chat_id, output, "This record is too long for one message; here it is as a text file.")
                self.cursor += 1
        else:
            self.telegram.send(chat_id, "Upload a .txt or .rtf file, or use /help.")


def main():
    load_env()
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise SystemExit("Set a valid BOT_TOKEN in .env or the hosting environment.")
    try:
        owner_id = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))
        if owner_id < 0:
            raise ValueError
    except ValueError:
        raise SystemExit("OWNER_TELEGRAM_ID must be a positive numeric user ID, or 0 for setup.")
    directory = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "updates.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY, offset INTEGER)")
    db.execute("INSERT OR IGNORE INTO progress VALUES (1, 0)")
    db.commit()
    telegram = Telegram(token)
    bot = CleanerBot(telegram, owner_id)
    telegram.call("deleteWebhook", {"drop_pending_updates": False})
    logging.info("Cleaner started. Uploaded documents and cleaned fields are not logged or saved to disk.")
    if not owner_id:
        logging.info("Setup mode: send /myid, set OWNER_TELEGRAM_ID, and restart. Uploads are disabled.")
    try:
        while True:
            try:
                offset = db.execute("SELECT offset FROM progress WHERE id=1").fetchone()[0]
                updates = telegram.call("getUpdates", {"offset": offset, "timeout": 30,
                                                       "allowed_updates": ["message"]})
                for update in updates:
                    try:
                        bot.handle(update)
                    except TelegramError as exc:
                        if exc.status not in (400, 403):
                            raise
                        # A permanent error (e.g. blocked bot) must not trap polling on one update.
                        logging.warning("Telegram could not deliver or retrieve this item.")
                        if exc.status == 400:
                            message = update.get("message", {})
                            if (message.get("from", {}).get("id") == owner_id
                                    and message.get("chat", {}).get("type") == "private"):
                                try:
                                    telegram.send(message["chat"]["id"], "Telegram could not process this item. Please upload the file again.")
                                except TelegramError as notice_error:
                                    if notice_error.status not in (400, 403):
                                        raise
                    except Exception:
                        # Do not print raw exceptions, tracebacks, credentials or input records.
                        logging.error("An upload could not be processed. Resend a smaller plain-text file.")
                        message = update.get("message", {})
                        if (message.get("from", {}).get("id") == owner_id
                                and message.get("chat", {}).get("type") == "private"):
                            telegram.send(message["chat"]["id"], "Could not process this file. Try exporting it as UTF-8 .txt.")
                    db.execute("UPDATE progress SET offset=? WHERE id=1", (update["update_id"] + 1,))
                    db.commit()
            except TelegramError as exc:
                if exc.status in (401, 404):
                    raise SystemExit("Telegram rejected the bot token. Check BOT_TOKEN.")
                if exc.status == 409:
                    raise SystemExit("Another bot worker is running. Stop it and run one instance only.")
                logging.warning("Telegram request failed; retrying shortly.")
                time.sleep(exc.retry_after)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
