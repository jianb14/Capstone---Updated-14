"""Decide how to use tool facts; a topic label is not a complete answer."""
import re


DETAIL_REQUEST = re.compile(
    r'\b(why|because|explain|meaning|means?|difference|compare|recommend|suggest|'
    r'fill|filling|fields?|form|confused|trouble|errors?|failed|stuck|already|still|'
    r'only|specifically|instead|bakit|kasi|paliwanag|ipaliwanag|ibig sabihin|'
    r'kaibahan|pagkakaiba|nalilito|turuan|paturo|tulungan|ayaw|hindi|di|'
    r'alin|bagay|babagay|suitable|step\s*\d+)\b|step[- ]by[- ]step', re.I)


def answer_mode(text, actions):
    """Specificity applies to every informational tool, independently of routing.

    Only simple overviews and small factual lookups bypass answer composition.
    Everything else uses the current question, history and verified tool facts.
    """
    text = ' '.join(str(text or '').lower().split()).rstrip(' ?!.')
    actions = set(actions)
    if 'clarify' in actions:
        return 'clarify'
    if 'answer' in actions:
        return 'focused'
    information = actions - {'generate', 'edit'}
    if not information:
        return 'visual'
    if len(actions) > 1 or DETAIL_REQUEST.search(text):
        return 'focused'
    action = next(iter(information))
    if action == 'booking_help':
        return 'overview' if re.fullmatch(
            r'(?:please )?(?:how (?:to|do i|can i) book(?: a (?:balloon )?setup)?|'
            r'paano mag(?:pa)?[ -]?book(?: ng setup)?)(?: po)?', text) else 'focused'
    if action == 'payment_help':
        if re.fullmatch(r'(?:please )?(?:how (?:to|do i|can i) pay(?: for my booking)?|'
                r'paano mag[ -]?bayad)(?: po)?', text):
            return 'overview'
        if re.fullmatch(r'(?:what|which|anong|ano(?: ang)?)(?: are| is)?(?: your| the| mga)? '
                r'(?:payment (?:methods?|options?)|modes? of payment)'
                r'(?: (?:do you (?:accept|support|offer)|are (?:available|accepted)|ang (?:pwede|available)|niyo|ninyo))?', text):
            return 'fact'
        return 'focused'
    if action == 'packages':
        # Listing/price/inclusion lookups are factual; comparisons and advice
        # were excluded above, even if the classifier only chose "packages".
        if re.search(r'\b(colors?|colours?|kulay|themes?|palettes?)\b', text) and not re.search(
                r'\b(how many|max|maximum|limit|ilan|include|allow)\b', text):
            return 'focused'
        package_name = r'package\s+\d+(?:[- ]?[a-z])?'
        general = (r'(?:our|your) packages|(?:please )?(?:list|show|give|provide)(?: me)?(?: your| the| all| active)* packages|'
            r'what (?:are your packages|packages do you offer|packages are available)|'
            r'ano(?: ano)?(?: ang| yung| mga)* packages?(?: niyo| ninyo)|'
            r'magkano(?: ang| yung)? packages?(?: niyo| ninyo)|'
            r'(?:what|which) packages (?:are )?(?:under|below|up to) (?:php )?[\d,.]+')
        atomic = (r'(?:magkano(?: ang| yung)?|how much is|what is the (?:price|cost) of) '+package_name+'|'
            r'what is included in '+package_name+'|'
            r'does '+package_name+r' include (?:an? )?(?:chair|panel|cake stand|drop light|buri mat)|'
            r'how many (?:panels|colors|colours) (?:are (?:included|allowed) in|does) '+package_name+r'(?: allow| include)?')
        if re.fullmatch(general+'|'+atomic, text):
            return 'fact'
        return 'focused'
    if action == 'availability':
        calendar_words = set(('are you is it available availability check date dates on from to through until '
            'what when ba sa bakante ngayong ngayon bukas today tomorrow next week kailan kelan araw '
            'january february march april may june july august september october november december '
            'jan feb mar apr jun jul aug sep sept oct nov dec enero pebrero marso abril mayo hunyo '
            'hulyo agosto setyembre oktubre nobyembre disyembre').split())
        return 'fact' if all(word.isdigit() or word in calendar_words for word in re.findall(r'\w+', text)) else 'focused'
    if action == 'booking_hours':
        simple = not re.search(r'\d|\b(if|kapag|kung|late|early|earlier|later|outside)\b', text)
        return 'fact' if len(text) < 180 and simple else 'focused'
    if action in ('booking_status', 'payment_status'):
        return 'fact' if re.fullmatch(
            r'(?:check my (?:booking|payment)(?:\s*#?\s*\d+)? status|'
            r'what is the status of my (?:booking|payment)|'
            r'verified na ba (?:yung|ang) payment ko)', text) else 'focused'
    if action == 'gallery':
        simple = not re.search(r'\b(how|what|which|paano|anong|saan|materials|built|made|size|source|if|kapag)\b', text)
        return 'fact' if len(text) < 160 and simple and re.match(
            r'^(?:please )?(?:show(?: me)?|(?:can|could|may) i (?:see|view)|view|see|patingin|'
            r'(?:(?:pwede|puwede) )?(?:pakita|ipakita|makita)|gallery|portfolio)\b', text) else 'focused'
    return 'focused'


