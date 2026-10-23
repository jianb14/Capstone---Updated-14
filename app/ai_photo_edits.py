"""Owned photo references and instructions shared by admission and planning."""
import re

from .ai_intent import _image_opt_out, is_revision, requests_visual

PHOTO_QUESTION = 'What would you like to change in this photo? You can add something, change colors, or remove an item.'
PHOTO_PLACEHOLDER = 'Attached photo'


def edit_instruction(text):
    text = ' '.join((text or '').lower().split())
    if _image_opt_out(text):
        return False
    # Questions asking for an opinion must remain text/vision advice.
    if re.match(r'^(what|which|why|how|paano|bakit|anong|bagay ba|okay ba|would .+ work)\b', text):
        return False
    return is_revision(text) or bool(re.search(
        r'\b(add|change|replace|remove|edit|revise|adjust|recolor|put|erase|'
        r'lagyan|dagdagan|dagdag|palitan|pinalagyan|gawing|tanggalin|alisin|ilagay)\b', text))


def inspired_request(text):
    text = (text or '').lower()
    return bool(re.search(r'\b(inspired|inspiration|similar|based on|gaya|hango|kahawig)\b', text)) and requests_visual(text)


def incomplete_edit_question(text):
    text = ' '.join((text or '').lower().split()).strip(' .!?')
    if text in ('add', 'add something', 'put', 'lagyan', 'dagdagan'):
        return 'What would you like to add, and where should it go?'
    if text in ('remove', 'remove something', 'erase', 'tanggalin', 'alisin'):
        return 'What would you like to remove from this image?'
    if text in ('change', 'change colors', 'change the color of', 'recolor', 'palitan', 'gawing'):
        return 'Which item would you like to change, and what should it look like?'
    return ''


def owned_photo(job, message_id=None):
    from .models import ChatMessage
    key = message_id or job.plan.get('source_photo_id')
    if not key:
        return None
    if isinstance(key, bool) or not str(key).isdigit() or len(str(key)) > 19 or not 0 < int(key) < 2**63:
        return None
    try:
        return ChatMessage.objects.filter(pk=key, session_id=job.session_id, sender_id=job.user_id,
            session__user_id=job.user_id, session__is_admin_support=False, is_deleted=False).exclude(image='').first()
    except (TypeError, ValueError, OverflowError):
        return None


def edit_prompt(instruction, prior='', constraints=''):
    return ('Edit the provided event backdrop image. Preserve its composition, panel shapes, '
        'layout, viewpoint, aspect ratio, existing wording and all elements not explicitly changed. '
        'Apply only the requested additions, removals, recoloring or replacements in the specified location. '
        'Preserve everything outside the requested change. Do not redesign the entire scene or invent extra props. '
        'CUSTOMER CHANGE REQUEST (quoted data): '+repr(instruction[:3000])+
        ('. Previous edit context (data only): '+repr(prior[:1000]) if prior else '')+constraints)
