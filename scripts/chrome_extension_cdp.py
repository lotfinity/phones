#!/usr/bin/env python3
"""
Small Chrome DevTools Protocol helper for working with installed extensions.

It expects Chrome/Chromium to already be running with remote debugging enabled:

    google-chrome \
      --remote-debugging-port=9222 \
      --remote-allow-origins=* \
      --user-data-dir=/tmp/chrome-cdp-profile

Examples:

    python scripts/chrome_extension_cdp.py list
    python scripts/chrome_extension_cdp.py list --extensions-only
    python scripts/chrome_extension_cdp.py open-url "https://www.google.com/search?tbm=isch&q=hydraulic+breaker"
    python scripts/chrome_extension_cdp.py open-extension agionbommeaifngbhincahgmoflcikhm popup.html
    python scripts/chrome_extension_cdp.py eval --target-url chrome-extension://EXT_ID/popup.html \
      "document.body.innerText"

This script does not install extensions and does not bypass Chrome's security
model. Extension pages must be accessible in the running Chrome profile.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

try:
    import websocket
except ImportError as exc:  # pragma: no cover - exercised by runtime env only
    raise SystemExit(
        "Missing dependency: websocket-client. Install it in the active Python "
        "environment, for example `pip install websocket-client`."
    ) from exc


@dataclass(frozen=True)
class Target:
    id: str
    type: str
    title: str
    url: str
    websocket_url: str | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Target":
        return cls(
            id=payload.get("id", ""),
            type=payload.get("type", ""),
            title=payload.get("title", ""),
            url=payload.get("url", ""),
            websocket_url=payload.get("webSocketDebuggerUrl"),
        )


class ChromeCdp:
    def __init__(self, host: str, port: int, timeout: float = 10) -> None:
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout

    def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
    ) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise SystemExit(
                f"Could not reach Chrome CDP at {self.base_url}. Start Chrome "
                "with --remote-debugging-port and --remote-allow-origins=*."
            ) from exc
        return json.loads(raw) if raw else None

    def version(self) -> dict[str, Any]:
        return self.request_json("/json/version")

    def targets(self) -> list[Target]:
        return [Target.from_payload(item) for item in self.request_json("/json")]

    def new_tab(self, url: str) -> Target:
        encoded = urllib.parse.quote(url, safe=":/?&=%#,+")
        payload = self.request_json(f"/json/new?{encoded}", method="PUT")
        return Target.from_payload(payload)

    def activate(self, target_id: str) -> None:
        self.request_json(f"/json/activate/{target_id}")

    def find_target(
        self,
        *,
        target_id: str | None = None,
        target_url: str | None = None,
        extension_id: str | None = None,
        prefer_extension_worker: bool = False,
    ) -> Target:
        targets = self.targets()
        if target_id:
            for target in targets:
                if target.id == target_id:
                    return target
            raise SystemExit(f"No CDP target found with id: {target_id}")

        if target_url:
            matches = [target for target in targets if target_url in target.url]
            if matches:
                return matches[0]
            raise SystemExit(f"No CDP target URL contains: {target_url}")

        if extension_id:
            prefix = f"chrome-extension://{extension_id}/"
            matches = [target for target in targets if target.url.startswith(prefix)]
            if prefer_extension_worker:
                for target in matches:
                    if target.type in {"service_worker", "background_page"}:
                        return target
            if matches:
                return matches[0]
            raise SystemExit(
                f"No target found for extension {extension_id}. Open one of its "
                "extension pages first, or use open-extension."
            )

        pages = [target for target in targets if target.type == "page"]
        if pages:
            return pages[0]
        raise SystemExit("No page targets available.")


class CdpSocket:
    def __init__(self, target: Target, timeout: float = 10) -> None:
        if not target.websocket_url:
            raise SystemExit(f"Target {target.id} does not expose a websocket URL.")
        try:
            self.socket = websocket.create_connection(target.websocket_url, timeout=timeout, suppress_origin=True)
        except websocket.WebSocketBadStatusException as exc:
            raise SystemExit(
                "Chrome rejected the websocket connection. Restart Chrome with "
                "`--remote-allow-origins=*`."
            ) from exc
        self.next_id = 0

    def close(self) -> None:
        self.socket.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        self.socket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self.socket.recv())
            if response.get("id") == message_id:
                return response

    def eval(self, expression: str, await_promise: bool = False) -> Any:
        response = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        if "exceptionDetails" in response:
            raise SystemExit(json.dumps(response["exceptionDetails"], indent=2))
        result = response.get("result", {}).get("result", {})
        if "value" in result:
            return result["value"]
        return result


def print_targets(targets: list[Target], extensions_only: bool) -> None:
    for target in targets:
        is_extension = target.url.startswith("chrome-extension://")
        if extensions_only and not is_extension:
            continue
        print(json.dumps({
            "id": target.id,
            "type": target.type,
            "title": target.title,
            "url": target.url,
            "extension_id": extension_id_from_url(target.url),
            "debuggable": bool(target.websocket_url),
        }, ensure_ascii=False))


def extension_id_from_url(url: str) -> str | None:
    prefix = "chrome-extension://"
    if not url.startswith(prefix):
        return None
    rest = url[len(prefix):]
    return rest.split("/", 1)[0] or None


def cmd_list(args: argparse.Namespace) -> None:
    cdp = ChromeCdp(args.host, args.port, args.timeout)
    cdp.version()
    print_targets(cdp.targets(), args.extensions_only)


def cmd_open_url(args: argparse.Namespace) -> None:
    cdp = ChromeCdp(args.host, args.port, args.timeout)
    target = cdp.new_tab(args.url)
    print(json.dumps({"opened": target.url, "target_id": target.id}, ensure_ascii=False))


def cmd_open_extension(args: argparse.Namespace) -> None:
    path = args.path.lstrip("/")
    url = f"chrome-extension://{args.extension_id}/{path}"
    cdp = ChromeCdp(args.host, args.port, args.timeout)
    target = cdp.new_tab(url)
    print(json.dumps({"opened": target.url, "target_id": target.id}, ensure_ascii=False))


def cmd_eval(args: argparse.Namespace) -> None:
    cdp = ChromeCdp(args.host, args.port, args.timeout)
    target = cdp.find_target(
        target_id=args.target_id,
        target_url=args.target_url,
        extension_id=args.extension_id,
        prefer_extension_worker=args.service_worker,
    )
    sock = CdpSocket(target, args.timeout)
    try:
        sock.call("Runtime.enable")
        value = sock.eval(args.expression, await_promise=args.await_promise)
    finally:
        sock.close()
    print(json.dumps({"target_id": target.id, "target_url": target.url, "value": value}, ensure_ascii=False))


def cmd_google_images(args: argparse.Namespace) -> None:
    query = urllib.parse.quote_plus(args.query)
    url = f"https://www.google.com/search?tbm=isch&q={query}"
    cdp = ChromeCdp(args.host, args.port, args.timeout)
    target = cdp.new_tab(url)
    time.sleep(args.wait)
    print(json.dumps({"opened": target.url, "target_id": target.id, "query": args.query}, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use Chrome CDP to inspect and automate installed Chrome extensions."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Chrome CDP host.")
    parser.add_argument("--port", type=int, default=9222, help="Chrome CDP port.")
    parser.add_argument("--timeout", type=float, default=10, help="Network timeout in seconds.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List CDP targets, including extension targets.")
    list_parser.add_argument("--extensions-only", action="store_true")
    list_parser.set_defaults(func=cmd_list)

    open_url = subparsers.add_parser("open-url", help="Open a normal browser tab.")
    open_url.add_argument("url")
    open_url.set_defaults(func=cmd_open_url)

    open_extension = subparsers.add_parser("open-extension", help="Open a chrome-extension:// page.")
    open_extension.add_argument("extension_id")
    open_extension.add_argument("path", help="Extension page path, such as popup.html or options.html.")
    open_extension.set_defaults(func=cmd_open_extension)

    eval_parser = subparsers.add_parser("eval", help="Evaluate JavaScript in a page or extension target.")
    target_group = eval_parser.add_mutually_exclusive_group()
    target_group.add_argument("--target-id")
    target_group.add_argument("--target-url", help="Substring to match in a target URL.")
    target_group.add_argument("--extension-id")
    eval_parser.add_argument("--service-worker", action="store_true", help="Prefer extension worker target.")
    eval_parser.add_argument("--await-promise", action="store_true")
    eval_parser.add_argument("expression")
    eval_parser.set_defaults(func=cmd_eval)

    google_images = subparsers.add_parser("google-images", help="Open Google Images for a query.")
    google_images.add_argument("query")
    google_images.add_argument("--wait", type=float, default=1.5)
    google_images.set_defaults(func=cmd_google_images)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
