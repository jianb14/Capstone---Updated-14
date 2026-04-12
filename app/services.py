import re
import urllib.parse
from django.conf import settings
from .models import Package, AddOn, AdditionalOnly
try:
    from huggingface_hub import InferenceClient
except ImportError:
    InferenceClient = None


# Strict profanity filter (English & Tagalog)
BAD_WORDS = [
    # English
    'fuck', 'fucking', 'fucked', 'fucker', 'fck', 'fuk',
    'shit', 'shitty', 'bullshit',
    'bitch', 'bitches',
    'asshole', 'ass',
    'cunt', 'dick', 'pussy', 'whore', 'slut', 'bastard',
    'motherfucker', 'mf', 'stfu', 'wtf', 'damn', 'dammit',
    'nigga', 'nigger', 'retard', 'retarded',
    # Tagalog
    'putangina', 'putangama', 'putanginamo', 'puta', 'tangina', 'tanginamo',
    'gago', 'gaga', 'gagong',
    'tanga', 'tangamo', 'tangang',
    'bobo', 'bobong',
    'inutil', 'tarantado', 'tarantada',
    'hayop', 'hayopka', 'ulol',
    'pota', 'potangina', 'pucha', 'puchang',
    'kantot', 'iyot', 'pokpok', 'malandi',
    'burat', 'pepe', 'puke', 'titi', 'tae', 'siraulo',
    'pakyu', 'pakyo', 'leche', 'lechekas', 'letse',
    'hinayupak', 'pesteng', 'punyeta', 'punyetang',
    'kupal', 'ogag', 'tangina',
]

def contains_profanity(text):
    """Strict profanity detection: checks both exact words AND substrings."""
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    words = cleaned.split()
    # Check exact word match
    if any(bad_word in words for bad_word in BAD_WORDS):
        return True
    # Check substring match (catches 'fuckoff', 'tangamo', etc.)
    joined = cleaned.replace(' ', '')
    return any(bad_word in joined for bad_word in BAD_WORDS)

def is_image_request(text):
    text = text.lower()
    keywords = [
        'picture', 'image', 'photo', 'design', 'gawa ka', 'draw', 'generate',
        'show me', 'backdrop', 'balloon', 'cartoon', 'anime', 'character',
        'themed', 'concept', 'gawa ng', 'pakita', 'igawa', 'lagay',
    ]
    # If it contains an image keyword AND is short enough to be a prompt, or explicitly asks for an image
    return any(kw in text for kw in keywords)

