"""Telegram bot that annotates uploaded synthetic lead files using an imported sort-code directory."""
import asyncio
import csv
import io
import logging
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_ID = os.environ.get('ADMIN_USER_ID', '').strip()
DB_PATH = Path(os.environ.get('DB_PATH', 'sortcodes.db'))
BUNDLED_DIRECTORY = Path(__file__).resolve().parent / 'sort_codes.csv'
MAX_BYTES = 15 * 1024 * 1024
CODE_RE = re.compile(r'(?i)(\b["\']?sort[ _-]?code["\']?\s*[:=]\s*["\']?)(\d{2}[- ]?\d{2}[- ]?\d{2})(["\']?)')
VALID_CODE = re.compile(r'^\d{6}$')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('sortcode-bot')

def normalize(value):
    s = re.sub(r'[\s-]', '', str(value).strip())
    return s if VALID_CODE.fullmatch(s) else None

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute('CREATE TABLE IF NOT EXISTS sort_codes (sort_code TEXT PRIMARY KEY, bank_name TEXT NOT NULL)')
    return con

def count_codes():
    with db() as con:
        return con.execute('SELECT COUNT(*) FROM sort_codes').fetchone()[0]

def directory_from_csv(raw):
    text = raw.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError('CSV has no header row.')
    norm_fields = {re.sub(r'[^a-z0-9]', '', f.lower()): f for f in reader.fieldnames}
    code_col = next((norm_fields[n] for n in ('sortcode', 'sortingcode') if n in norm_fields), None)
    bank_col = next((norm_fields[n] for n in ('bankname', 'bank', 'institutionname', 'institution') if n in norm_fields), None)
    if not code_col or not bank_col:
        raise ValueError('CSV needs columns sort_code and bank_name (or bank / institution_name).')
    records = {}
    skipped = 0
    for row in reader:
        code = normalize(row.get(code_col, ''))
        name = (row.get(bank_col) or '').strip()
        if code and name:
            records[code] = name[:250]
        else:
            skipped += 1
    if not records:
        raise ValueError('No usable sort-code/bank rows in file.')
    return records, skipped

# Each block begins with fullname:. A sort code must exist and be valid or the
# complete block is dropped. The bank line is updated in place, not duplicated.
START_RE = re.compile(r'(?im)^[ \t]*fullname[ \t]*:')
SORT_FIELD_RE = re.compile(r'(?im)^([ \t]*sort_code[ \t]*:[ \t]*)([^\r\n]*)')
BANK_FIELD_RE = re.compile(r'(?im)^([ \t]*bank[ \t]*:[ \t]*)([^\r\n]*)')

def annotate_text(text, mapping):
    """Return (processed text, kept lead count, matched count, removed count)."""
    starts = [m.start() for m in START_RE.finditer(text)]
    if not starts:
        raise ValueError('No leads found. Each lead must begin with fullname: on its own line.')
    newline = '\r\n' if '\r\n' in text else '\n'
    # Preserve any text preceding the first record (e.g. a file header).
    output = [text[:starts[0]]]
    kept = matched = removed = 0
    for i, start in enumerate(starts):
        block = text[start:starts[i + 1] if i + 1 < len(starts) else len(text)]
        field = SORT_FIELD_RE.search(block)
        code = normalize(field.group(2)) if field else None
        if code is None:
            removed += 1
            continue
        bank = mapping.get(code)
        if not bank:
            removed += 1
            continue
        kept += 1
        matched += 1
        label = bank
        if BANK_FIELD_RE.search(block):
            block = BANK_FIELD_RE.sub(lambda m: m.group(1) + label, block, count=1)
        else:
            # Insert bank immediately after fullname, leaving everything else untouched.
            first_line_end = re.search(r'\r?\n', block)
            if first_line_end:
                pos = first_line_end.end()
                block = block[:pos] + 'bank: ' + label + newline + block[pos:]
            else:
                block += newline + 'bank: ' + label + newline
        output.append(block)
    return ''.join(output), kept, matched, removed

def annotate_csv(text, mapping):
    r = csv.DictReader(io.StringIO(text))
    if not r.fieldnames:
        raise ValueError('CSV has no column headings.')
    columns = list(r.fieldnames)
    key = next((c for c in columns if re.sub(r'[^a-z0-9]', '', c.lower()) == 'sortcode'), None)
    if not key:
        raise ValueError('CSV needs a sort_code column.')
    bank_key = next((c for c in columns if c.strip().lower() == 'bank'), None)
    if bank_key is None:
        bank_key = 'bank'
        columns.append(bank_key)
    out = io.StringIO(newline='')
    w = csv.DictWriter(out, fieldnames=columns)
    w.writeheader()
    kept = matched = removed = 0
    for row in r:
        code = normalize(row.get(key) or '')
        if code is None:
            removed += 1
            continue
        bank = mapping.get(code)
        if not bank:
            removed += 1
            continue
        kept += 1
        matched += 1
        row[bank_key] = bank
        w.writerow(row)
    return out.getvalue(), kept, matched, removed

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '🏦 UK Sort-Code Lead Annotator\n\n'
        'Upload a .txt or .csv file. For each lead beginning with fullname:, I update its bank: field using sort_code:. Leads with a missing, invalid or unrecognised sort_code are removed.\n\n'
        'A historical sort-code database is included and loaded automatically. Admins can replace it by uploading a CSV with /setcodes.\n'
        'Use /status to check database size. Unknown codes are removed from the output.\n\n'
        'Files may contain sensitive information; use dummy or authorised data only.'
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f'📚 Loaded sort codes: {count_codes():,}')

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Usage: /lookup 12-34-56')
        return
    code = normalize(context.args[0])
    if not code:
        await update.message.reply_text('Enter a six-digit sort code, e.g. 12-34-56.')
        return
    with db() as con:
        row = con.execute('SELECT bank_name FROM sort_codes WHERE sort_code=?', (code,)).fetchone()
    await update.message.reply_text(f'{code[:2]}-{code[2:4]}-{code[4:]} → {row[0] if row else "UNKNOWN (not in directory)"}')

