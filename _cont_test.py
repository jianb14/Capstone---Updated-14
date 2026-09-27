import contextlib
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Project.settings")
django.setup()

from django.conf import settings
import app.services as S

# --- Fake HF client: first stream hits the token cap mid-sentence, the
# --- continuation (non-stream) call supplies the missing ending.
class FakeChunk:
    """A single streamed chunk shaped like huggingface_hub's output."""

    def __init__(self, content=None, finish=None):
        choice = type("Choice", (), {})
        choice.delta = type("Delta", (), {"content": content})()
        choice.finish_reason = finish
        self.choices = [choice]

class FakeResponse:
    def __init__(self, message_content):
        choice = type("Choice", (), {})
        choice.message = type("Message", (), {"content": message_content})()
        choice.finish_reason = "stop"
        self.choices = [choice]

class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def chat_completion(self, messages, **kwargs):
        if kwargs.get("stream"):
            return iter([
                FakeChunk(content="Here is the full package list with prices:\n- Package 1-A: PHP 4,799.00 (1 panel,"),
                FakeChunk(content=None, finish="length"),  # cut off mid-list
            ])
        # Non-stream continuation
        return FakeResponse(" 2 buri mats, drop lights, celebrant chair.) That is the complete list.")

S.InferenceClient = FakeClient
S._without_dead_local_proxy = lambda: contextlib.nullcontext()
# Anonymous (user=None) moderation returns an empty payload in tests — bypass.
S.evaluate_chat_moderation = lambda user, message: None

_orig_payload = S._chat_response_payload
payload_calls = []
def _spy_payload(text=None, *args, **kwargs):
    import traceback
    payload_calls.append((str(text)[:60], traceback.format_stack(limit=6)[-4:-1]))
    return _orig_payload(text, *args, **kwargs)
S._chat_response_payload = _spy_payload

settings.HUGGINGFACE_API_KEY = "test-key"

full = ""
saw_continuation_delta = False
final_text = ""
event_log = []
for event in S.stream_chatbot_events("List our packages with prices", None, None):
    etype = event.get("type")
    event_log.append(etype + (":" + str(event.get("message", event.get("data", "")))[:150] if etype in ("error", "final") else ""))
    if etype == "delta":
        chunk = event.get("text", "")
        if "complete list" in chunk:
            saw_continuation_delta = True
        full += chunk
    elif etype == "final":
        final_text = event["data"].get("text", "")
        break

out = []
out.append("EVENT_LOG: " + " || ".join(event_log[:6]))
for text, stack in payload_calls:
    out.append(f"PAYLOAD_CALL text={text!r}")
    for line in stack:
        out.append("   " + line.strip().replace("\n", " "))

out.append(f"streamed_len={len(full)}")
out.append(f"complete_reply={full.strip().endswith('complete list.')}")
out.append(f"continuation_streamed_as_delta={saw_continuation_delta}")
out.append(f"final_contains_ending={'complete list' in final_text}")
ok = (
    full.strip().endswith("complete list.")
    and saw_continuation_delta
    and "complete list" in final_text
)
out.append("ALL_OK" if ok else "SOME_FAILED")
with open("_cont_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))
