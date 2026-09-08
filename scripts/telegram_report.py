#!/usr/bin/env python3
"""Send an existing report to a fixed Telegram group; no third-party dependencies."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import uuid
import urllib.error
import urllib.request


class DeliveryError(Exception):
    pass


def setting(name):
    value = os.environ.get(name, "").strip()
    # Accept a copied NAME=value line as well as just its value.
    if value.startswith(name + "="):
        value = value[len(name) + 1:].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def api_failure(method, status, payload=None):
    # Classify errors; never print server text, which may echo credentials/data.
    description = str((payload or {}).get("description", "")).lower()
    if status == 401 or status == 404:
        return DeliveryError("Telegram rejected the bot token. Update TELEGRAM_BOT_TOKEN in repository Secrets (not Variables).")
    if status == 403:
        return DeliveryError("Telegram denied access. Add the bot to the group and allow it to send messages and documents.")
    if status == 400 and "chat not found" in description:
        return DeliveryError("Telegram cannot find the group. Check TELEGRAM_CHAT_ID and that this bot is still a member.")
    if status == 400 and "thread" in description:
        return DeliveryError("Telegram cannot use this topic. Correct or remove TELEGRAM_THREAD_ID.")
    if status == 400 and any(word in description for word in ("not enough rights", "chat_write_forbidden", "not a member")):
        return DeliveryError("The bot cannot post in this group. Check membership and message/document permissions.")
    if status == 429:
        return DeliveryError("Telegram rate limit reached. Wait before trying again.")
    if method.startswith("send"):
        return DeliveryError("Telegram did not confirm delivery. Check the group before retrying.")
    return DeliveryError("Telegram could not complete the connection check. Check configuration and retry later.")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Telegram:
    def __init__(self, token):
        token = token.strip()
        if not token:
            raise DeliveryError("Missing TELEGRAM_BOT_TOKEN. Add it as a repository Actions secret.")
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
            raise DeliveryError("Invalid TELEGRAM_BOT_TOKEN format. Paste the bot token only, without surrounding instructions.")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, method, fields, document=None):
        if document is None:
            body = json.dumps(fields).encode()
            content_type = "application/json"
        else:
            boundary = uuid.uuid4().hex
            chunks = []
            for key, value in fields.items():
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="re-tech-report.md"\r\nContent-Type: text/markdown; charset=utf-8\r\n\r\n'.encode())
            chunks.extend([document, f'\r\n--{boundary}--\r\n'.encode()])
            body = b"".join(chunks)
            content_type = f"multipart/form-data; boundary={boundary}"
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/{method}", data=body,
            headers={"Content-Type": content_type}, method="POST")
        try:
            with self.opener.open(request, timeout=45) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read(65536))
                if not isinstance(payload, dict):
                    payload = {}
            except (ValueError, OSError):
                payload = {}
            raise api_failure(method, error.code, payload) from None
        except Exception:
            # Exceptions may include the credential-bearing URL; never print them.
            # Do not retry an ambiguous send: Telegram has no idempotency key.
            if method.startswith("send"):
                raise DeliveryError("Telegram request failed. Delivery may be uncertain; check the group before retrying.") from None
            raise DeliveryError("Cannot reach Telegram or read its response. No message was sent by this check.") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            payload = result if isinstance(result, dict) else {}
            raise api_failure(method, payload.get("error_code"), payload)
        return result.get("result")


def destination(api):
    chat_id = setting("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise DeliveryError("Missing TELEGRAM_CHAT_ID. Add the group ID as a repository Actions secret.")
    if not re.fullmatch(r"-[1-9]\d*", chat_id):
        raise DeliveryError("Set TELEGRAM_CHAT_ID to the confirmed numeric group ID")
    chat = api.call("getChat", {"chat_id": chat_id})
    if chat.get("type") not in ("group", "supergroup") or str(chat.get("id")) != chat_id:
        raise DeliveryError("Destination is not the configured group")
    fields = {"chat_id": chat_id}
    thread = setting("TELEGRAM_THREAD_ID")
    if thread:
        if not re.fullmatch(r"[1-9]\d*", thread):
            raise DeliveryError("Invalid TELEGRAM_THREAD_ID")
        fields["message_thread_id"] = int(thread)
    return fields


def send_report(api, path):
    send_content(api, Path(path).read_bytes())


def send_secret_report(api):
    # Preserve report text verbatim: do not strip, interpolate or execute it.
    content = os.environ.pop("TELEGRAM_REPORT_TEXT", "")
    if not content.strip():
        raise DeliveryError("Missing TELEGRAM_REPORT_TEXT. Save the complete report text as a repository Actions secret.")
    send_content(api, content.encode("utf-8"))


def send_content(api, content):
    if not content.strip() or len(content) > 5_000_000:
        raise DeliveryError("Report must be nonempty and under 5 MB")
    content.decode("utf-8")
    fields = destination(api)
    fields["caption"] = "Re-Tech · Price report / Отчет за цените"
    result = api.call("sendDocument", fields, document=content)
    if not isinstance(result, dict) or not result.get("message_id"):
        raise DeliveryError("No delivery confirmation received")
    print("Report delivery confirmed.")


def check_connection(api):
    me = api.call("getMe", {})
    if not isinstance(me, dict) or me.get("username", "").lower() != "retech23_bot":
        raise DeliveryError("The token belongs to a different bot. Use the token for @retech23_bot.")
    destination(api)
    print("Bot token and group access verified. No test message was sent.")
    print("Posting permissions and optional topic access are verified by the connection test.")


def pair(api):
    # Interactive and local only: avoid publishing group IDs in Actions logs.
    if not sys.stdin.isatty():
        raise DeliveryError("Run pairing interactively on your computer")
    me = api.call("getMe", {})
    code = uuid.uuid4().hex[:16]
    command = f"/retech_connect@{me['username']} {code}"
    print("Send this exact command in the intended group:\n" + command)
    input("Then press Enter here: ")
    matches = {}
    offset = None
    for _ in range(20):
        fields = {"timeout": 0, "limit": 100}
        if offset is not None:
            fields["offset"] = offset
        updates = api.call("getUpdates", fields)
        for update in updates:
            msg = update.get("message", {})
            chat = msg.get("chat", {})
            if msg.get("text") == command and chat.get("type") in ("group", "supergroup"):
                matches[chat["id"]] = chat
        if len(updates) < 100:
            break
        offset = updates[-1]["update_id"] + 1
    if len(matches) != 1:
        raise DeliveryError("No unique matching group found. Try again; stop any other polling process first.")
    chat = next(iter(matches.values()))
    print("Group:", chat.get("title", ""))
    if input("Is this your Re-Tech group? Type yes: ").strip().lower() != "yes":
        raise DeliveryError("Pairing cancelled")
    print("TELEGRAM_CHAT_ID=" + str(chat["id"]))
    print("Store this ID with the token in your private environment or GitHub Actions secrets.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pair")
    sub.add_parser("test")
    sub.add_parser("check")
    sub.add_parser("send-secret")
    send = sub.add_parser("send")
    send.add_argument("report", help="Local UTF-8 Markdown report; never commit private reports")
    args = parser.parse_args()
    token = setting("TELEGRAM_BOT_TOKEN")
    if not token and sys.stdin.isatty():
        token = getpass.getpass("Bot token (hidden): ")
    try:
        api = Telegram(token)
        if args.command == "pair":
            pair(api)
        elif args.command == "check":
            check_connection(api)
        elif args.command == "send-secret":
            send_secret_report(api)
        elif args.command == "test":
            result = api.call("sendMessage", {**destination(api), "text": "Re-Tech: Telegram connection test successful. Daily report delivery requires the report producer to be connected."})
            if not isinstance(result, dict) or not result.get("message_id"):
                raise DeliveryError("No delivery confirmation received")
            print("Test delivery confirmed.")
        else:
            send_report(api, args.report)
    except DeliveryError as error:
        # DeliveryError messages are fixed application text, never raw API errors.
        print("Operation failed: " + str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        print("Operation failed: invalid file or unexpected Telegram response. Before retrying a send, check the group for delivery.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
