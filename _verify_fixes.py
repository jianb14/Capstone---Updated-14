import os
import re
import subprocess
import tempfile

# 1) Syntax-check the widget JavaScript with node (if available).
# Django template tags ({% ... %} / {{ ... }}) are not valid JS — substitute
# placeholders so node only checks the real JavaScript.
html = open("app/templates/client/base.html", encoding="utf-8").read()
scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
body = "\n".join(scripts)
js = re.sub(r"{%.*?%}", '"__TAG__"', body)
js = re.sub(r"{{.*?}}", '"__VAR__"', js)
tmp = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
tmp.write(js)
tmp.close()
node_ok = None
try:
    proc = subprocess.run(
        ["node", "--check", tmp.name], capture_output=True, text=True, timeout=30
    )
    node_ok = proc.returncode == 0
    node_out = proc.stderr.strip()[:400]
except FileNotFoundError:
    node_out = "node not installed"
os.unlink(tmp.name)

print(("PASS" if node_ok else ("FAIL" if node_ok is False else "SKIP ")) + " node --check widget JS " + (node_out or ""))

# CSS lives in <style>, not in <script> — check the whole HTML for it
html_all = html
mic = re.search(r"// ---- Voice input \(Web Speech API\) ----(.*?)// ---- Inspiration photo", body, re.DOTALL).group(1)
checks = [
    ("exactly one mic click listener", mic.count("micBtn.addEventListener('click'") == 1),
    ("starts with fil-PH then falls back to en-US", "startRecognition(micLang)" in mic and "startRecognition('en-US')" in mic),
    ("interim results ON (live text while speaking)", "interimResults = true" in mic),
    ("input filled during speaking (no auto-send)", "chatInput.value = text" in mic and "chatInput.dispatchEvent(new Event('input'))" in mic),
    ("red .listening CSS exists in both themes", "#ai-widget-mic.listening" in html_all and '[data-theme="light"] #ai-widget-mic.listening' in html_all),
    ("mic errors shown as visible red bubbles", "showVoiceError(" in mic),
    ("placeholder says Listening... while active", "'Listening... speak now'" in mic),
    ("cursor fully removed while typing", "ai-stream-cursor" not in body.split("// ---- Voice input")[0].split("formatMarkdown(streamedText)")[-1] and body.count("ai-stream-cursor") <= 1),
    ("smart scroll present (no yank when reading up)", "isScrolledUp" in body),
    ("stream max_tokens raised to 1400", "max_tokens=1400" in open("app/services.py", encoding="utf-8").read()),
    ("stream continuation on truncation", "Streaming Continuation Error" in open("app/services.py", encoding="utf-8").read()),
]
all_ok = node_ok is not False
for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
    all_ok = all_ok and ok
print("ALL_OK" if all_ok else "SOME_FAILED")