FOCUSED_ANSWER_INSTRUCTIONS = (
    'Respond to the precise CURRENT request, not just its topic. Read-only tool results are source facts, '
    'not a reply template to copy. A factual overview can be correct yet fail to answer a specific question. '
    'For a particular field, error, comparison, reason, or numbered step, explain that part first and stay on it. '
    'Use earlier assistant steps only to resolve references such as "step 3" or "that field". '
    'For a form-filling walkthrough, name the real required fields, explain what to enter, give clearly marked '
    'examples, and distinguish optional fields. Do not substitute the general booking/payment journey. '
    'For a short factual question, give the requested fact before any necessary explanation. '
    'Do not restart at the calendar or list all payment steps unless the customer asks for the whole process. '
    'Do not invent the cause of a failure, an account state, a price, a feature, or an outcome. '
    'If essential information is missing, ask one question specific to that missing detail. '
    'Explain missing business facts specifically rather than returning a service-category menu.'
)


def scope_issue(question, reply):
    """Enforce a few concrete limits before trusting a model's quality verdict."""
    question = question.lower()
    detailed = bool(re.search(r'\b(form|fill|walkthrough|step.by.step|detail|compare|comparison)\b', question))
    if len(reply.split()) > (340 if detailed else 220):
        return 'The answer is too long for this request. Keep only the requested explanation and necessary steps.'
    if not re.search(r'\b(packages?|pricing|presyo|magkano|estimate|quotation)\b', question):
        if re.search(r'\bpackage\s+\d', reply, re.I):
            return 'The customer did not ask for a catalog or price estimate. Remove named package offers and amounts.'
    if not re.search(r'\b(prices?|pricing|presyo|magkano|cost|estimate|quotation|compare|comparison|difference|pagkakaiba)\b', question):
        if re.search(r'(?:\bPHP\s*|₱\s*)[\d,]+', reply, re.I):
            return 'The customer did not ask for a price estimate. Remove currency amounts and keep the requested explanation.'
    if re.search(r'\b(white|gold|silver)\b.{0,90}(?:do not count|does not count|don.t count|doesn.t count|without counting|not counted|free accent)', reply, re.I | re.S):
        return 'Every distinct balloon color counts toward the package limit, including white, gold and silver. No accent-color exemption is supported.'
    if re.search(r'\b(?:send|upload|submit|i-send|isend)\b.{0,100}\b(?:screenshot|proof|receipt)\b.{0,80}\b(?:messenger|instagram|facebook|gcash)\b', reply, re.I | re.S):
        return 'Do not invent a manual receipt/GCash-transfer process. Explain the enabled checkout and My Payments workflow.'
    return ''