def get_system_context():
    """
    Fetches real-time data from the database and returns a comprehensive, 
    step-by-step instruction manual of the entire Balloorina system for the AI.
    """
    try:
        # Fetch Active Packages
        packages = Package.objects.filter(is_active=True)
        package_info = "AVAILABLE PACKAGES:\n"
        for p in packages:
            feats = ", ".join(p.feature_list()[:5])
            package_info += f"- {p.name}: ₱{p.price:,.2f} (Features: {feats})\n"

        # Fetch Active Add-ons
        addons = AddOn.objects.filter(is_active=True)
        addon_info = "AVAILABLE ADD-ONS:\n"
        for a in addons:
            solo_text = f", Solo Price: ₱{a.solo_price:,.2f}" if a.solo_price else ""
            addon_info += f"- {a.name}: ₱{a.price:,.2f} w/ package{solo_text}\n"
            
        # Fetch Active Additionals
        additionals = AdditionalOnly.objects.filter(is_active=True)
        additional_info = "ADDITIONAL ITEMS:\n"
        for a in additionals:
            additional_info += f"- {a.name}: ₱{a.price:,.2f}\n"

        # Construct the exhaustive manual
        system_rules = f"""
BALLOORINA SYSTEM MANUAL & KNOWLEDGE BASE
You are Balloorina's official AI assistant. You must ONLY provide factual information based on this manual. If a user asks a question not covered here, apologize and say you only know about Balloorina's services and system.

1. ABOUT BALLOORINA
Founded in 2020, Balloorina is Metro Manila's premier balloon styling and event decoration service.
- Mission: To transform ordinary spaces into extraordinary experiences.
- Core Values: Excellence, Creativity, Integrity, Customer Focus, Professionalism, Sustainability.

2. REAL-TIME OFFERS & PRICING
{package_info}
{addon_info}
{additional_info}

3. HOW TO BOOK (STEP-BY-STEP PROCESS)
Users must explicitly go to the "Booking" page in the navigation menu to start booking.
- STEP 0 (Calendar): The user views the Events Calendar (Blue=Confirmed, Yellow=Pending). They must click on an available Date (cannot be in the past).
- STEP 1 (Selection): A modal opens. The user chooses a main Package OR a solo Add-on. They can also add any regular Add-ons and Additional Items. The system calculates the total price, including a Service & Logistics Fee if applicable. They click "Next Step".
- STEP 2 (Event Details): The user fills out a form requiring: Event Type, Event Date, Start Time, End Time, Venue Address/Location, Special Requests, and an optional Reference Image. 
- SUBMIT: The user clicks "Submit Booking". The booking immediately falls into a "Pending" status and awaits Admin approval.

4. BOOKING STATUS & MANAGEMENT
- PENDING: The booking is successfully submitted but waiting for Admin review.
- CONFIRMED: The Admin approved the booking. At this point, the customer is expected to pay.
- COMPLETED: The event is finished.
- DENIED/CANCELLED: The booking was rejected or cancelled.

5. EDITING OR CANCELLING A BOOKING
Customers CANNOT edit or cancel confirmed bookings immediately. They must request permission via their Profile Dashboard.
- EDIT: Only "Confirmed" bookings can request an edit. The user clicks "Request Edit". Once the Admin approves the request, the user's dashboard will show an "Edit Booking" button allowing them to modify time/location/package.
- CANCEL: "Pending" or "Confirmed" bookings can request a cancellation. Once requested, the Admin must approve it to fully cancel the booking.

6. PAYMENTS
Balloorina accepts GCash, Credit/Debit Cards, and PayPal. Payment is typically negotiated or processed after a booking is CONFIRMED by the admin. 

7. ACCOUNTS & DASHBOARD
- Anyone can browse the site, but users must Register and Login (Customer role) to book.
- Customer Dashboard: After logging in, users click their Profile icon -> Dashboard. Here they can see all their Bookings, Request Edits/Cancels, and view Notifications.

8. INTERACTIVE FEATURES
- Design Canvas: A page where users can drag, drop, rotate, and resize items to visualize their event backdrop before booking.
- Reviews: After a booking is marked "COMPLETED", the user gets a notification allowing them to write a Review and rate the service (1-5 stars) on the Reviews page.

RULES FOR THE AI:
- When a user asks "How do I book", list out the explicit steps from section 3 clearly.
- When a user asks about canceling or editing, explain the request process in section 5.
- Always be polite, enthusiastic, and speak strictly from this knowledge base.
"""
        return system_rules
    except Exception as e:
        print(f"Error fetching system context: {e}")
        return "You are Balloorina's assistant. Provide helpful and factual answers."

