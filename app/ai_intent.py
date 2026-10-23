"""Customer intent is decided before a model can request a paid image operation."""
import re


def _image_opt_out(text):
    return bool(re.search(
        r"\b(don't|do not|no need to|without|huwag|wag|ayaw)\b.{0,35}"
        r"\b(generate|create|make|image|picture|gumawa|gawa)\b|"
        r"\b(text only|advice only|no images?|no pictures?)\b", text))


def _asks_for_prompt(text):
    return bool(re.search(
        r'\b(write|generate|create|make|give|provide|share|send)\s+'
        r'(?:(?:me|us|an?|the|some|please)\s+)*(?:image|design|backdrop)\s+prompts?\b', text))


def requests_visual(text):
    """Recognize a visual request in its own clause, including mixed questions."""
    lowered = ' '.join((text or '').lower().split())
    if _image_opt_out(lowered):
        return False
    clauses = re.split(r'[?!;.]\s*|\b(?:and|also|at|tapos|saka)\s+', lowered)
    for clause in clauses:
        # Asking how generation works must never spend image credits.
        if re.match(r'^(how\b|paano\b|why\b|bakit\b|what (?:is|are|happens)\b|'
                    r'(?:can|could) you explain\b)', clause.strip()):
            continue
        if _asks_for_prompt(clause):
            continue
        if re.search(r'\b(generate|regenerate|draw|render|gumawa|igawa|gawan|gawa|pakita|ipakita|patingin)\b', clause):
            return True
        if re.search(r'\b(create|make|show|see|view|makita|makakita|tingnan|want|like)\b.{0,100}'
                     r'\b(images?|pictures?|photos?|backdrops?|designs?|versions?|concepts?)\b', clause):
            return True
        if re.search(r'\b(give|provide|send|share|include|attach|pahingi|pasend|ibigay|bigyan)\b.{0,70}'
                     r'\b(images?|pictures?|photos?|(?:sample|example)\s+(?:of\s+)?(?:a\s+)?(?:backdrop|design))\b', clause):
            return True
    return False


def requests_information(text):
    """Keep requested business details when the same message also asks for a visual."""
    lowered = ' '.join((text or '').lower().split())
    return bool(re.search(
        r'\b(what|which|how much|how to|magkano|ano|anong|list|tell|explain|compare|'
        r'recommend|give|provide|show|ibigay|paano)\b.{0,100}'
        r'\b(packages?|pricing|prices?|cost|inclusions?|booking|availability|payment|services?)\b|'
        r'\b(packages?|booking|payment)\b.{0,50}\b(prices?|cost|inclusions?|details|steps|process)\b', lowered))


def is_advice_question(text):
    lowered = ' '.join((text or '').lower().split())
    # Explicit negative instructions always win, including a supplied Generate flag.
    if _image_opt_out(lowered):
        return True
    if re.match(r'^(bagay ba|bagay kaya|babagay ba|okay ba|ok ba)\b', lowered):
        return True
    if requests_visual(lowered):
        return False
    if _asks_for_prompt(lowered):
        return True
    if re.match(r'^(how|paano|what happens|what is|what are|why|can you explain|could you explain)\b', lowered):
        return True
    # A request to generate can itself be phrased as a polite question.
    if re.search(r'\b(generate|regenerate|draw|render|gumawa|igawa|gawan|gawa|pakita|patingin)\b', lowered):
        return False
    if re.search(r'\b(create|make|show)\b.{0,45}\b(image|picture|photo|backdrop|design|version|concept)\b', lowered):
        return False
    if re.match(r'^(can|could|would|will) you (please )?(suggest|recommend|tell|help|explain)\b', lowered):
        return True
    return bool(re.match(r'^(please\s+)?(what|which|why|how|when|where|can you explain|could you explain|do (?:you|the|your|packages?)|does|did|is|are|ano|anong|alin|paano|bakit|kailan|saan|magkano|meron|mayroon|pwede ba|puwede ba)\b', lowered))


def is_revision(text):
    lowered = (text or '').lower().strip()
    if requests_information(lowered) and requests_visual(lowered) and not re.search(
            r'\b(change|replace|remove|edit|revise|adjust|palitan|gawing|tanggalin|alisin)\b', lowered):
        # "Include a sample" alongside a package question asks for an example,
        # rather than an edit of the last design in this chat.
        return False
    return not is_advice_question(lowered) and bool(re.search(
        r'\b(change|replace|remove|add|include|keep|preserve|edit|revise|adjust|simplify|reduce|increase|'
        r'palitan|gawing|tanggalin|alisin|dagdagan|lagyan|panatilihin|liitan|lakihan)\b', lowered))


def wants_generation(text, *, explicit=False, has_reference=False):
    if is_advice_question(text):
        return False
    if explicit or requests_visual(text) or (has_reference and is_revision(text)):
        return True
    from .services import is_image_request, _asks_for_new_image_variant
    return is_image_request(text) or (has_reference and _asks_for_new_image_variant(text))
