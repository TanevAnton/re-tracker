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
import urllib.request


class DeliveryError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Telegram:
    def __init__(self, token):
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
            raise DeliveryError("Missing or invalid TELEGRAM_BOT_TOKEN")
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
        except Exception:
            # Exceptions may include the credential-bearing URL; never print them.
            # Do not retry an ambiguous send: Telegram has no idempotency key.
            raise DeliveryError("Telegram request failed. Delivery may be uncertain; check the group before retrying.") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise DeliveryError("Telegram rejected the request. Check bot permissions and destination.")
        return result.get("result")


def destination(api):
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not re.fullmatch(r"-[1-9]\d*", chat_id):
        raise DeliveryError("Set TELEGRAM_CHAT_ID to the confirmed numeric group ID")
    chat = api.call("getChat", {"chat_id": chat_id})
    if chat.get("type") not in ("group", "supergroup") or str(chat.get("id")) != chat_id:
        raise DeliveryError("Destination is not the configured group")
    fields = {"chat_id": chat_id}
    thread = os.environ.get("TELEGRAM_THREAD_ID", "")
    if thread:
        if not re.fullmatch(r"[1-9]\d*", thread):
            raise DeliveryError("Invalid TELEGRAM_THREAD_ID")
        fields["message_thread_id"] = int(thread)
    return fields


def send_report(api, path):
    content = Path(path).read_bytes()
    if not content.strip() or len(content) > 5_000_000:
        raise DeliveryError("Report must be nonempty and under 5 MB")
    content.decode("utf-8")
    fields = destination(api)
    fields["caption"] = "Re-Tech · Price report / Отчет за цените"
    result = api.call("sendDocument", fields, document=content)
    if not isinstance(result, dict) or not result.get("message_id"):
        raise DeliveryError("No delivery confirmation received")
    print("Report delivery confirmed.")


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
    send = sub.add_parser("send")
    send.add_argument("report", help="Local UTF-8 Markdown report; never commit private reports")
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token and sys.stdin.isatty():
        token = getpass.getpass("Bot token (hidden): ")
    try:
        api = Telegram(token)
        if args.command == "pair":
            pair(api)
        elif args.command == "test":
            result = api.call("sendMessage", {**destination(api), "text": "Re-Tech: Telegram connection test successful. Daily report delivery requires the report producer to be connected."})
            if not isinstance(result, dict) or not result.get("message_id"):
                raise DeliveryError("No delivery confirmation received")
            print("Test delivery confirmed.")
        else:
            send_report(api, args.report)
    except (DeliveryError, OSError, UnicodeError, ValueError, KeyError, TypeError):
        print("Operation failed. Check configuration, file, permissions and connectivity. Before retrying a send, check the group for delivery.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
