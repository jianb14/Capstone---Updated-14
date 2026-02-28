import re
import urllib.parse
from django.conf import settings
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
    keywords = ['picture', 'image', 'photo', 'design', 'gawa ka', 'draw', 'generate', 'show me', 'backdrop', 'balloon']
    # If it contains an image keyword AND is short enough to be a prompt, or explicitly asks for an image
    return any(kw in text for kw in keywords)

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
        system_prompt = (
            "You are the official AI assistant for 'Balloorina', a premium balloon decoration and event styling company in the Philippines. "
            "You MUST ONLY answer questions related to Balloorina's services: balloon decorations, backdrop designs, event styling, packages, bookings, and event planning. "
            "If a user asks about anything NOT related to Balloorina or event decoration (e.g. coding, math, general knowledge, other topics), "
            "politely decline and say: 'I can only assist with Balloorina event services and balloon decoration inquiries. How can I help with your event?' "
            "Keep your answers concise, elegant, and friendly. DO NOT use profanity or bad words ever. "
        )

        image_triggered = is_image_request(user_message)

        if image_triggered:
            system_prompt += (
                "The user wants a picture/design of a balloon decoration or event backdrop setup. "
                "IMPORTANT: You must describe a REAL EVENT DECORATION SETUP, NOT cartoon characters or illustrations. "
                "Think of actual balloon garlands, balloon arches, printed backdrop panels, number balloons, flower arrangements, chairs, and fairy lights — like a real party venue setup. "
                "If the user mentions a theme (e.g. Avengers, Disney, etc.), incorporate the theme through COLORS, PRINTED PANELS, and THEMED PROPS — NOT by drawing the actual characters. "
                "You MUST reply with exactly ONE highly descriptive image prompt wrapped in [PROMPT] and [/PROMPT] tags, along with a polite intro message. "
                "Always end the image prompt with: 'balloon decoration setup, event styling, real event photography, high quality' "
                "Example for Avengers theme: 'Here is a concept for your Avengers-themed backdrop: "
                "[PROMPT]elegant event backdrop with red blue and gold color scheme, large printed Avengers logo panel, "
                "organic balloon garland arch in red navy blue and gold balloons, scattered star balloons, "
                "white chair in center, LED number balloons, fairy lights, balloon decoration setup, event styling, real event photography, high quality[/PROMPT] "
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
                    generated_image = client.text_to_image(
                        prompt=img_prompt,
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
                    clean_reply += f'<img src="{img_url}" alt="{img_prompt}" '
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