async def setcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or str(update.effective_user.id) != ADMIN_ID:
        await update.message.reply_text('Admin only. Set ADMIN_USER_ID in your environment first.')
        return
    doc = update.message.document or (update.message.reply_to_message.document if update.message.reply_to_message else None)
    if not doc or not (doc.file_name or '').lower().endswith('.csv'):
        await update.message.reply_text('Attach directory.csv with /setcodes as the caption, or reply /setcodes to a CSV. Columns: sort_code,bank_name.')
        return
    if doc.file_size and doc.file_size > MAX_BYTES:
        await update.message.reply_text('Directory too large (15 MB maximum).')
        return
    try:
        f = await doc.get_file()
        raw = bytes(await f.download_as_bytearray())
        if len(raw) > MAX_BYTES:
            raise ValueError('File too large.')
        records, skipped = directory_from_csv(raw)
        # A transaction avoids losing the old directory on error.
        with db() as con:
            con.execute('DELETE FROM sort_codes')
            con.executemany('INSERT INTO sort_codes(sort_code,bank_name) VALUES (?,?)', records.items())
        await update.message.reply_text(f'✅ Imported {len(records):,} sort codes. Skipped {skipped:,} invalid rows.')
    except (UnicodeError, csv.Error, ValueError) as e:
        await update.message.reply_text(f'❌ Directory problem: {e}')
    except Exception:
        logger.exception('Directory import failed')
        await update.message.reply_text('❌ Import failed. Check logs.')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        return
    name = Path(doc.file_name or 'leads.txt').name
    ext = Path(name).suffix.lower()
    if ext not in ('.txt', '.csv'):
        await update.message.reply_text('Please upload a .txt or .csv file.')
        return
    if doc.file_size and doc.file_size > MAX_BYTES:
        await update.message.reply_text('Files must be no larger than 15 MB.')
        return
    if count_codes() == 0:
        await update.message.reply_text('⚠️ No bank directory loaded. Admin: import sort_code,bank_name CSV using /setcodes first.')
        return
    try:
        f = await doc.get_file()
        raw = bytes(await f.download_as_bytearray())
        if len(raw) > MAX_BYTES:
            raise ValueError('File too large.')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Please save your file as UTF-8 text or CSV.')
        with db() as con:
            mapping = dict(con.execute('SELECT sort_code, bank_name FROM sort_codes'))
        if ext == '.csv':
            result, total, matched, removed = annotate_csv(text, mapping)
        else:
            result, total, matched, removed = annotate_text(text, mapping)
        output = io.BytesIO(result.encode('utf-8-sig' if ext == '.csv' else 'utf-8'))
        output.name = f'{Path(name).stem}_with_banks{ext}'
        output.seek(0)
        await update.message.reply_document(
            document=output,
            filename=output.name,
            caption=f'✅ Kept {total:,} verified leads; removed {removed:,} leads with missing, invalid or unknown sort codes.' 
        )
    except (UnicodeError, csv.Error, ValueError) as e:
        await update.message.reply_text(f'❌ Could not process the file: {e}')
    except Exception:
        logger.exception('Lead processing failed')
        await update.message.reply_text('❌ Processing failed. Check bot logs.')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error('Telegram update error: %s', type(context.error).__name__)

def main():
    if not TOKEN:
        raise RuntimeError('BOT_TOKEN is missing. Set it in Railway or your environment.')
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if count_codes() == 0 and BUNDLED_DIRECTORY.is_file():
        records, skipped = directory_from_csv(BUNDLED_DIRECTORY.read_bytes())
        with db() as con:
            con.executemany('INSERT INTO sort_codes(sort_code,bank_name) VALUES (?,?)', records.items())
        logger.info('Loaded %s bundled sort codes (skipped %s).', len(records), skipped)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('lookup', lookup))
    app.add_handler(CommandHandler('setcodes', setcodes))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.CaptionRegex(r'^/setcodes(?:@\w+)?(?:\s|$)'), setcodes))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document))
    app.add_error_handler(error_handler)
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
