import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Project.settings")
django.setup()

from app.services import stream_chatbot_events

out = open("_ls_result.txt", "w", encoding="utf-8")
def say(line):
    out.write(str(line) + "\n")
    out.flush()

# Long-reply request: this used to get cut off at the old 720-token cap.
full = ""
delta_count = 0
for event in stream_chatbot_events(
    "List all our packages with their complete prices and every inclusions. Be very detailed and list everything.",
    conversation_history=None,
    user=None,
):
    if event.get("type") == "delta":
        full += event.get("text", "")
        delta_count += 1
    elif event.get("type") == "final":
        data = event.get("data", {})
        final_text = (data.get("text") or "").strip()
        say(f"delta_events={delta_count}")
        say(f"streamed_len={len(full)}")
        say(f"final_len={len(final_text)}")
        say(f"stream_equals_final={full.strip() == final_text}")
        tail = final_text[-260:].replace(chr(10), ' | ')
        say(f"TAIL: {tail}")
        import re as _re
        looks_cut = bool(_re.search(r"(\b(\d+\.|Step \d|PHP|\*|-)\s*[^.!?\n]*)$", final_text.strip().rstrip('.,;: '))) and not final_text.rstrip().endswith(('.', '!', '?', ':', ')'))
        say(f"LOOKS_TRUNCATED={looks_cut}")
        break
say("DONE")
out.close()
