# Telegram lead file cleaner

Upload a `.txt` or `.rtf` assignment file and receive `cleaned_leads.txt`.
The bot splits at each standalone **Personal Information** heading, recognises
common field-label variations, and writes exactly this order for every record:

```text
fullname:
date_of_birth:
bank:
address:
postcode:
phone:
email:
sort_code:
account_number:
```

It extracts **supplied bank names, sort codes and account numbers** along with the
other selected fields. Account numbers and phone numbers remain text, preserving
leading zeros. Spaces and hyphens in purely numeric account numbers are removed
so equivalent formatting does not cause a false conflict. It does not copy cardholder names, card numbers, CVVs, expiry dates, passwords,
security answers, IP addresses or browser metadata.

## What it recognises

- `Full Name`, `Customer Name`, or `First Name` plus `Last Name`.
- `Date of Birth`, `Date of Birth (dd/mm/yyyy)`, `DOB`, `D.O.B.`, or `Birth Date`.
  Birth dates are copied as supplied, without guessing date order or inferring them
  from an age. Missing dates show `Not provided`.
- `Bank`, `Bank Name`, or `Card Bank`.
- `Address`, `Full Address`, or `Postal Address`, plus an explicit County.
- `Postcode`, `Post Code`, or `Postal Code`. A UK postcode already present in an
  address is copied into the postcode field when no separate label exists.
- `Phone`, `Mobile/Telephone Number`, `Contact Number`, and other common variants.
- `Email`, `Email Address`, or `E-mail`.
- `Sort Code`, `Sortcode`, or `Bank Sort Code`.
- `Account`, `Account Number`, `Account No`, or `Bank Account Number`.

The parser accepts case, spacing and punctuation variations in labels. It is
deterministic and does not send documents to an AI service. It does not identify
unlabelled names by guessing, verify account ownership,
or look up missing bank names online. Missing fields show `Not provided`.
Any record containing conflicting values is **skipped entirely**. It does not
appear in the cleaned file or the `/lead` queue. The other records still export.
A separate `cleaning_review.txt` attachment lists the original record number and
the field that caused the skip, without including that record's data or choosing
between conflicting values. Repeated identical values are accepted.
A nonempty sort code must contain six digits; a valid one is formatted NN-NN-NN,
and a record with an invalid one is also skipped. Low-level `parse_text` and `clean_bytes`
remain strict for callers that explicitly want rejection; the bot and command-line
tool use `clean_bytes_with_report` to finish the file and omit ambiguous records.

Only a standalone Personal Information heading starts a record. The phrase in
an address or field value does not split it. Each input must contain at least
one such heading. Empty sections with no recognised fields are skipped. The file
limit is 5 MiB and 10,000 headings; export is limited to 15 MiB.

## Run locally

Requires Python 3.12 or later.

```sh
python -m pip install -r requirements.txt
```

1. Create a Telegram bot using **@BotFather** and copy the token.
2. Copy `.env.example` to `.env` and put the token in `BOT_TOKEN`.
3. Leave `OWNER_TELEGRAM_ID=0` initially, then run `python bot.py`.
4. Send `/myid` in a private chat with your bot. It returns your numeric user ID.
   In this setup mode, no uploads are processed.
5. Put that ID in `.env`, stop the bot and run `python bot.py` again.
6. Send `/start`, then upload a `.txt` or `.rtf` file. Try the synthetic examples
   in `examples/` first.

Existing hosting environment variables take priority over `.env` values.
Keep the bot token private. `.env` is excluded from Git by `.gitignore`.

## Telegram commands

- Upload a file: returns the full cleaned text file and replaces the prior queue.
- `/lead` or **Next lead**: shows one cleaned record at a time.
- `/export` or **Export file**: downloads the full current cleaned file again.
- `/review` or **Review issues**: downloads the skipped-record report for the current file.
- `/reset`: returns to the first record.
- `/clear` or **Clear file**: drops the current records from bot memory.
- `/help`: shows instructions.
- `/myid`: shows the requesting user's own Telegram ID.

Only your configured numeric user ID may process files or access records. Group
messages are ignored. `/myid` is available to any private-chat user and reveals
only their own ID. Documents and extracted fields are held in memory and are
lost on restart. `/clear` does not delete messages or files from Telegram. Telegram
necessarily handles uploads and returned messages; the bot does not contact
banking services or other third parties.

The only local database contains the last processed update number, not file
contents. An unreadable, oversized or otherwise structurally invalid file keeps
the previous queue. Field conflicts skip the affected records, not the file. A successful clean
replaces both the queue and its review report; `/clear` removes both from memory.
If the cleaned file is delivered but the review attachment fails, the new data
is retained and `/review` retries the report. Extremely long records
are returned as a text attachment instead of being truncated. There is no
Picked/No Answer/Ready for WA workflow in this file-cleaning version.

If every recognised record is skipped, the bot returns only the skipped-record
report and stores an empty queue. It does not send a blank cleaned attachment or
keep showing records from an older upload. `/review` remains available.

## GitHub / Railway

Upload the extracted project files to GitHub, including `.env.example`,
`.gitignore`, `requirements.txt`, `Dockerfile`, `railway.json`, `bot.py` and
`cleaner.py`. Do not upload a real `.env` or private source documents.

Connect the repository to Railway and deploy. The included Dockerfile installs
the RTF reader and starts `python bot.py`. Set `BOT_TOKEN` and
`OWNER_TELEGRAM_ID` in Railway's environment variables. You can initially use 0
for the ID bootstrap steps above. Keep one running replica; this is a long-polling
worker and needs no public port or domain. A prior webhook is removed at startup.

Optionally mount a volume at `/data` and set `DATA_DIR=/data` to preserve only
the update offset between deployments. Files and the queue always remain in RAM.
If the offset database is lost, Telegram may redeliver unconfirmed recent updates.
Network interruptions or a crash between sending and acknowledging an update can
produce duplicate output. Hosting setup/costs depend on your provider.

## Use without Telegram

```sh
python cleaner.py examples/sample_leads.txt cleaned_leads.txt
python cleaner.py examples/sample_leads.rtf cleaned_leads.txt
```

The local command needs no bot token or network connection. Use a new output path;
it refuses to overwrite the input file with either output. It also writes a
sidecar report such as `cleaned_leads_review.txt`, including a no-issues result
when nothing is flagged so an earlier report cannot be mistaken for a current one.
Input and output contents are not logged.

## Tests and references

```sh
python -m unittest discover -s tests -v
```

Tests use synthetic fixtures only. Live Telegram verification requires your own
bot token; it is not performed as part of packaging.

- Telegram API: https://core.telegram.org/bots/api
- RTF reader: https://pypi.org/project/striprtf/ (pinned in requirements.txt).
