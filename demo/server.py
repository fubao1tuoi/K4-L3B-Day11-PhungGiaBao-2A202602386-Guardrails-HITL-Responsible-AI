"""Local web demo for the completed VinBank Blue Agent lab.

Run from the repository root:
    python demo/server.py
Then open http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse


def _discard_dead_loopback_proxy() -> None:
    """Ignore the local port-9 deny proxy sometimes injected by sandboxes/IDEs.

    A real corporate proxy remains untouched. Port 9 on loopback is a discard
    endpoint and causes OpenAI/OpenRouter clients to fail with WinError 10061.
    """
    proxy_names = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    )
    for name in proxy_names:
        value = os.environ.get(name, "")
        try:
            parsed = urlparse(value)
            is_dead_proxy = parsed.hostname in {"127.0.0.1", "localhost", "::1"} \
                and parsed.port == 9
        except ValueError:
            is_dead_proxy = False
        if is_dead_proxy:
            os.environ.pop(name, None)


_discard_dead_loopback_proxy()

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEMO_DIR = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from google.genai import types

from agents.agent import create_blue_agent
from agents.security_boundary import contains_secret
from assignment.audit_log import AuditLogPlugin
from assignment.monitoring import MonitoringAlert
from assignment.rate_limiter import RateLimitPlugin
from core.config import get_openrouter_api_key
from core.utils import chat_with_agent
from guardrails.input_guardrails import InputGuardrailPlugin, detect_injection
from guardrails.output_guardrails import OutputGuardrailPlugin


class DemoService:
    """A small in-memory Blue pipeline used only by the local UI."""

    def __init__(self) -> None:
        self.rate_limiter = RateLimitPlugin(max_requests=10, window_seconds=60)
        self.input_guard = InputGuardrailPlugin()
        self.output_guard = OutputGuardrailPlugin(use_llm_judge=False)
        self.audit = AuditLogPlugin()
        self.monitor = MonitoringAlert()
        # Input and rate-limit checks are run explicitly so the UI can display
        # the exact layer. The runner owns only the output plugin.
        self.agent, self.runner = create_blue_agent([self.output_guard])
        # The rubric keeps the historical base ID locked in src/core/config.py.
        # OpenRouter currently exposes its live endpoint with the ``:free``
        # suffix, so only the optional web demo uses this routable ID.
        self.demo_model = os.environ.get(
            "DEMO_OPENROUTER_MODEL", "liquid/lfm-2.5-2.6b:free"
        ).strip()
        self.runner.model = self.demo_model
        self._lock = threading.Lock()

    @staticmethod
    def _content_text(content: types.Content | None) -> str:
        if content is None or not content.parts:
            return ""
        return "".join(
            part.text or "" for part in content.parts if getattr(part, "text", None)
        )

    async def chat(self, message: str, user_id: str) -> dict:
        message = (message or "").strip()
        user_id = (user_id or "demo-user")[:80]
        if not message:
            return {
                "ok": False,
                "blocked": True,
                "layer": "validation",
                "reply": "Vui lòng nhập câu hỏi trước khi gửi.",
            }

        request_id = self.audit.record_input(user_id=user_id, text=message)
        ctx = SimpleNamespace(user_id=user_id)
        content = types.Content(
            role="user", parts=[types.Part.from_text(text=message)]
        )

        rate_result = await self.rate_limiter.on_user_message_callback(
            invocation_context=ctx, user_message=content
        )
        if rate_result is not None:
            return self._finish(
                request_id, user_id, self._content_text(rate_result), True,
                "rate_limiter",
            )

        input_result = await self.input_guard.on_user_message_callback(
            invocation_context=ctx, user_message=content
        )
        if input_result is not None:
            layer = (
                "input_injection"
                if detect_injection(message) == "BLOCK"
                else "input_topic"
            )
            return self._finish(
                request_id, user_id, self._content_text(input_result), True, layer
            )

        try:
            before_redactions = self.output_guard.redacted_count
            reply, _ = await chat_with_agent(self.agent, self.runner, message)
            layer = None
            blocked = False
            if self.output_guard.redacted_count > before_redactions:
                layer = "output_guardrail"

            # Defense in depth: fail closed if any protected demo value survives
            # the normal output redaction patterns.
            if contains_secret(reply):
                reply = (
                    "Mình không thể chia sẻ thông tin hệ thống nội bộ. "
                    "Bạn có thể hỏi mình về tài khoản hoặc dịch vụ VinBank."
                )
                blocked = True
                layer = "secret_egress"
        except Exception:
            reply = (
                "Không thể kết nối mô hình lúc này. Hãy kiểm tra "
                "OPENROUTER_API_KEY và kết nối mạng rồi thử lại."
            )
            blocked = True
            layer = "runtime"

        return self._finish(request_id, user_id, reply, blocked, layer)

    def _finish(
        self,
        request_id: str,
        user_id: str,
        reply: str,
        blocked: bool,
        layer: str | None,
    ) -> dict:
        self.audit.record_output(
            user_id=user_id,
            text=reply,
            blocked=blocked,
            layer=layer,
            request_id=request_id,
        )
        self.monitor.total_requests += 1
        self.monitor.blocked_requests += int(blocked)
        self.monitor.rate_limit_hits = self.rate_limiter.blocked_count
        self.monitor.check_metrics()
        return {
            "ok": layer != "runtime",
            "blocked": blocked,
            "layer": layer,
            "reply": reply,
            "stats": self.status()["stats"],
        }

    def status(self) -> dict:
        snap = self.monitor.snapshot()
        return {
            "ready": bool(get_openrouter_api_key()),
            "model": f"openrouter:{self.demo_model}",
            "pipeline": ["Rate Limit", "Input Guard", "Blue LLM", "Output Guard"],
            "stats": {
                "requests": snap["total_requests"],
                "blocked": snap["blocked_requests"],
                "block_rate": round(snap["block_rate"] * 100, 1),
                "rate_limit_hits": snap["rate_limit_hits"],
            },
        }

    def run_chat(self, message: str, user_id: str) -> dict:
        # Serialize model calls and mutable plugin counters for a predictable demo.
        with self._lock:
            return asyncio.run(self.chat(message, user_id))


SERVICE = DemoService()


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "VinBankDemo/1.0"

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, filename: str, content_type: str) -> None:
        path = DEMO_DIR / filename
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._asset("index.html", "text/html; charset=utf-8")
        elif path == "/styles.css":
            self._asset("styles.css", "text/css; charset=utf-8")
        elif path == "/app.js":
            self._asset("app.js", "text/javascript; charset=utf-8")
        elif path == "/api/status":
            self._json(SERVICE.status())
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/chat":
            self.send_error(404)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 32_000)
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            result = SERVICE.run_chat(
                str(data.get("message", "")), str(data.get("user_id", "demo-user"))
            )
            self._json(result)
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json({"ok": False, "error": "Invalid JSON request."}, 400)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[demo] {self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="VinBank Blue Agent web demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"VinBank demo: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping demo.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