def get_chatbot_response(user_message, conversation_history=None):
    """
    Sends a message to Hugging Face using the API.
    Handles profanity filtering and dynamic image generation using Pollinations AI.
    """
    try:
        # Pre-filter user input with strict profanity check
        if contains_profanity(user_message):
            return {
                'text': "<strong>⚠️ WARNING: INAPPROPRIATE LANGUAGE DETECTED</strong><br><br>"
                        "<span style='color:#fbbf24;'>Balloorina</span> maintains a <strong>strict policy</strong> against profanity and inappropriate language.<br><br>"
                        "🚫 Your message has been <strong>blocked</strong> and <strong>will not be processed</strong>.<br><br>"
                        "<em>Please keep our conversation respectful and professional. Continued violations may result in restricted access.</em>",
                'is_warning': True
            }

        if InferenceClient is None:
            print("Error: huggingface_hub library is not installed.")
            return {'text': "System Error: AI library missing. Please install huggingface_hub.", 'is_warning': False}
            
        if not hasattr(settings, 'HUGGINGFACE_API_KEY'):
            print("Error: HUGGINGFACE_API_KEY is not set in settings.py")
            return {'text': "Configuration Error: API Key missing.", 'is_warning': False}

        client = InferenceClient(token=settings.HUGGINGFACE_API_KEY)
        model_id = "Qwen/Qwen2.5-72B-Instruct"

        # Construct System Prompt
        base_prompt = (
            "You are the official AI assistant of Balloorina, a premium balloon decoration and event styling company in the Philippines. "
            "Only answer questions related to Balloorina’s services: balloon decorations, backdrop designs, event styling, event packages, bookings, and event planning."
            "If a user asks about anything NOT related to Balloorina or event decoration (e.g. coding, math, general knowledge, other topics), "
            "politely decline and say: 'I can only assist with Balloorina event services and balloon decoration inquiries. How can I help with your event?' "
            "Keep all responses short, direct, elegant, and friendly. Do not use profanity. "
            "ALWAYS base your answers about packages, prices, and booking rules on the exact SYSTEM CONTEXT below.\n\n"
        )
        
        system_context = get_system_context()
        
        system_prompt = base_prompt + system_context

        image_triggered = is_image_request(user_message)

        if image_triggered:
            system_prompt += (
                "The user wants a picture/design of a balloon decoration or event backdrop setup. "
                "You MUST create a WIDE SHOT, FULL EVENT BACKDROP setup. "
                "CRITICAL INSTRUCTION: DO NOT use the word 'arch' in your image prompt unless the user explicitly requests an entrance arch. Text-to-image models get confused by negative words, so NEVER mention 'no arch', 'without arch', or 'half-arch'. If no arch is requested, strictly use terms like 'balloon garlands', 'balloon clusters', 'cascading balloons', or 'organic balloon arrangements' only. "
                "The scene must be a wide center stage setup focusing on the main backdrop panels, balloon garlands spreading across the panels, "
                "number balloons, furniture/dessert table props, flower arrangements, and fairy lights. "
                "IMPORTANT: If the user mentions specific characters, cartoons, anime, or themes (e.g., Naruto, Avengers, Mickey Mouse, Hello Kitty, Frozen, Spider-Man, etc.), "
                "you MUST INCLUDE the ACTUAL characters or illustrations of those characters in the backdrop design. "
                "For example, if they ask for Naruto-themed, include Naruto character artwork/illustrations on the backdrop panels. "
                "If they ask for Disney, include the actual Disney characters. Do NOT just use colors — actually incorporate the characters visually. "
                "Combine the themed characters with elegant balloon decorations, garlands, and event styling elements. "
                "CRITICAL INSTRUCTION: You MUST reply with exactly ONE highly descriptive image prompt wrapped EXACTLY in [PROMPT] and [/PROMPT] tags, preceded by a polite intro message. "
                "EVEN IF the user's request is vague or general (e.g., 'give me an example'), YOU MUST INVENT A BEAUTIFUL THEME AND Output the [PROMPT] block. "
                "DO NOT ask the user for clarification. DO NOT output any bullet points, features list, or markdown. Your response should ONLY be a short intro sentence followed by the [PROMPT] block. "
                "Always start the image prompt with: WIDE SHOT, full event backdrop center stage, "
                "and end the image prompt with: wide event styling, luxury balloon decoration setup, high quality, detailed, vibrant colors. "
                "Example for Naruto anime theme: "
                "Here is a concept for your Naruto-themed backdrop: "
                "[PROMPT]WIDE SHOT, full event backdrop center stage featuring large Naruto character illustration on the center wooden panel, "
                "orange and black color scheme, kunai and shuriken decorative props on cylinders, "
                "massive organic balloon garland wrapping the panels in orange, black, and white balloons, "
                "Konoha leaf symbol printed on side panels, ninja-themed party decorations, "
                "fairy lights, wide event styling, luxury balloon decoration setup, high quality, detailed, vibrant colors[/PROMPT]"
                "Let me know if you want any changes!' "
            )

        messages = [
            {"role": "system", "content": system_prompt}
        ]

        if conversation_history:
            for msg in conversation_history:
                role = msg.get('role')
                content = msg.get('content')
                if content and role in ['user', 'assistant']:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        # Generate Response
        response = client.chat_completion(
            messages=messages,
            model=model_id,
            max_tokens=300,
            temperature=0.7,
        )
        
        reply_text = response.choices[0].message.content

        # Post-process for Image Generation
        if "[PROMPT]" in reply_text and "[/PROMPT]" in reply_text:
            # Extract prompt
            prompt_start = reply_text.find("[PROMPT]") + len("[PROMPT]")
            prompt_end = reply_text.find("[/PROMPT]")
            img_prompt = reply_text[prompt_start:prompt_end].strip()
            
            # Build the intro/outro text
            intro_text = reply_text[:reply_text.find("[PROMPT]")].strip()
            outro_text = reply_text[prompt_end + len("[/PROMPT]"):].strip()
            
            if image_triggered:
                # Generate image using HuggingFace Inference API
                try:
                    import os
                    import time
                    
                    image_model = "stabilityai/stable-diffusion-xl-base-1.0"
                    
                    user_wants_arch = any(word in user_message.lower() for word in ['arch', 'entrance', 'doorway', 'archway', 'banderitas'])
                    neg_prompt = "low quality, blurry, distorted, text, watermark, bad anatomy, bad lighting, cropped, out of frame"
                    if not user_wants_arch:
                        neg_prompt += ", entrance arch, doorway arch, full balloon arch, archway, upside-down U-shape arch, foreground arch, structural arch over stage"

                    generated_image = client.text_to_image(
                        prompt=img_prompt,
                        negative_prompt=neg_prompt,
                        model=image_model,
                    )
                    
                    # Save image to media/ai_generated/
                    ai_img_dir = os.path.join(settings.MEDIA_ROOT, 'ai_generated')
                    os.makedirs(ai_img_dir, exist_ok=True)
                    
                    filename = f"design_{int(time.time())}.png"
                    filepath = os.path.join(ai_img_dir, filename)
                    generated_image.save(filepath)
                    
                    # Build the media URL
                    img_url = f"{settings.MEDIA_URL}ai_generated/{filename}"
                    
                    clean_reply = f'{intro_text}<br><br>'
                    clean_reply += f'<img src="{img_url}" alt="Balloorina Design Concept" '
                    clean_reply += f'style="max-width:100%; border-radius:8px; margin-top:6px; box-shadow:0 4px 12px rgba(0,0,0,0.5);">'
                    if outro_text:
                        clean_reply += f'<br><br>{outro_text}'
                    
                    return {'text': clean_reply, 'is_warning': False}
                    
                except Exception as img_err:
                    print(f"Image Generation Error: {img_err}")
                    # Fallback: return text-only response if image generation fails
                    clean_reply = f'{intro_text}<br><br>'
                    clean_reply += f'<div style="padding:12px; background:#1a1a1a; border-radius:8px; border:1px solid #333;">⚠️ <em>Image generation is temporarily unavailable. Here\'s the design concept:</em><br><br><strong>{img_prompt}</strong></div>'
                    if outro_text:
                        clean_reply += f'<br><br>{outro_text}'
                    return {'text': clean_reply, 'is_warning': False}
            else:
                # If image not triggered but AI still output a prompt, strip it out.
                reply_text = f"{intro_text} {outro_text}".strip()

        return {'text': reply_text, 'is_warning': False}

    except Exception as e:
        print(f"Hugging Face Error: {e}")
        return {'text': "I'm sorry, I'm having trouble connecting to my service right now. Please try again later.", 'is_warning': False}

# EOF