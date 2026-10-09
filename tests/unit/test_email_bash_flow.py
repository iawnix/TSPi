"""Exercise scientific Job collection then report/email through bash against an isolated TLS SMTP sink."""
import json
import os
from pathlib import Path
import socketserver
import ssl
import subprocess
import sys
import threading
import time

from research_agent.application.execution import dispatch
from tests.unit.test_job_recovery import workspace
from research_agent.research.nodes import create, update
from research_agent.application.evidence import dispatch as artifact


def test_computation_then_report_and_email_through_bash(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / 'backend/src'
    monkeypatch.setenv('PYTHONPATH', str(source))
    workspace(tmp_path)
    delivery_node = create(tmp_path, {"goal": "Deliver the authorized progress report"})["node"]["id"]
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
password_env = "RESEARCH_AGENT_FIXTURE_PASSWORD"
'''); config.chmod(0o600)
        monkeypatch.setenv("RESEARCH_AGENT_NOTIFICATION_CONFIG", str(config))
        monkeypatch.setenv("SSL_CERT_FILE", str(cert))
        monkeypatch.setenv("RESEARCH_AGENT_FIXTURE_PASSWORD", "fixture-only")
        script = Path(__file__).resolve().parents[2] / "skills/email/scripts/email_cli.py"
        calculation = dispatch("start", {"root": str(tmp_path), "request_id": "calculation",
            "command": [sys.executable, "-c", "import json;from pathlib import Path;Path('result.json').write_text(json.dumps({'method':'fixture','validated':True,'steps':[{'task':'sp','energy_hartree':-1}]}))"],
            "outputs": [{"path": "result.json", "required": True}]})
        try:
            for _ in range(200):
                status = dispatch("status", {"root": str(tmp_path), "job_id": calculation["job_id"]})
                if status["state"] in {"succeeded", "failed", "timed_out"}: break
                time.sleep(.02)
            assert status["state"] == "succeeded"
            collected = dispatch("collect", {"root": str(tmp_path), "job_id": calculation["job_id"]})
            assert collected["status"]["state"] in {"succeeded", "collected"}
        finally:
            dispatch("cancel", {"root": str(tmp_path), "job_id": calculation["job_id"]})
        builder = Path(__file__).resolve().parents[2] / "domains/chemical/skills/report/scripts/build.py"
        output = tmp_path / "reports/comparison"
        subprocess.run(["bash", "-c", 'exec "$@"', "report", sys.executable, str(builder),
                        "--result", f"local={calculation['cwd']}/result.json", "--output-dir", str(output)], check=True, timeout=30)
        report = output / "report.md"
        draft = tmp_path / "draft.json"
        draft.write_text(json.dumps({"notification_id": "fixture-progress-v1", "event": "progress",
                                    "subject": "Fixture result", "summary": "Fixture complete", "report_refs": ["reports/comparison/report.md"]}))

        def cli(name, operation, *extra):
            path = tmp_path / "reports/email" / (name + ".json")
            run = subprocess.run(["bash", "-c", 'exec "$@"', "email", sys.executable, str(script),
                                  operation, "--root", str(tmp_path), "--output", str(path), *extra],
                                 capture_output=True, text=True, timeout=30)
            assert run.returncode == 0, (run.stderr, run.stdout)
            return path, json.loads(path.read_text())

        _, check = cli("email_check", "check")
        assert check["recipient"] == "reader@example.test"
        prepared, _ = cli("email_prepare", "prepare", "--request-file", str(draft))
        update(tmp_path, {'node_id': delivery_node, 'note': 'Some science is still pending; this authorized fixture reports progress.'})
        _, sent = cli("email_send", "send", "--request-file", str(prepared))
        assert sent["state"] == "sent"
        receipt = json.loads((tmp_path / sent['receipt_ref']).read_text())
        assert receipt['state'] == 'sent'
        _, retry = cli("email_retry", "send", "--request-file", str(prepared))
        assert retry["state"] == "already_sent"
        _, status = cli("email_status", "status", "--receipt-ref", "reports/email/email_send.json")
        assert status["state"] == "sent"
        # Recover delivery registration independently of the already-sent effect.
        evidence = artifact('register', {'root': str(tmp_path), 'path': sent['receipt_ref']})
        update(tmp_path, {'node_id': delivery_node, 'note': 'Delivery verified in receipt material ' + evidence['artifact_id']})
        _, replay = cli('email_after_terminal', 'send', '--request-file', str(prepared))
        assert replay['state'] == 'already_sent'
        assert len(list((tmp_path/'operations/executions').glob('*.json'))) == 1  # Delivery does not dispatch another calculation.
        assert len(messages) == 1
        assert b"Fixture result" in messages[0]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
