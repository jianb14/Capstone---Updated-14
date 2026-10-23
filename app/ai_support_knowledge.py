"""Customer help facts checked against the form, design controls and policies."""
import re

BOOKING_FORM_GUIDE = (
    'Booking Form Field Guide (customer booking page): Event Details contains required Event Type, '
    'Event Date, Event Duration (Start and End), and Location (Venue Address). '
    'Choose the real occasion in Event Type; select Other and specify it when needed. '
    'Use an available Event Date. Start is the event start time, End is its finish time; obey the configured duration rules. '
    'For Location (Venue Address), search/select the actual venue, barangay or city, then check and adjust the map pin. '
    'Nearest landmark / gate / floor is optional arrival guidance, not a replacement for the venue address. '
    'Next Step opens Design Preferences: Theme / Decor Style and Color Palette are required. '
    'Choose a theme chip or Other and type the theme. Pick one to three colors in Color Palette, '
    'while respecting any stricter color limit of the selected package. '
    'Motto / Text on the Backdrop is optional exact wording for signage. '
    'Design Notes / Special Requests are optional instructions. Add Reference Pictures is optional, '
    'with up to four pictures in total; Browse Files selects photos and previews them. '
    'Next Step opens Review & Confirm. Review event details, preferences, package, extras, logistics, overtime and total before submitting. '
    'Submission requests admin approval; it does not itself confirm the booking or verify payment. '
    'When teaching how to fill the form, explain these fields with illustrative values; do not ask customers '
    'to enter nonexistent fields such as number of guests or payment card details into Event Details.'
)

DESIGN_HELP_GUIDE = (
    'Design guide and saved-design help: The AI chat header has Design guide and Sample description. '
    'The guide asks for the occasion, optional theme/colors, optional name/milestone text, then a review before Generate design. '
    'Help me choose shows three curated theme/palette suggestions from a larger occasion-specific set. '
    'The same button changes its label to Show more ideas; clicking it changes the three displayed choices. '
    'This control selects predefined style options; it does not generate images or list canvas assets. '
    'Selecting one fills the theme and colors. '
    'Clear answers clears the device guide draft; Clear saved details clears the current chat\'s server design preferences. '
    'Edit this design in an AI image\'s action row selects that owned image for a requested edit. '
    'AI images are visual concepts; active Gallery photos are actual setups and are labeled Actual setup. '
    'For My Designs, Draft means required package items are missing. Continue Editing opens the canvas; '
    'follow the missing-item list and use the matching canvas assets. Uploaded reference photos do not count '
    'toward required package items. A design marked Ready to book has met the current requirements; '
    'that label does not mean a booking has been approved or paid. My Designs has a Download action. '
    'The canvas Save Design dialog saves a named design. A physical event design uploaded by the team '
    'appears under Your Event Design and has View full size and Download Design actions.'
)


