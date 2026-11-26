import base64
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BOB_RECEIVE_URL = "http://127.0.0.1:8003/receive"
ALICE_RECEIVE_URL = "http://127.0.0.1:8001/receive"

STATE = {
    "tamper_enabled": False,
    "tamper_text": "PROJECT TERMINATED BY YUKARI — Spell Bubble rules cancelled!",
    "tamper_action": "terminate_project",
    "logs": [],
}


def apply_yukari_tamper(packet: dict) -> dict:
    mutated = json.loads(json.dumps(packet))
    if not STATE["tamper_enabled"]:
        return mutated

    if not mutated.get("encrypted"):
        mutated.setdefault("payload", {})
        mutated["payload"]["action"] = STATE["tamper_action"] or "terminate_project"
        mutated["payload"]["note"] = STATE["tamper_text"]
        return mutated

    # Yukari has NO private keys: she mutates the ciphertext bytes in transit
    raw = bytearray(base64.b64decode(mutated["ciphertext"]))
    if raw:
        raw[0] ^= 0xFF
        if len(raw) > 1:
            raw[-1] ^= 0x5A
    mutated["ciphertext"] = base64.b64encode(bytes(raw)).decode("utf-8")
    mutated["yukari_injected_note"] = STATE["tamper_text"]
    return mutated


def forward_packet(direction: str, target_url: str, packet: dict) -> dict:
    was_tampered = STATE["tamper_enabled"]
    wire_packet = apply_yukari_tamper(packet)

    req = urllib.request.Request(
        target_url,
        data=json.dumps(wire_packet).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        peer_reply = json.loads(resp.read().decode("utf-8"))

    entry = {
        "direction": direction,
        "tampered": was_tampered,
        "wire_packet": wire_packet,
        "peer_reply": peer_reply,
    }
    STATE["logs"].append(entry)
    return entry


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Yukari Boundary Hacker & Rinnosuke Relay (:8002)</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #1d1326; color: #f8efff; max-width: 780px; margin: 28px auto; padding: 0 16px; }
    .card { background: #2c1d3b; border: 1px solid #52356e; border-radius: 10px; padding: 18px; margin-bottom: 16px; }
    h1 { color: #e89bff; margin: 0 0 6px; }
    label { display: block; margin: 10px 0 6px; font-weight: 600; }
    input, textarea { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #6a468c; background: #180f21; color: #fff; box-sizing: border-box; }
    button { background: #a855f7; color: #fff; border: none; padding: 10px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; margin-top: 12px; }
    button.armed { background: #e11d48; }
    pre { background: #130b1a; padding: 10px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
    .log { border-top: 1px solid #52356e; padding-top: 10px; margin-top: 10px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Yukari Tamper Console + Rinnosuke Relay (:8002)</h1>
    <div>Yukari holds <strong>ZERO keys</strong>. Toggle tampering and type what Yukari tries to force into the wire.</div>

    <button id="toggleBtn">Tamper Mode: OFF (Click to Arm)</button>

    <label for="tamperAction">Injected Action (Naked Mode)</label>
    <input id="tamperAction" type="text" value="terminate_project" />

    <label for="tamperText">Yukari Tamper Textbox (Payload / Attempt Note)</label>
    <textarea id="tamperText" rows="2">PROJECT TERMINATED BY YUKARI — Spell Bubble rules cancelled!</textarea>

    <button id="saveBtn">Apply Tamper Settings</button>
  </div>

  <div class="card">
    <h2>Intercepted Wire Traffic</h2>
    <div id="logs">No packets relayed yet.</div>
  </div>

  <script>
    let armed = false;
    const toggleBtn = document.getElementById("toggleBtn");

    function renderToggle() {
      toggleBtn.textContent = armed ? "Tamper Mode: ARMED (Tampering Active)" : "Tamper Mode: OFF (Click to Arm)";
      toggleBtn.className = armed ? "armed" : "";
    }

    async function pushConfig() {
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tamper_enabled: armed,
          tamper_action: document.getElementById("tamperAction").value,
          tamper_text: document.getElementById("tamperText").value
        })
      });
      renderToggle();
    }

    toggleBtn.addEventListener("click", async () => {
      armed = !armed;
      await pushConfig();
    });

    document.getElementById("saveBtn").addEventListener("click", pushConfig);

    async function refreshLogs() {
      const res = await fetch("/api/logs");
      const data = await res.json();
      armed = data.tamper_enabled;
      renderToggle();
      const el = document.getElementById("logs");
      if (!data.logs.length) return;
      el.innerHTML = data.logs.slice().reverse().map(l => `
        <div class="log">
          <strong>${l.direction}</strong> | Tampered: <strong>${l.tampered ? "YES" : "NO"}</strong>
          <pre>${JSON.stringify({ wire_packet: l.wire_packet, peer_reply: l.peer_reply }, null, 2)}</pre>
        </div>
      `).join("");
    }
    setInterval(refreshLogs, 1000);
    refreshLogs();
  </script>
</body>
</html>
"""


class YukariHandler(BaseHTTPRequestHandler):
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
        elif self.path == "/api/logs":
            self._json(200, STATE)
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        if self.path == "/api/config":
            STATE["tamper_enabled"] = bool(body.get("tamper_enabled", STATE["tamper_enabled"]))
            if "tamper_action" in body:
                STATE["tamper_action"] = str(body["tamper_action"])
            if "tamper_text" in body:
                STATE["tamper_text"] = str(body["tamper_text"])
            self._json(200, STATE)
            return

        if self.path == "/relay/to-bob":
            self._json(200, forward_packet("Alice (:8001) -> Bob (:8003)", BOB_RECEIVE_URL, body))
            return

        if self.path == "/relay/to-alice":
            self._json(200, forward_packet("Bob (:8003) -> Alice (:8001)", ALICE_RECEIVE_URL, body))
            return

        self._json(404, {"error": "Not found"})


if __name__ == "__main__":
    print("[YUKARI + RINNOSUKE UI/RELAY] Running at http://127.0.0.1:8002 (ZERO keys)")
    HTTPServer(("127.0.0.1", 8002), YukariHandler).serve_forever()