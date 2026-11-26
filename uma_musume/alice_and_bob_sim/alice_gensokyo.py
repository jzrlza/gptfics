import base64
import hashlib
import hmac
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

KEY_DIR = "keys_alice"
ALICE_PRIV_PATH = os.path.join(KEY_DIR, "alice_private.key")
ALICE_PUB_PATH = os.path.join(KEY_DIR, "alice_public.key")
BOB_PUB_PATH = os.path.join(KEY_DIR, "bob_public.key")
RELAY_SEND_URL = "http://127.0.0.1:8002/relay/to-bob"

INBOX_FROM_BOB = []


def ensure_alice_keys():
    os.makedirs(KEY_DIR, exist_ok=True)
    if not os.path.exists(ALICE_PRIV_PATH):
        with open(ALICE_PRIV_PATH, "w", encoding="utf-8") as f:
            f.write("gensokyo_alice_priv_9f8a7b6c5d4e3f2a\n")
    with open(ALICE_PRIV_PATH, "r", encoding="utf-8") as f:
        priv = f.read().strip()

    pub = hashlib.sha256(f"PUB::{priv}".encode("utf-8")).hexdigest()
    if not os.path.exists(ALICE_PUB_PATH):
        with open(ALICE_PUB_PATH, "w", encoding="utf-8") as f:
            f.write(pub + "\n")
    if not os.path.exists(BOB_PUB_PATH):
        bob_priv_seed = "outside_bob_priv_66554433221100ff"
        bob_pub = hashlib.sha256(f"PUB::{bob_priv_seed}".encode("utf-8")).hexdigest()
        with open(BOB_PUB_PATH, "w", encoding="utf-8") as f:
            f.write(bob_pub + "\n")


def load_key(path: str) -> str:
    ensure_alice_keys()
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def xor_stream(data: bytes, material: str) -> bytes:
    stream = hashlib.sha256(material.encode("utf-8")).digest()
    return bytes(b ^ stream[i % len(stream)] for i, b in enumerate(data))


