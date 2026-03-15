import os

# =======================================================================
# PREMIUM ASSET GENERATOR — LINEAL COLOR ICON STYLE
# =======================================================================
# Style: Bold black outlines, flat solid color fill, small white
#        highlight dot, NO gradients, NO shadows, NO glow.
#        Matches the reference "Lineal Color" icon pack aesthetic.
# =======================================================================

BASE_DIR = os.path.join(os.path.dirname(__file__), 'static', 'images', 'canvas', 'premium')

# ---- Color Palette ----
COLORS = {
    'red': '#e63946',
    'blue': '#4895ef',
    'yellow': '#fee440',
    'green': '#06d6a0',
    'pink': '#ffb3c6',
    'purple': '#9d4edd',
    'orange': '#f77f00',
    'gold': '#ffb703',
    'silver': '#ced4da',
}

OUTLINE = '#222222'
STROKE_W = 1
HIGHLIGHT_OPACITY = 0.45

def create_svg(filename, w, h, content):
    """Writes a clean SVG file with the Lineal Color Icon style."""
    dir_path = os.path.join(BASE_DIR, os.path.dirname(filename))
    os.makedirs(dir_path, exist_ok=True)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}px" height="{h}px">
{content}
</svg>'''
    with open(os.path.join(BASE_DIR, filename), 'w') as f:
        f.write(svg)

def highlight(cx, cy, r=8):
    """Returns empty string as highlights have been removed from the style."""
    return ''

OL = f'stroke="{OUTLINE}" stroke-width="{STROKE_W}" stroke-linecap="round" stroke-linejoin="round"'

# ==========================================
# 1. FRAMES / STRUCTURES
# ==========================================
def create_frames():
    print("Generating frames...")
    cat = 'frames'
    frame_fill = '#ffb703'  # gold

    # Arch Frames
    create_svg(f'{cat}/round_arch.svg', 150, 150, f'<path d="M 20 140 A 55 55 0 0 1 130 140" fill="none" {OL}/>')
    create_svg(f'{cat}/half_arch.svg', 120, 150, f'<path d="M 100 140 L 100 60 A 60 60 0 0 0 20 60 L 20 140" fill="none" {OL}/>')
    create_svg(f'{cat}/spiral_arch.svg', 150, 150, f'<path d="M 20 140 A 55 55 0 0 1 130 140" fill="none" {OL}/><path d="M 30 140 A 45 45 0 0 1 120 140" fill="none" {OL}/>')
    create_svg(f'{cat}/organic_arch.svg', 150, 150, f'<path d="M 20 140 Q 50 20 75 10 Q 100 20 130 140" fill="none" {OL}/>')
    create_svg(f'{cat}/square_arch.svg', 150, 150, f'<path d="M 20 140 L 20 20 L 130 20 L 130 140" fill="none" {OL}/>')
    create_svg(f'{cat}/double_arch.svg', 150, 150, f'<path d="M 20 140 A 55 55 0 0 1 130 140" fill="none" {OL}/><path d="M 35 140 A 40 40 0 0 1 115 140" fill="none" {OL}/>')
    create_svg(f'{cat}/entrance_arch.svg', 150, 150, f'<path d="M 20 140 L 20 50 A 55 30 0 0 1 130 50 L 130 140" fill="none" {OL}/>')

    # Backdrop Frames
    create_svg(f'{cat}/round_backdrop.svg', 150, 150, f'<circle cx="75" cy="75" r="65" fill="{frame_fill}" {OL}/>{highlight(95, 40)}')
    create_svg(f'{cat}/square_backdrop.svg', 150, 150, f'<rect x="10" y="10" width="130" height="130" fill="{frame_fill}" {OL}/>{highlight(120, 30)}')
    create_svg(f'{cat}/rectangle_backdrop.svg', 120, 160, f'<rect x="10" y="10" width="100" height="140" fill="{frame_fill}" {OL}/>{highlight(90, 30)}')
    create_svg(f'{cat}/hexagon_backdrop.svg', 150, 150, f'<polygon points="75,10 135,40 135,110 75,140 15,110 15,40" fill="{frame_fill}" {OL}/>{highlight(110, 35)}')
    create_svg(f'{cat}/triangle_backdrop.svg', 150, 150, f'<polygon points="75,10 140,140 10,140" fill="{frame_fill}" {OL}/>{highlight(100, 50)}')

    # Grid / Wall
    grid_h = ''.join([f'<line x1="10" y1="{y}" x2="140" y2="{y}" {OL}/>' for y in range(30, 150, 30)])
    grid_v = ''.join([f'<line x1="{x}" y1="10" x2="{x}" y2="140" {OL}/>' for x in range(30, 150, 30)])
    create_svg(f'{cat}/grid_frame.svg', 150, 150, f'<rect x="10" y="10" width="130" height="130" fill="none" {OL}/>{grid_h}{grid_v}')
    create_svg(f'{cat}/balloon_wall_frame.svg', 150, 120, f'<rect x="10" y="10" width="130" height="100" fill="none" {OL}/>')

    # Number & Letter Frames
    def text_frame(name, text, w, h):
        create_svg(f'{cat}/{name}.svg', w, h, f'<text x="50%" y="55%" text-anchor="middle" dominant-baseline="central" font-family="Impact, Arial Black, sans-serif" font-size="{int(h*0.7)}" font-weight="bold" fill="{frame_fill}" {OL}>{text}</text>')

    for i in range(10):
        text_frame(f'number_{i}', str(i), 100, 130)
    for i in range(26):
        text_frame(f'letter_{chr(65+i)}', chr(65+i), 100, 130)
    text_frame('love_frame', 'LOVE', 280, 100)
    text_frame('baby_frame', 'BABY', 280, 100)
    text_frame('one_frame', 'ONE', 220, 100)

    # Stands
    create_svg(f'{cat}/balloon_stand_single.svg', 60, 150, f'<line x1="30" y1="20" x2="30" y2="130" {OL}/><rect x="15" y="130" width="30" height="10" rx="3" fill="{OUTLINE}" {OL}/>')
    create_svg(f'{cat}/ring_stand.svg', 150, 180, f'<circle cx="75" cy="70" r="55" fill="none" {OL}/><line x1="75" y1="125" x2="75" y2="165" {OL}/><rect x="50" y="165" width="50" height="8" rx="3" fill="{OUTLINE}" {OL}/>')


# ==========================================
# 2. BALLOONS — Lineal Color Icon
# ==========================================
def create_balloons():
    print("Generating balloons...")
    cat = 'balloons'
    blank_color = '#e0e0e0'

    # ---- Standard Normal Balloon (with tied string) ----
    create_svg(f'{cat}/standard_blank.svg', 100, 160,
        f'<ellipse cx="50" cy="65" rx="40" ry="50" fill="{blank_color}" {OL}/>'
        f'<path d="M 45 115 L 55 115 L 52 122 L 48 122 Z" fill="{blank_color}" {OL}/>'
        f'<path d="M 50 122 Q 40 135 55 145 Q 65 155 50 155" fill="none" {OL}/>'
        f'{highlight(70, 35, 8)}')

    # ---- Circle Balloon ----
    create_svg(f'{cat}/circle_blank.svg', 120, 120,
        f'<circle cx="60" cy="60" r="52" fill="{blank_color}" {OL}/>'
        f'{highlight(78, 35, 10)}')

    # ---- Star Balloon ----
    create_svg(f'{cat}/star_blank.svg', 130, 130,
        f'<polygon points="65,10 86,37 117,48 98,76 97,110 65,100 33,110 32,76 13,48 44,37" fill="{blank_color}" {OL}/>'
        f'{highlight(88, 35, 8)}')

    # ---- Heart Balloon ----
    create_svg(f'{cat}/heart_blank.svg', 130, 130,
        f'<path d="M 65 115 C 65 115 15 75 15 45 A 25 25 0 0 1 65 30 A 25 25 0 0 1 115 45 C 115 75 65 115 65 115 Z" fill="{blank_color}" {OL}/>'
        f'{highlight(88, 35, 8)}')

    # ---- Number Balloons (0-9) ----
    for i in range(10):
        create_svg(f'{cat}/number_{i}_blank.svg', 100, 105,
            f'<text x="50" y="95" font-family="Impact, Arial Black, sans-serif" font-size="100" font-weight="900" fill="{blank_color}" stroke="{OUTLINE}" stroke-width="{STROKE_W}" stroke-linejoin="round" text-anchor="middle">{i}</text>'
            f'<text x="47" y="92" font-family="Impact, Arial Black, sans-serif" font-size="100" font-weight="900" fill="none" stroke="#ffffff" stroke-width="1" stroke-dasharray="10, 15" text-anchor="middle" opacity="0.6">{i}</text>'
        )

    # ---- Letter Balloons (A-Z) ----
    for i in range(26):
        letter = chr(65 + i)
        create_svg(f'{cat}/letter_{letter}_blank.svg', 100, 105,
            f'<text x="50" y="95" font-family="Impact, Arial Black, sans-serif" font-size="100" font-weight="900" fill="{blank_color}" stroke="{OUTLINE}" stroke-width="{STROKE_W}" stroke-linejoin="round" text-anchor="middle">{letter}</text>'
            f'<text x="47" y="92" font-family="Impact, Arial Black, sans-serif" font-size="100" font-weight="900" fill="none" stroke="#ffffff" stroke-width="1" stroke-dasharray="10, 15" text-anchor="middle" opacity="0.6">{letter}</text>'
        )

    # Garland
    create_svg(f'{cat}/balloon_garland.svg', 250, 200,
        f'<circle cx="35" cy="170" r="28" fill="{COLORS["red"]}" {OL}/>'
        f'<circle cx="70" cy="130" r="32" fill="{COLORS["blue"]}" {OL}/>'
        f'<circle cx="115" cy="95" r="35" fill="{COLORS["gold"]}" {OL}/>'
        f'<circle cx="160" cy="70" r="30" fill="{COLORS["pink"]}" {OL}/>'
        f'<circle cx="200" cy="50" r="25" fill="{COLORS["green"]}" {OL}/>'
        f'<circle cx="55" cy="155" r="12" fill="{COLORS["yellow"]}" {OL}/>'
        f'<circle cx="140" cy="80" r="14" fill="{COLORS["purple"]}" {OL}/>')

    # Bouquet
    create_svg(f'{cat}/balloon_bouquet.svg', 130, 180,
        f'<line x1="65" y1="130" x2="55" y2="175" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<line x1="65" y1="130" x2="65" y2="175" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<line x1="65" y1="130" x2="75" y2="175" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<circle cx="45" cy="105" r="25" fill="{COLORS["pink"]}" {OL}/>'
        f'<circle cx="85" cy="105" r="25" fill="{COLORS["blue"]}" {OL}/>'
        f'<circle cx="65" cy="75" r="28" fill="{COLORS["gold"]}" {OL}/>')


# ==========================================
# 3. DECORATIONS
# ==========================================
def create_decorations():
    print("Generating decorations...")
    cat = 'decorations'

    # Flower
    def make_flower(name, petal_color, center_color):
        create_svg(f'{cat}/{name}.svg', 120, 120,
            f'<circle cx="60" cy="35" r="22" fill="{petal_color}" {OL}/>'
            f'<circle cx="35" cy="60" r="22" fill="{petal_color}" {OL}/>'
            f'<circle cx="85" cy="60" r="22" fill="{petal_color}" {OL}/>'
            f'<circle cx="45" cy="85" r="22" fill="{petal_color}" {OL}/>'
            f'<circle cx="75" cy="85" r="22" fill="{petal_color}" {OL}/>'
            f'<circle cx="60" cy="60" r="15" fill="{center_color}" {OL}/>'
            f'{highlight(68, 52, 5)}')

    make_flower('flower_pink', '#ffb3c6', '#fee440')
    make_flower('flower_blue', '#a2d2ff', '#fee440')
    make_flower('flower_red', '#e63946', '#ffb703')

    # Greenery Fern
    create_svg(f'{cat}/greenery_fern.svg', 100, 140,
        f'<path d="M 50 130 Q 50 70 25 15" fill="none" stroke="#06d6a0" stroke-width="5" stroke-linecap="round"/>'
        f'<path d="M 50 100 Q 70 80 85 50" fill="none" stroke="#06d6a0" stroke-width="4" stroke-linecap="round"/>'
        f'<path d="M 50 80 Q 30 60 15 40" fill="none" stroke="#06d6a0" stroke-width="4" stroke-linecap="round"/>'
        f'<path d="M 50 60 Q 75 45 90 25" fill="none" stroke="#06d6a0" stroke-width="3" stroke-linecap="round"/>')

    # Giant Bow
    def make_bow(name, color):
        create_svg(f'{cat}/{name}.svg', 130, 100,
            f'<path d="M 65 50 Q 10 5 10 50 Q 10 95 65 50 Z" fill="{color}" {OL}/>'
            f'<path d="M 65 50 Q 120 5 120 50 Q 120 95 65 50 Z" fill="{color}" {OL}/>'
            f'<ellipse cx="65" cy="50" rx="12" ry="15" fill="{color}" {OL}/>'
            f'{highlight(45, 28, 6)}')
    make_bow('bow_pink', '#ffb3c6')
    make_bow('bow_blue', '#a2d2ff')
    make_bow('bow_gold', '#ffb703')

    # Globe String Lights
    create_svg(f'{cat}/string_lights.svg', 200, 80,
        f'<path d="M 10 15 Q 100 55 190 15" fill="none" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<circle cx="40" cy="30" r="10" fill="#fee440" {OL}/>'
        f'<circle cx="80" cy="42" r="10" fill="#fee440" {OL}/>'
        f'<circle cx="120" cy="45" r="10" fill="#fee440" {OL}/>'
        f'<circle cx="160" cy="35" r="10" fill="#fee440" {OL}/>')

    # Teepee Tent
    create_svg(f'{cat}/teepee_tent.svg', 140, 160,
        f'<polygon points="70,10 130,150 10,150" fill="#faf0e6" {OL}/>'
        f'<line x1="70" y1="3" x2="55" y2="10" stroke="#8b5a2b" stroke-width="4" stroke-linecap="round"/>'
        f'<line x1="70" y1="3" x2="85" y2="10" stroke="#8b5a2b" stroke-width="4" stroke-linecap="round"/>'
        f'<path d="M 55 150 L 55 100 Q 70 85 85 100 L 85 150" fill="#d4a373" {OL}/>'
        f'{highlight(55, 45, 8)}')


# ==========================================
# 4. FURNITURE
# ==========================================
def create_furniture():
    print("Generating furniture...")
    cat = 'furniture'

    # Plinth
    def make_plinth(name, color):
        create_svg(f'{cat}/{name}.svg', 80, 140,
            f'<ellipse cx="40" cy="20" rx="30" ry="12" fill="{color}" {OL}/>'
            f'<rect x="10" y="20" width="60" height="100" fill="{color}" {OL}/>'
            f'<ellipse cx="40" cy="120" rx="30" ry="12" fill="{color}" {OL}/>'
            f'{highlight(55, 30, 6)}')
    make_plinth('plinth_white', '#f8f9fa')
    make_plinth('plinth_pink', '#ffb3c6')
    make_plinth('plinth_gold', '#ffb703')

    # Ghost Chair
    create_svg(f'{cat}/ghost_chair.svg', 100, 130,
        f'<rect x="25" y="10" width="50" height="55" rx="12" fill="none" stroke="{OUTLINE}" stroke-width="2" stroke-dasharray="4,2"/>'
        f'<ellipse cx="50" cy="70" rx="32" ry="8" fill="none" stroke="{OUTLINE}" stroke-width="2" stroke-dasharray="4,2"/>'
        f'<line x1="25" y1="72" x2="20" y2="120" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<line x1="75" y1="72" x2="80" y2="120" stroke="{OUTLINE}" stroke-width="2"/>')

    # Velvet Chair
    create_svg(f'{cat}/velvet_chair.svg', 110, 140,
        f'<path d="M 20 15 Q 55 0 90 15 L 95 90 L 15 90 Z" fill="#ffb3c6" {OL}/>'
        f'<rect x="10" y="90" width="90" height="20" rx="5" fill="#ff8fab" {OL}/>'
        f'<line x1="25" y1="110" x2="22" y2="135" stroke="#ffb703" stroke-width="5" stroke-linecap="round"/>'
        f'<line x1="85" y1="110" x2="88" y2="135" stroke="#ffb703" stroke-width="5" stroke-linecap="round"/>'
        f'{highlight(65, 35, 6)}')

    # Wooden Bench
    create_svg(f'{cat}/wooden_bench.svg', 150, 90,
        f'<rect x="10" y="30" width="130" height="12" rx="2" fill="#d4a373" {OL}/>'
        f'<rect x="10" y="45" width="130" height="12" rx="2" fill="#d4a373" {OL}/>'
        f'<rect x="20" y="57" width="12" height="25" fill="#8b5a2b" {OL}/>'
        f'<rect x="118" y="57" width="12" height="25" fill="#8b5a2b" {OL}/>'
        f'{highlight(120, 35, 5)}')

    # Wooden Crate
    create_svg(f'{cat}/wooden_crate.svg', 120, 90,
        f'<rect x="10" y="10" width="100" height="70" fill="#d4a373" {OL}/>'
        f'<line x1="10" y1="30" x2="110" y2="30" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<line x1="10" y1="50" x2="110" y2="50" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<rect x="15" y="10" width="15" height="70" fill="#faedcd" {OL}/>'
        f'<rect x="90" y="10" width="15" height="70" fill="#faedcd" {OL}/>'
        f'{highlight(75, 20, 5)}')

    # Easel
    create_svg(f'{cat}/easel.svg', 80, 140,
        f'<line x1="40" y1="10" x2="15" y2="130" stroke="#8b5a2b" stroke-width="5" stroke-linecap="round"/>'
        f'<line x1="40" y1="10" x2="65" y2="130" stroke="#8b5a2b" stroke-width="5" stroke-linecap="round"/>'
        f'<line x1="40" y1="10" x2="40" y2="125" stroke="#5c3a21" stroke-width="4" stroke-linecap="round"/>'
        f'<rect x="8" y="90" width="64" height="6" rx="2" fill="#b08968" {OL}/>')

    # Ladder Shelf
    create_svg(f'{cat}/ladder_shelf.svg', 100, 160,
        f'<line x1="30" y1="5" x2="15" y2="155" stroke="#f8f9fa" stroke-width="5" stroke-linecap="round"/>'
        f'<line x1="70" y1="5" x2="85" y2="155" stroke="#f8f9fa" stroke-width="5" stroke-linecap="round"/>'
        f'<rect x="22" y="35" width="56" height="6" fill="#f8f9fa" {OL}/>'
        f'<rect x="20" y="70" width="60" height="6" fill="#f8f9fa" {OL}/>'
        f'<rect x="18" y="105" width="64" height="6" fill="#f8f9fa" {OL}/>')


# ==========================================
# 5. PARTY ITEMS
# ==========================================
def create_party_items():
    print("Generating party items...")
    cat = 'party'

    # Cake
    create_svg(f'{cat}/cake.svg', 120, 150,
        f'<rect x="30" y="60" width="60" height="40" rx="3" fill="#ffccd5" {OL}/>'
        f'<rect x="38" y="30" width="44" height="30" rx="3" fill="#ffb3c6" {OL}/>'
        f'<ellipse cx="60" cy="60" rx="30" ry="5" fill="#ff8fab" {OL}/>'
        f'<ellipse cx="60" cy="30" rx="22" ry="4" fill="#ffe5ec" {OL}/>'
        f'<rect x="58" y="10" width="4" height="20" fill="#ffc8dd" {OL}/>'
        f'<circle cx="60" cy="8" r="4" fill="#ffb703" {OL}/>'
        f'<path d="M 25 100 C 25 115 95 115 95 100" fill="#ced4da" {OL}/>'
        f'<rect x="40" y="100" width="40" height="8" fill="#ced4da" {OL}/>'
        f'<rect x="35" y="108" width="50" height="6" fill="#ced4da" {OL}/>'
        f'{highlight(75, 40, 5)}')

    # Gift Box
    create_svg(f'{cat}/gift_box.svg', 100, 100,
        f'<rect x="15" y="35" width="70" height="55" fill="#4895ef" {OL}/>'
        f'<rect x="10" y="25" width="80" height="14" rx="2" fill="#023e8a" {OL}/>'
        f'<rect x="45" y="25" width="10" height="65" fill="#ffb703" {OL}/>'
        f'<path d="M 50 25 Q 35 8 42 25" fill="#ffb703" {OL}/>'
        f'<path d="M 50 25 Q 65 8 58 25" fill="#ffb703" {OL}/>'
        f'{highlight(70, 40, 5)}')

    # Alphabet Blocks
    def make_block(letter, color):
        create_svg(f'{cat}/block_{letter}.svg', 90, 90,
            f'<rect x="10" y="20" width="60" height="60" fill="{color}" {OL}/>'
            f'<polygon points="15,15 65,15 70,20 10,20" fill="{color}" {OL} fill-opacity="0.7"/>'
            f'<polygon points="70,20 65,15 65,70 70,80" fill="#000" {OL} fill-opacity="0.1"/>'
            f'<text x="40" y="58" font-family="Arial, sans-serif" font-size="35" font-weight="bold" fill="#ffffff" text-anchor="middle" dominant-baseline="central">{letter}</text>')
    make_block('A', '#e63946')
    make_block('B', '#fee440')
    make_block('C', '#06d6a0')

    # Safari Standees
    create_svg(f'{cat}/standee_lion.svg', 120, 150,
        f'<circle cx="60" cy="55" r="38" fill="#e07a5f" {OL}/>'
        f'<circle cx="60" cy="55" r="26" fill="#f4a261" {OL}/>'
        f'<circle cx="52" cy="48" r="4" fill="{OUTLINE}"/>'
        f'<circle cx="68" cy="48" r="4" fill="{OUTLINE}"/>'
        f'<ellipse cx="60" cy="60" rx="7" ry="4" fill="#2a9d8f" {OL}/>'
        f'<path d="M 40 88 Q 60 78 80 88 L 85 140 L 35 140 Z" fill="#f4a261" {OL}/>'
        f'<rect x="30" y="140" width="60" height="5" fill="#ced4da" {OL}/>'
        f'{highlight(75, 30, 5)}')

    create_svg(f'{cat}/standee_giraffe.svg', 110, 170,
        f'<ellipse cx="55" cy="30" rx="14" ry="22" fill="#e9c46a" {OL}/>'
        f'<path d="M 44 48 L 40 110 L 70 110 L 66 48 Z" fill="#e9c46a" {OL}/>'
        f'<circle cx="52" cy="65" r="3" fill="#8b5a2b"/>'
        f'<circle cx="58" cy="85" r="4" fill="#8b5a2b"/>'
        f'<path d="M 35 110 Q 55 95 75 110 L 80 160 L 30 160 Z" fill="#e9c46a" {OL}/>'
        f'<rect x="22" y="160" width="66" height="5" fill="#ced4da" {OL}/>'
        f'{highlight(65, 22, 4)}')


# ==========================================
# 6. THEME OBJECTS
# ==========================================
def create_theme_objects():
    print("Generating themes...")
    cat = 'themes'

    # Teddy Bear
    create_svg(f'{cat}/teddy_bear.svg', 120, 150,
        f'<circle cx="40" cy="35" r="16" fill="#d4a373" {OL}/>'
        f'<circle cx="80" cy="35" r="16" fill="#d4a373" {OL}/>'
        f'<circle cx="60" cy="55" r="30" fill="#faedcd" {OL}/>'
        f'<ellipse cx="60" cy="105" rx="35" ry="38" fill="#d4a373" {OL}/>'
        f'<circle cx="53" cy="50" r="3" fill="{OUTLINE}"/>'
        f'<circle cx="67" cy="50" r="3" fill="{OUTLINE}"/>'
        f'<circle cx="60" cy="58" r="4" fill="{OUTLINE}"/>'
        f'{highlight(75, 30, 5)}')

    # Rainbow
    create_svg(f'{cat}/rainbow.svg', 160, 100,
        f'<path d="M 15 85 A 65 65 0 0 1 145 85" fill="none" stroke="#e63946" stroke-width="10" stroke-linecap="round"/>'
        f'<path d="M 25 85 A 55 55 0 0 1 135 85" fill="none" stroke="#fee440" stroke-width="10" stroke-linecap="round"/>'
        f'<path d="M 35 85 A 45 45 0 0 1 125 85" fill="none" stroke="#06d6a0" stroke-width="10" stroke-linecap="round"/>'
        f'<path d="M 45 85 A 35 35 0 0 1 115 85" fill="none" stroke="#4895ef" stroke-width="10" stroke-linecap="round"/>')

    # Hot Air Balloon
    create_svg(f'{cat}/hot_air_balloon.svg', 120, 160,
        f'<ellipse cx="60" cy="55" rx="42" ry="50" fill="#ffb3c6" {OL}/>'
        f'<path d="M 35 55 A 25 50 0 0 1 85 55" fill="none" stroke="#fff" stroke-width="2" opacity="0.5"/>'
        f'<line x1="40" y1="98" x2="45" y2="125" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<line x1="80" y1="98" x2="75" y2="125" stroke="{OUTLINE}" stroke-width="2"/>'
        f'<rect x="45" y="125" width="30" height="22" rx="2" fill="#8b5a2b" {OL}/>'
        f'{highlight(78, 30, 8)}')

    # Street Lamp
    create_svg(f'{cat}/street_lamp.svg', 70, 170,
        f'<rect x="32" y="45" width="6" height="115" fill="#343a40" {OL}/>'
        f'<rect x="25" y="158" width="20" height="8" rx="2" fill="{OUTLINE}" {OL}/>'
        f'<polygon points="15,40 55,40 35,15" fill="#343a40" {OL}/>'
        f'<circle cx="35" cy="38" r="12" fill="#fee440" {OL}/>'
        f'{highlight(40, 30, 4)}')


# ==========================================
# 7. TEXT & SIGNS
# ==========================================
def create_texts_signs():
    print("Generating text signs...")
    cat = 'texts'

    # Neon Signs
    def make_neon(name, text, glow_color):
        create_svg(f'{cat}/{name}.svg', 200, 80,
            f'<rect x="5" y="5" width="190" height="70" rx="8" fill="#1a1a2e" {OL}/>'
            f'<text x="100" y="48" font-family="\'Brush Script MT\', cursive, sans-serif" font-size="28" font-style="italic" font-weight="bold" fill="{glow_color}" text-anchor="middle" dominant-baseline="central">{text}</text>')

    make_neon('neon_happy_birthday', 'Happy Birthday', '#ff69b4')
    make_neon('neon_oh_baby', 'Oh Baby', '#00f5d4')
    make_neon('neon_lets_party', "Let's Party", '#fee440')

    # Marquee 1
    create_svg(f'{cat}/marquee_1.svg', 80, 140,
        f'<path d="M 22 40 L 40 15 L 55 15 L 55 120 L 25 120" fill="#f8f9fa" {OL}/>'
        f'<line x1="20" y1="120" x2="65" y2="120" stroke="{OUTLINE}" stroke-width="{STROKE_W}"/>'
        f'<circle cx="45" cy="35" r="4" fill="#fee440" {OL}/>'
        f'<circle cx="45" cy="55" r="4" fill="#fee440" {OL}/>'
        f'<circle cx="45" cy="75" r="4" fill="#fee440" {OL}/>'
        f'<circle cx="45" cy="95" r="4" fill="#fee440" {OL}/>'
        f'<circle cx="45" cy="112" r="4" fill="#fee440" {OL}/>')

    # Acrylic Board
    create_svg(f'{cat}/acrylic_board.svg', 120, 155,
        f'<rect x="15" y="15" width="90" height="125" rx="8" fill="rgba(255,255,255,0.6)" stroke="#d4af37" stroke-width="{STROKE_W}"/>'
        f'<text x="60" y="55" font-family="\'Brush Script MT\', cursive" font-size="16" font-weight="bold" fill="#333" text-anchor="middle">Welcome to</text>'
        f'<text x="60" y="85" font-family="Arial" font-size="12" font-weight="bold" fill="#333" text-anchor="middle">OUR EVENT</text>')


# ==========================================
# RUN ALL
# ==========================================
if __name__ == '__main__':
    create_frames()
    create_balloons()
    create_decorations()
    create_furniture()
    create_party_items()
    create_theme_objects()
    create_texts_signs()
    print("Done generating premium Lineal Color Icon assets!")
