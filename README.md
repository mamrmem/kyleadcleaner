# UK Sort Code Telegram Bot

A Python Telegram bot that reads uploaded `.txt` or `.csv` dummy leads, matches their `sort_code` with the **bundled historical** UK and Ireland sort-code directory, updates `bank:`, removes records with absent/invalid/unmatched sort codes, and sends a new file back.

**The `sort_codes.csv` directory is from an older public spreadsheet (2017) and is not guaranteed current or comprehensive.** This is for an assignment/demo, not for validating payments or bank accounts. A matched sort code does not confirm an account belongs to someone or is valid.

## Deploy using GitHub + Railway

1. Extract this ZIP and upload the **contents** of `uk_sortcode_bot/` into your GitHub repository (or push with Git).
2. Create your bot using Telegram `@BotFather`; copy the token. Never commit your token to GitHub.
3. On Railway create a service from the GitHub repository.
4. Under Railway Variables add `BOT_TOKEN` with the BotFather token. Optionally set `ADMIN_USER_ID` to your numeric Telegram user ID if you want to upload a replacement directory using `/setcodes`.
5. Use the **start command** `python bot.py`. Railway installs requirements from `requirements.txt`.
6. Open the Telegram bot, send `/start`, then upload a `.txt` or `.csv` dummy leads file. The bot replies with an updated file.

The included `sort_codes.csv` is **auto-imported on first launch**. No manual database upload is required. If you use a persistent Railway volume set `DB_PATH=/data/sortcodes.db` (with volume mounted at `/data`). An existing database is not overwritten during redeploys; use `/setcodes` to replace it.

## Input TXT example

```text
fullname: Demo Person
bank: Not provided
sort_code: 20-00-00
account_number: 00000000

fullname: Second Person
bank: Not provided
sort_code: Not provided
account_number: 11111111
```

Each `fullname:` starts a new lead. The bot keeps the full block only when `sort_code:` has six digits and has a match in the bundled directory; it replaces the `bank:` value (or inserts that field if absent). All other fields remain unchanged. The second example block would be removed. CSV input requires a `sort_code` column and gets a `bank` column updated/added.

## Commands

- `/start` — instructions
- `/status` — number of loaded sort codes
- `/lookup 20-00-00` — check one code
- `/setcodes` — admin-only replace directory from a `.csv` attachment with columns `sort_code,bank_name` (send as caption or reply to the file)

## Local run

Python 3.11+:

```bash
pip install -r requirements.txt
```

Set environment variable `BOT_TOKEN` then run `python bot.py`. Optionally set `ADMIN_USER_ID` and `DB_PATH`.

## Privacy

Use synthetic or data you are authorised to process. The bot processes uploads in memory and does not save lead files, but Telegram and the hosting provider handle their transmission. By default anyone who finds the bot can upload files; for a deployed production bot add user authentication or an allowlist.