def focused_support_facts(question, actions):
    """Keep unrelated UI flows/catalogs out of a specific support answer."""
    text = question.lower()
    sections, compatible = [], set()
    if re.search(r'\b(payment|payments|gcash|paymaya|pay|bayad|magbayad|nagbayad|checkout)\b', text):
        from django.conf import settings
        from .models import GCashConfig
        config = GCashConfig.objects.first()
        sections.append('Payment help. GCash through online checkout is the enabled payment method. '
            +('Online checkout is currently configured. ' if settings.PAYMONGO_SECRET_KEY else 'Online checkout is currently unavailable. ')
            +'Open My Payments, select the booking and follow its checkout instructions. Initial payment options are '
            'downpayment or full payment; balance payment follows an initial verified payment. '
            +(f'The configured downpayment is {config.downpayment_percent}%. ' if config else '')
            +'A payment marked pending is not verified. The booking status pending_payment is a DIFFERENT field, '
            'meaning the booking was approved and awaits payment; never equate these two statuses. '
            'A pending payment alone does not prove that funds were received. Check My Payments and the GCash transaction '
            'before retrying; if funds were already received and await review, do not pay again. '
            'Do not guarantee that another charge cannot happen, a fixed verification deadline, or that no balance remains. '
            'No manual personal-number GCash transfer or social-media receipt submission is documented as the enabled checkout flow. '
            'The assistant cannot verify a payment or change a booking. Use only supplied account records to report account status.')
        compatible.update({'payment_help', 'payment_status', 'booking_status'})
    if re.search(r'\b(my designs|canvas|draft|missing items|missing assets|continue editing)\b', text):
        sections.append(DESIGN_HELP_GUIDE+(
            ' Important: Canvas missing items are asset quantities required by the selected package. '
            'Filling the booking form\'s Event Type/Theme/Color Palette does not satisfy missing canvas assets.'))
        compatible.add('packages')
    elif re.search(r'\b(design guide|help me choose|show more ideas|sample description)\b', text):
        sections.append(DESIGN_HELP_GUIDE)
    if re.search(r'\b(forms?|fill|filling|fields?|venue|landmark|address|location|event details|design preferences)\b', text):
        sections.append(BOOKING_FORM_GUIDE+(
            ' Explain the requested form section; do not repeat date/package selection or payment steps unless explicitly requested. '
            +event_time_facts()))
        compatible.add('packages')
    if re.search(r'\b(mean|meaning|ibig sabihin)\b', text) and re.search(r'\b(colors?|colours?|kulay)\b', text):
        sections.append('Maximum balloon colors means the number of distinct balloon colors allowed by the selected package. '
            'Every distinct balloon color counts, including white, gold and silver. There is no free accent-color exemption. '
            'For example, a two-color limit permits blue and white; adding gold would be a third color. '
            'Explain the limit; do not enumerate all packages or recommend purchases unless asked.')
        compatible.add('packages')
    if sections:
        return '\n\n'.join(sections), compatible
    if 'booking_status' in actions:
        return ('Booking status definitions: pending = request awaiting admin approval; pending_payment = approved booking '
            'awaiting the required payment; confirmed = reservation confirmed after payment verification; completed = finished event. '
            'Submitting a form does not confirm a booking. Do not infer why a particular record has a status without evidence. '
            +runtime_policy_facts()), {'booking_status'}
    if set(actions) == {'booking_help'}:
        return BOOKING_FORM_GUIDE+event_time_facts(), {'booking_help', 'packages'}
    return '', set(actions)


def event_time_facts():
    from .models import SiteSettings
    policy = SiteSettings.objects.first()
    def current(field):
        return getattr(policy, field) if policy else SiteSettings._meta.get_field(field).get_default()
    return (' Event start must be at or after 7 AM and strictly BEFORE 6 PM. '
        f'Minimum duration: {current("booking_min_duration_hours")} hours; '
        f'maximum: {current("booking_max_duration_hours")} hours; '
        f'included: {current("booking_included_hours")} hours. '
        'End times may be later or overnight within those limits.')


def runtime_policy_facts():
    from .models import SiteSettings
    policy = SiteSettings.objects.first()
    def current(field):
        return getattr(policy, field) if policy else SiteSettings._meta.get_field(field).get_default()
    return (
        'CURRENT RUNTIME POLICIES (override older descriptions): '
        f'Minimum booking notice: {current("booking_lead_time_days")} day(s). '
        f'Minimum event duration: {current("booking_min_duration_hours")} hour(s); '
        f'included duration: {current("booking_included_hours")} hour(s); '
        f'maximum duration: {current("booking_max_duration_hours")} hour(s); '
        f'overtime rate: PHP {current("booking_overtime_rate")} per extra hour or fraction. '
        f'Initial payment window after approval: {current("booking_payment_window_hours")} hour(s), capped at event start. '
        'Submitted/received payments awaiting review must not be treated as unsubmitted payments or automatically charged again. '
        'A pending payment is not verified. Do not invent why a particular payment failed or guarantee a verification time. '
        'The enabled online flow is GCash through checkout, tracked in My Payments. Do not instruct customers '
        'to transfer money to a personal GCash number or send receipts through social media as an invented payment workflow. '
        'Customers can directly edit a pending booking. Approved (pending_payment) or confirmed bookings '
        'can use a separate Request changes flow, subject to eligibility, team review, a quote and any required additional payment. '
        f'Change requests within {current("booking_change_cutoff_hours")} hours of the event need direct team assistance. '
        'Only one active change request is allowed for a booking. Do not claim a requested change is already applied. '
        'The assistant reads facts and gives instructions; it cannot submit forms, verify payments, '
        'cancel or reschedule a booking on behalf of the customer.'
    )
