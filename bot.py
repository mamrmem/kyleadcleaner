
import io
import logging
import os
import re

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("phone-number-extractor")


def owner_id():
    try:
        return int(OWNER_TELEGRAM_ID) if OWNER_TELEGRAM_ID else None
    except ValueError:
        return None


def is_owner(user_id):
    oid = owner_id()
    return oid is None or user_id == oid


async def require_owner(update):
    if update.effective_chat.type != ChatType.PRIVATE:
        return False

    if not is_owner(update.effective_user.id):
        await update.effective_message.reply_text("⛔ This bot is private.")
        return False

    return True


def decode_file(raw):
    if not raw:
        return ""

    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass

    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass

    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def normalize_uk_mobile(candidate):
    """
    Normalize supported UK mobile formats to +44XXXXXXXXXX.

    Accepted examples:
      07784726262
      07742 472744
      +447727362666
      447227473722
      7737372643
    """
    digits = re.sub(r"\D", "", candidate)

    # 07XXXXXXXXX -> 447XXXXXXXXX
    if len(digits) == 11 and digits.startswith("07"):
        return "+44" + digits[1:]

    # 447XXXXXXXXX -> +447XXXXXXXXX
    if len(digits) == 12 and digits.startswith("447"):
        return "+" + digits

    # 7XXXXXXXXX -> +447XXXXXXXXX
    if len(digits) == 10 and digits.startswith("7"):
        return "+44" + digits

    return None


def extract_numbers(text):
    """
    Find UK mobile-like numbers with optional spaces, dashes,
    brackets, +44 / 44 / 0 / bare-7 prefixes.
    """
    pattern = re.compile(
        r"""
        (?<!\d)
        (?:
            \+?44[\s().-]*7(?:[\s().-]*\d){9}
            |
            0[\s().-]*7(?:[\s().-]*\d){9}
            |
            7(?:[\s().-]*\d){9}
        )
        (?!\d)
        """,
        re.VERBOSE,
    )

    seen = set()
    results = []

    for match in pattern.finditer(text):
        normalized = normalize_uk_mobile(match.group(0))
        if normalized and normalized not in seen:
            seen.add(normalized)
            results.append(normalized)

    return results


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update):
        return

    await update.message.reply_text(
        "📱 <b>Phone Number Extractor</b>\n\n"
        "Upload a .txt or .csv file and I'll extract UK mobile numbers.\n\n"
        "Supported examples:\n"
        "<code>07784726262</code>\n"
        "<code>07742 472744</code>\n"
        "<code>+447727362666</code>\n"
        "<code>447227473722</code>\n"
        "<code>7737372643</code>\n\n"
        "Output is normalised to <code>+44...</code>, one number per line.",
        parse_mode="HTML",
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update):
        return

    doc = update.message.document
    filename = doc.file_name or "input.txt"

    if not filename.lower().endswith((".txt", ".csv")):
        await update.message.reply_text("Please upload a .txt or .csv file.")
        return

    tg_file = await doc.get_file()
    raw = bytes(await tg_file.download_as_bytearray())
    text = decode_file(raw)

    numbers = extract_numbers(text)

    if not numbers:
        await update.message.reply_text("No UK mobile numbers found.")
        return

    output = "\n".join(numbers) + "\n"

    original_name = filename.rsplit(".", 1)[0].strip() or "file"
    output_name = f"{original_name} extracted numbers.txt"

    data = io.BytesIO(output.encode("utf-8"))
    data.name = output_name

    await update.message.reply_document(
        document=data,
        filename=output_name,
        caption=f"✅ {len(numbers):,} valid UK numbers",
    )


async def error_handler(update, context):
    log.exception("Unhandled bot error", exc_info=context.error)


def main():
    if not TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_error_handler(error_handler)

    log.info("Phone Number Extractor Bot running")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
