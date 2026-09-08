# Re-Tech Telegram reports

Status: sender and connection-test workflow implemented. Credentials, group pairing,
a live delivery test, and the ChatGPT report-producer connection are still required.
There is no new daily schedule and no change to Shopify pricing or the Mac collector.

## Add the bot

Telegram → Re-Tech group → group name → Add Members → `@retech23_bot`.
Allow text and document messages. Admin privileges and disabling privacy mode are
not needed. If members cannot add bots, a group administrator must add it.

Use the bot token authorized by the owner. Store it privately; do not commit it
or enter it into a GitHub workflow input. It can be rotated later in BotFather.

## Pair locally (Python 3.10+)

From an updated checkout of this repository:

```sh
python3 scripts/telegram_report.py pair
```

The token prompt is hidden. Send the generated `/retech_connect@retech23_bot ...`
command in the group, press Enter, and confirm the displayed group name.
Copy the resulting numeric `TELEGRAM_CHAT_ID` (including its minus sign).
The pairing helper does not save credentials or post messages. It uses getUpdates,
so stop other bot pollers first; a bot with an existing webhook cannot use this helper
until its owner intentionally removes that webhook. Use this only with the new bot.
For a forum group, optionally configure `TELEGRAM_THREAD_ID` for the desired topic.

## GitHub connection test

Open https://github.com/TanevAnton/re-tracker/settings/secrets/actions
and add repository secrets:

- `TELEGRAM_BOT_TOKEN`: authorized bot token.
- `TELEGRAM_CHAT_ID`: confirmed group ID.
- `TELEGRAM_THREAD_ID`: optional topic ID.

Then Actions → Telegram connection test → Run workflow, using main.
This sends a harmless connection-test message. The workflow cannot change prices.
Do not enter private report contents into public repository files, issues or workflow
inputs. This repository is public. The bot credentials belong only in secrets.

## Send the current report from your Mac

Download `Re-Tech-Price-Changes-2026-09-08.md` from the ChatGPT conversation.
Set `TELEGRAM_CHAT_ID` in the local environment to the confirmed group ID, then run:

```sh
python3 scripts/telegram_report.py send /absolute/path/to/Re-Tech-Price-Changes-2026-09-08.md
```

The token is prompted for privately if absent from the environment. You can also
inject `TELEGRAM_BOT_TOKEN` from your local secret manager. The Markdown report is
sent as a document, preserving all tables, Bulgarian text and long reports.
Success is printed only after Telegram returns a message ID. Errors never log the
credential-bearing URL or Telegram response body. Ambiguous sends are not retried
automatically; inspect the group before retrying to avoid duplicates.

## Connect a daily producer

A trusted local report-generating process can invoke the same `send` command after
it writes each completed report (including no-change, partial and blocked results).
Use a unique dated report path and persist the successful delivery state in that
producer so the same run is not sent twice. Supply the token via a private process
environment, never command-line arguments. A send failure must not rerun pricing.

The existing ChatGPT daily Shopify task is separate from the Mac market collector.
The sender does not have access to that conversation or its completed reports.
GitHub does not automatically receive those reports. Activating automatic forwarding
requires a supported authenticated delivery connection from the task, or moving
report production to the local service and explicitly integrating this sender.
Until that connection exists, daily reports continue in ChatGPT only; do not label
Telegram daily delivery active just because a connection test succeeds.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_telegram_report.py' -v
```

Tests cover large Unicode reports, destination validation, empty reports and safe
network-error handling without automatic duplicate sends. Actual Telegram delivery
requires the configured secrets and an explicit test run.

References:
- https://core.telegram.org/bots/api#senddocument
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
