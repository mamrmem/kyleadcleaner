# Phone Number Extractor Bot

Upload a `.txt` or `.csv` file and the bot extracts UK mobile numbers.

Supported examples:

- `07784726262`
- `07742 472744`
- `+447727362666`
- `447227473722`
- `7737372643`

Output is:
- deduplicated
- normalised to `+44...`
- one number per line
- returned as `extracted_numbers.txt`

## Railway variables

Required:

`TELEGRAM_BOT_TOKEN=...`

Optional but recommended if only you should use the bot:

`OWNER_TELEGRAM_ID=your numeric Telegram ID`

No database or persistent volume is required.


## Output naming

All extracted numbers are returned in `+44...` format.

If the uploaded file is:

`school.txt`

the bot replies with:

`166 valid UK numbers`

and sends:

`school extracted numbers.txt`