def sign_payload(canonical_json: str, private_key: str) -> str:
    return hmac.new(
        private_key.encode("utf-8"),
        canonical_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(canonical_json: str, signature: str, peer_public_key: str) -> bool:
    # Verifies against signing material tied to the peer's public key
    peer_signing_key = hashlib.sha256(f"SIGNKEY::{peer_public_key}".encode("utf-8")).hexdigest()
    expected = hmac.new(
        peer_signing_key.encode("utf-8"),
        canonical_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def derive_signing_key_from_priv(private_key: str) -> str:
    pub = hashlib.sha256(f"PUB::{private_key}".encode("utf-8")).hexdigest()
    return hashlib.sha256(f"SIGNKEY::{pub}".encode("utf-8")).hexdigest()


def encrypt_for_peer_pub(plain_bytes: bytes, peer_public_key: str) -> str:
    cipher = xor_stream(plain_bytes, f"ENC::{peer_public_key}")
    return base64.b64encode(cipher).decode("utf-8")


def decrypt_with_own_priv(ciphertext_b64: str, own_private_key: str) -> str:
    own_pub = hashlib.sha256(f"PUB::{own_private_key}".encode("utf-8")).hexdigest()
    raw = base64.b64decode(ciphertext_b64)
    plain = xor_stream(raw, f"ENC::{own_pub}")
    return plain.decode("utf-8")


def process_incoming_from_bob(packet: dict) -> dict:
    alice_priv = load_key(ALICE_PRIV_PATH)
    bob_pub = load_key(BOB_PUB_PATH)

    if not packet.get("encrypted"):
        payload = packet.get("payload", {})
        if payload.get("action") == "terminate_project":
            return {
                "status": "PROJECT_TERMINATED",
                "reason": "Unencrypted incoming packet tampered to terminate_project!",
                "payload": payload,
            }
        return {
            "status": "ACCEPTED_UNENCRYPTED",
            "reason": "Received naked message from Bob without encryption.",
            "payload": payload,
        }

    try:
        if packet.get("sender_public_key") != bob_pub:
            raise ValueError("Untrusted sender public key")
        decrypted_text = decrypt_with_own_priv(packet["ciphertext"], alice_priv)
        parsed = json.loads(decrypted_text)
        canonical = json.dumps(parsed, sort_keys=True)
        if not verify_signature(canonical, packet.get("signature", ""), bob_pub):
            raise ValueError("Invalid signature")
        return {
            "status": "ACCEPTED_ENCRYPTED_VERIFIED",
            "reason": "Decrypted with Alice's private key & verified Bob's signature.",
            "payload": parsed,
        }
    except Exception as exc:
        return {
            "status": "CORRUPT_TAMPER_REJECTED",
            "reason": f"Tampered/corrupt packet rejected ({exc}).",
            "payload": None,
        }


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Alice — Gensokyo (:8001)</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #141625; color: #f1f3f9; max-width: 780px; margin: 28px auto; padding: 0 16px; }
    .card { background: #1e2238; border: 1px solid #323859; border-radius: 10px; padding: 18px; margin-bottom: 16px; }
    h1 { color: #8ab4f8; margin: 0 0 6px; }
    label { display: block; margin: 10px 0 6px; font-weight: 600; }
    textarea, select { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #444b73; background: #121526; color: #fff; box-sizing: border-box; }
    button { background: #4f7df3; color: #fff; border: none; padding: 10px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; margin-top: 12px; }
    pre { background: #0f111e; padding: 10px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
    .msg { border-top: 1px solid #323859; padding-top: 10px; margin-top: 10px; }
    .tag { display: inline-block; padding: 3px 8px; border-radius: 5px; font-size: 12px; font-weight: 700; background: #263566; color: #b8ceff; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Alice Margatroid — Gensokyo (:8001)</h1>
    <div>Keys stored in <code>keys_alice/</code> (Alice private + Bob public). Yukari has zero keys.</div>

    <label for="encMode">Communication Mode</label>
    <select id="encMode">
      <option value="true" selected>Encrypted + Signed (Alice Private Sign + Bob Public Encrypt)</option>
      <option value="false">Non-Encrypted (Naked Plaintext)</option>
    </select>

    <label for="msgText">Message to Bob (Outside World)</label>
    <textarea id="msgText" rows="2">Let's make Touhou Spell Bubble happen together and help create the Spell Bubble rules!</textarea>

    <button id="sendBtn">Send to Bob via Rinnosuke (:8002)</button>
    <pre id="lastSend">No outgoing packet sent yet.</pre>
  </div>

  <div class="card">
    <h2>Incoming Messages from Bob</h2>
    <div id="inbox">Waiting for messages from Bob...</div>
  </div>

  <script>
    document.getElementById("sendBtn").addEventListener("click", async () => {
      const res = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          encrypt_mode: document.getElementById("encMode").value === "true",
          note: document.getElementById("msgText").value
        })
      });
      const data = await res.json();
      document.getElementById("lastSend").textContent = JSON.stringify(data, null, 2);
    });

    async function refreshInbox() {
      const res = await fetch("/api/inbox");
      const items = await res.json();
      const box = document.getElementById("inbox");
      if (!items.length) return;
      box.innerHTML = items.slice().reverse().map(i => `
        <div class="msg">
          <span class="tag">${i.status}</span>
          <div>${i.reason}</div>
          <pre>${JSON.stringify(i.payload || i.raw_packet, null, 2)}</pre>
        </div>
      `).join("");
    }
    setInterval(refreshInbox, 1000);
    refreshInbox();
  </script>
</body>
</html>
"""


class AliceHandler(BaseHTTPRequestHandler):
    def _json(self, code: int, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _html(self, html: str):
        raw = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._html(HTML_PAGE)
        elif self.path == "/api/inbox":
            self._json(200, INBOX_FROM_BOB)
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        if self.path == "/api/send":
            alice_priv = load_key(ALICE_PRIV_PATH)
            alice_pub = load_key(ALICE_PUB_PATH)
            bob_pub = load_key(BOB_PUB_PATH)
            encrypt_mode = bool(body.get("encrypt_mode", True))

            payload = {
                "from": "Alice Margatroid (Gensokyo)",
                "to": "Bob (Outside World - Bubble Bobble)",
                "project": "Touhou Spell Bubble",
                "action": "create_spell_bubble_rules",
                "note": body.get("note", ""),
            }

            if not encrypt_mode:
                packet = {"encrypted": False, "payload": payload}
            else:
                canonical = json.dumps(payload, sort_keys=True)
                sig = sign_payload(canonical, derive_signing_key_from_priv(alice_priv))
                packet = {
                    "encrypted": True,
                    "ciphertext": encrypt_for_peer_pub(canonical.encode("utf-8"), bob_pub),
                    "signature": sig,
                    "sender_public_key": alice_pub,
                }

            req = urllib.request.Request(
                RELAY_SEND_URL,
                data=json.dumps(packet).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                relay_res = json.loads(resp.read().decode("utf-8"))
            self._json(200, {"sent_packet": packet, "relay_response": relay_res})
            return

        if self.path == "/receive":
            outcome = process_incoming_from_bob(body)
            INBOX_FROM_BOB.append({**outcome, "raw_packet": body})
            self._json(200, outcome)
            return

        self._json(404, {"error": "Not found"})


if __name__ == "__main__":
    ensure_alice_keys()
    print("[ALICE UI + SERVER] Running at http://127.0.0.1:8001")
    HTTPServer(("127.0.0.1", 8001), AliceHandler).serve_forever()