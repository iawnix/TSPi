"""Exercise installed email CLI through Jobs against an isolated TLS SMTP sink."""
import json
import os
from pathlib import Path
import socketserver
import ssl
import subprocess
import sys
import threading
import time

from tspi_runtime.execution import dispatch
from tests.unit.test_job_recovery import workspace


def test_email_prepare_send_receipt_and_retry_through_jobs(tmp_path, monkeypatch):
    workspace(tmp_path)
    cert = tmp_path / "cert.pem"; key = tmp_path / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True, capture_output=True)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert, key)
    messages = []

    class Handler(socketserver.StreamRequestHandler):
        def setup(self):
            self.request = tls.wrap_socket(self.request, server_side=True)
            self.request.settimeout(5)
            super().setup()

        def handle(self):
            self.wfile.write(b"220 localhost fixture\r\n")
            while line := self.rfile.readline():
                command = line.split(b" ", 1)[0].strip().upper()
                if command in {b"EHLO", b"HELO"}:
                    self.wfile.write(b"250-localhost\r\n250 AUTH PLAIN\r\n")
                elif command == b"AUTH":
                    self.wfile.write(b"235 authenticated\r\n")
                elif command == b"DATA":
                    self.wfile.write(b"354 data\r\n")
                    data = []
                    while (line := self.rfile.readline()) not in {b".\r\n", b""}:
                        data.append(line)
                    messages.append(b"".join(data))
                    self.wfile.write(b"250 accepted by isolated fixture\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 bye\r\n"); return
                else:
                    self.wfile.write(b"250 ok\r\n")

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    try:
        config = tmp_path / "notifications.toml"
        config.write_text(f'''[notifications.email]
enabled = true
provider = "smtp"
preset = "custom"
host = "localhost"
port = {server.server_address[1]}
security = "ssl"
username = "sender@example.test"
recipient = "reader@example.test"
password_env = "TSPI_FIXTURE_PASSWORD"
'''); config.chmod(0o600)
        monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
        monkeypatch.setenv("SSL_CERT_FILE", str(cert))
        monkeypatch.setenv("TSPI_FIXTURE_PASSWORD", "fixture-only")
        script = Path(__file__).resolve().parents[2] / "extensions/email/scripts/email_cli.py"
        report = tmp_path / "reports/result.md"; report.parent.mkdir(exist_ok=True)
        report.write_text("Isolated scientific fixture, no real recipient.")
        draft = tmp_path / "draft.json"
        draft.write_text(json.dumps({"notification_id": "fixture-final-v1", "event": "study_completed",
                                    "subject": "Fixture result", "summary": "Fixture complete", "report_refs": ["reports/result.md"]}))

        def job(name, operation, *extra):
            receipt = dispatch("start", {"root": str(tmp_path), "nodeId": "node_1", "requestId": name,
                "command": [sys.executable, str(script), operation, "--root", str(tmp_path), "--output", "output.json", *extra],
                "outputs": [{"path": "output.json", "required": True}]})
            try:
                for _ in range(200):
                    status = dispatch("status", {"root": str(tmp_path), "jobId": receipt["job_id"]})
                    if status["state"] in {"succeeded", "failed", "timed_out"}: break
                    time.sleep(.02)
                assert status["state"] == "succeeded", (status, (Path(receipt["cwd"])/"output.json").read_text())
                dispatch("collect", {"root": str(tmp_path), "jobId": receipt["job_id"]})
                path = Path(receipt["cwd"])/"output.json"
                return path, json.loads(path.read_text())
            finally:
                dispatch("cancel", {"root": str(tmp_path), "jobId": receipt["job_id"]})

        _, check = job("email_check", "check")
        assert check["recipient"] == "reader@example.test"
        prepared, _ = job("email_prepare", "prepare", "--request-file", str(draft))
        _, sent = job("email_send", "send", "--request-file", str(prepared))
        assert sent["state"] == "sent"
        _, retry = job("email_retry", "send", "--request-file", str(prepared))
        assert retry["state"] == "already_sent"
        assert len(messages) == 1
        assert b"Fixture result" in messages[0]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
