# Telegram Lead Shuffler

Upload a `.txt` file to your bot in Telegram. It sends back a new `.txt` file with the lines in a random order. Designed for files of around 15,000 leads, with one complete lead per line.

## Get started

1. Open [@BotFather](https://t.me/BotFather) in Telegram. Send `/newbot`, choose a name and username, and copy the token it gives you. [Telegram's instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token).
2. Unzip this folder. You need Python 3.10 or newer. If needed, install it from [python.org](https://www.python.org/downloads/).
3. On **Mac**, double-click **Start on Mac.command**. On **Windows**, double-click **Start on Windows.bat**.
4. On the first run, paste your BotFather token into the terminal prompt. The token is hidden as you type. It is saved in a local `.env` file.
5. Once the terminal says `Running @your_bot`, open that bot in Telegram, press **Start**, and upload your `.txt` file as a document.

Keep the terminal open and your computer awake while using the bot. Press **Ctrl+C** to stop it. Running on a server instead keeps it available while your computer is off; it uses outgoing HTTPS and does not need a public website or incoming port.

### Terminal alternative (Mac, Linux, or a server)

Open a terminal in the extracted folder, then run:

```sh
python3 bot.py --setup
python3 bot.py
```

On Windows, use `py -3` instead of `python3`.

No package installation, database, or paid API is required. Telegram connectivity is required.

If you already created `.env`, edit its `TELEGRAM_BOT_TOKEN` value instead of rerunning setup. You can also supply the settings through environment variables; those take precedence over `.env`.

## What happens to your leads

- Every whole source line moves to another position. The characters within each line are kept intact.
- Duplicate leads are kept. Identical copies may look unchanged even though their source records moved.
- Blank lines are kept and shuffled too. The reported count includes them.
- Every line is treated as data: there is no special header row.
- Normal Windows, Mac, and Unix line endings are preserved, including whether the file ends with a newline. If a file mixes line-ending styles, they are made consistent using its first newline style.
- UTF-8 (with or without a BOM), legacy single-byte text, and UTF-16 with a BOM are supported. Save other text encodings as UTF-8 first.
- At least two nonblank leads are required. Files are limited to **19 MB** and **300,000 lines**.
- Each upload generates a fresh random shuffle. The bot does not keep a history to prevent an earlier permutation from recurring. With two leads, swapping them is the only possible result.

The bot handles files in memory and does not save them or log their contents. Uploads and results still exist in your Telegram chat until you delete them there. The `.env` file stores your bot token, so keep it private.

## Optional: only let your own account use it

By default, anyone who knows the bot's username can use it in a direct message. Group uploads are ignored.

1. Send `/id` to your bot to get your numeric Telegram user ID.
2. Stop the bot and edit `.env`:

   ```dotenv
   TELEGRAM_BOT_TOKEN=your_token_here
   ALLOWED_USER_IDS=123456789
   ```

3. Restart the bot. Use comma-separated IDs to allow more than one account.

Commands: `/start` or `/help` for instructions, `/id` for your user ID, and `/privacy` for file handling information.

## Troubleshooting

- **Python is missing:** install Python 3.10 or newer, then reopen the launcher.
- **Token rejected:** check `.env` against the token from BotFather.
- **Another copy is running:** stop any other process using the same bot token. Only one polling instance can run at a time.
- **Webhook already active:** use a newly created bot, or remove the old bot's webhook before using this polling bot.
- **No reply:** check that the terminal is still running, your computer is awake, you are messaging the correct bot directly, and your ID is allowed if you set an allowed list.
- **Encoding error:** open the text file in an editor and save it as UTF-8.

## Verify locally

```sh
python3 -m unittest discover -s tests -v
```

Tests use generated example leads and mocked Telegram calls. They do not contact Telegram. A real upload-and-return check needs your own BotFather token.

Implementation uses Python's standard library and the official [Telegram Bot API](https://core.telegram.org/bots/api). Telegram's hosted API allows bots to download files up to 20 MB; this bot caps uploads at 19 MB.
