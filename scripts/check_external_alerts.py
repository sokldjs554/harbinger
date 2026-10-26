"""Actual local Prometheus/Alertmanager + authenticated SSL SMTP sink.

No external mail is sent. API traffic is restricted to loopback. The same
on-host verifier reads native process logs through an adapter instead of Docker
logs; alert state and SMTP transport responses are never mocked.
"""

import argparse
import base64
import email
import email.header
import importlib.util
import json
import shutil
import socketserver
import ssl
import subprocess
import threading
import time
import types
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prometheus", type=Path, required=True)
    parser.add_argument("--alertmanager", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--reject-auth",
        action="store_true",
        help="Local sink returns 535; verify failure evidence and cleanup",
    )
    args = parser.parse_args()
    reject_auth = args.reject_auth
    parsed = urlparse(args.api_url)
    assert (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and not parsed.username
        and not parsed.password
    ), "Loopback HTTP API only"
    repo = Path(__file__).resolve().parents[1]
    root = args.out.resolve()
    root.mkdir(exist_ok=False)
    api_url = args.api_url.rstrip("/")
    spec = importlib.util.spec_from_file_location("mailcheck", repo / "scripts/external_alerts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bundle = root / "bundle"
    env = {
        "HARBINGER_SMTP_HOST": "smtp.example.test",
        "HARBINGER_SMTP_PORT": "465",
        "HARBINGER_SMTP_USERNAME": "test@example.test",
        "HARBINGER_SMTP_PASSWORD": "local-test-only",
        "HARBINGER_SMTP_FROM": "test@example.test",
        "HARBINGER_ALERT_TO": "owner@example.test",
    }
    mod.write_bundle(bundle, env, "local-mail-check")
    shutil.copyfile(repo / "deploy/monitoring/rules.yml", bundle / "config/rules.yml")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(root / "smtp.key"),
            "-out",
            str(bundle / "config/smtp-ca.pem"),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for name in ("prometheus.yml", "prometheus-normal.yml", "prometheus-test.yml"):
        p = bundle / "config" / name
        p.write_text(p.read_text().replace("127.0.0.1:8000", api_url.removeprefix("http://")))
    p = bundle / "config/alertmanager.yml"
    config = yaml.safe_load(p.read_text())
    config["global"]["smtp_smarthost"] = "127.0.0.1:1587"
    for r in config["receivers"]:
        r["email_configs"][0]["tls_config"] = {
            "ca_file": "/etc/hbmonitor/smtp-ca.pem",
            "server_name": "localhost",
        }
    p.write_text(yaml.safe_dump(config))
    p = bundle / "compose.yml"
    compose = yaml.safe_load(p.read_text())
    for name, s in compose["services"].items():
        data = root / name
        data.mkdir(exist_ok=True)
        data.chmod(0o777)
        s["volumes"][-1] = str(data) + ":/" + name
    p.write_text(yaml.safe_dump(compose))
    (bundle / "config").chmod(0o755)
    for p in (bundle / "config").iterdir():
        p.chmod(0o644)
    messages = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(bundle / "config/smtp-ca.pem", root / "smtp.key")

    class SMTP(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(10)
            sock = context.wrap_socket(self.request, server_side=True)
            f = sock.makefile("rb")

            def send(s):
                sock.sendall((s + "\r\n").encode())

            send("220 localhost test SMTP")
            while True:
                raw = f.readline()
                if not raw:
                    break
                line = raw.decode().strip()
                cmd = line.split(" ", 1)[0].upper()
                if cmd in ("EHLO", "HELO"):
                    send("250-localhost\r\n250-AUTH PLAIN\r\n250 8BITMIME")
                elif cmd == "AUTH":
                    credentials = base64.b64decode(line.split(" ", 2)[2])
                    assert credentials == b"\0test@example.test\0local-test-only"
                    send(
                        "535 5.7.1 deliberate local authentication rejection"
                        if reject_auth
                        else "235 authenticated test user"
                    )
                elif cmd in ("MAIL", "RCPT", "RSET", "NOOP"):
                    send("250 ok")
                elif cmd == "DATA":
                    send("354 end with dot")
                    rows = []
                    while True:
                        row = f.readline()
                        if row in (b".\r\n", b""):
                            break
                        rows.append(row)
                    m = email.message_from_bytes(b"".join(rows))
                    subject = str(email.header.make_header(email.header.decode_header(m["Subject"])))
                    messages.append(
                        {"subject": subject, "received_at": mod.now(), "tls": isinstance(sock, ssl.SSLSocket)}
                    )
                    send("250 accepted by local test sink")
                elif cmd == "QUIT":
                    send("221 bye")
                    break
                else:
                    send("502 unsupported")
            f.close()
            sock.close()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    smtp = Server(("127.0.0.1", 1587), SMTP)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    # Native binaries keep the same real protocol without Docker vfs storage amplification.
    for config_file in (bundle / "config").glob("*.yml"):
        config_file.write_text(
            config_file.read_text().replace("/etc/hbmonitor/", str(bundle / "config") + "/")
        )
    prom = args.prometheus.resolve()
    am = args.alertmanager.resolve()
    processes = []
    original_request = mod.request
    if reject_auth:
        original_wait = mod.wait_for
        mod.wait_for = lambda check, timeout=180: original_wait(check, 12 if timeout == 240 else timeout)
    mod.request = lambda url, post=False: original_request(
        url.replace("http://127.0.0.1:8000", api_url), post
    )
    mod.subprocess = types.SimpleNamespace(
        run=lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=(root / "alertmanager.log").read_text(), stderr=""
        )
    )
    try:
        subprocess.run(
            [str(prom.parent / "promtool"), "check", "config", str(bundle / "config/prometheus.yml")],
            check=True,
        )
        subprocess.run(
            [str(am.parent / "amtool"), "check-config", str(bundle / "config/alertmanager.yml")], check=True
        )
        for name, args in [
            (
                "prometheus",
                [
                    str(prom),
                    "--config.file=" + str(bundle / "config/prometheus.yml"),
                    "--storage.tsdb.path=" + str(root / "prom-data"),
                    "--web.listen-address=127.0.0.1:19090",
                    "--web.enable-lifecycle",
                ],
            ),
            (
                "alertmanager",
                [
                    str(am),
                    "--config.file=" + str(bundle / "config/alertmanager.yml"),
                    "--storage.path=" + str(root / "am-data"),
                    "--web.listen-address=127.0.0.1:19093",
                    "--cluster.listen-address=",
                    "--log.level=debug",
                    "--log.format=json",
                ],
            ),
        ]:
            processes.append(
                subprocess.Popen(args, stdout=(root / (name + ".log")).open("w"), stderr=subprocess.STDOUT)
            )
        for port in (19090, 19093):
            for _i in range(60):
                try:
                    with urlopen(f"http://127.0.0.1:{port}/-/ready", timeout=2) as r:
                        if r.status == 200:
                            break
                except OSError:
                    time.sleep(1)
            else:
                raise TimeoutError("monitor not ready")
        try:
            mod.verify_on_host(bundle, root / "result.json")
        except TimeoutError:
            if not reject_auth:
                raise
        finally:
            if (root / "result.json").exists():
                record = json.loads((root / "result.json").read_text())
                record["scope"] = "local authenticated implicit TLS SMTP sink; no external mail sent"
                record["operator_receipt_confirmed"] = False
                (root / "result.json").write_text(json.dumps(record, indent=2) + "\n")
        if reject_auth:
            assert not messages and record["transport_verified"] is False
            assert record["normal_after_test"] and record["test_rule_removed"]
            assert any(
                e["category"] == "authentication" and e["smtp_code"] == "535"
                for e in record["email_transport_failures"]
            )
            print(
                "PASS: deliberate local SMTP 535 rejection recorded without secrets; normal cleanup; no external mail sent"
            )
            return
        assert len(messages) == 2, messages
        assert "FIRING" in messages[0]["subject"] and "RESOLVED" in messages[1]["subject"]
        assert all(m["tls"] and "local-mail-check" in m["subject"] for m in messages)
        (root / "smtp-messages.json").write_text(
            json.dumps(
                {"scope": "local implicit TLS SMTP sink; not operator mailbox receipt", "messages": messages},
                indent=2,
            )
        )
        print(
            "PASS: actual Prometheus/Alertmanager -> local authenticated implicit TLS SMTP sink, firing/resolved, normal cleanup; no external mail sent"
        )
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=15)
        smtp.shutdown()
        smtp.server_close()
        (root / "smtp.key").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
