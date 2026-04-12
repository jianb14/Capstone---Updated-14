import os
import re

html_path = 'app/templates/client/design_canvas.html'

with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

colors = {
    'red': 'Red', 'blue': 'Blue', 'yellow': 'Yellow', 'green': 'Green',
    'pink': 'Pink', 'purple': 'Purple', 'orange': 'Orange',
    'gold': 'Gold', 'silver': 'Silver'
}

def item(src, label, w, h):
    return f"                    {{% include 'components/canvas_item.html' with type='image' src='images/canvas/premium/{src}' label='{label}' width='{w}' height='{h}' %}}\n"

def sub_label(text):
    return f'                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">{text}</div>\n'

def items_open(content_str):
    return f'                <div class="category-items" style="gap: 5px;">\n{content_str}                </div>\n'

# ========== Build balloons section ==========
b = ''

# Shapes
inner = sub_label('Balloon Shapes')
inner += item(f'balloons/standard_blank.svg', f'Normal', 70, 110)
inner += item(f'balloons/circle_blank.svg', f'Circle', 80, 80)
inner += item(f'balloons/star_blank.svg', f'Star', 80, 80)
inner += item(f'balloons/heart_blank.svg', f'Heart', 80, 80)
b += items_open(inner)

# Numbers
inner = sub_label('Number Balloons (0-9)')
for i in range(10):
    inner += item(f'balloons/number_{i}_blank.svg', f'Num {i}', 80, 80)
b += items_open(inner)

# Letters
inner = sub_label('Letter Balloons (A-Z)')
for i in range(26):
    letter = chr(65 + i)
    inner += item(f'balloons/letter_{letter}_blank.svg', f'Let {letter}', 80, 80)
b += items_open(inner)

# Flower Balloons
inner = sub_label('Flower Balloons')
inner += item('balloons/flower_daisy_blank.svg', 'Daisy', 80, 80)
inner += item('balloons/flower_rose_blank.svg', 'Rose', 80, 80)
inner += item('balloons/flower_tulip_blank.svg', 'Tulip', 70, 80)
b += items_open(inner)

# Specialty Balloons
inner = sub_label('Specialty Balloons')
inner += item('balloons/jumbo_blank.svg', 'Jumbo', 80, 110)
inner += item('balloons/giant_blank.svg', 'Giant', 90, 130)
inner += item('balloons/square_blank.svg', 'Square Foil', 80, 80)
b += items_open(inner)

# Celestial & Weather
inner = sub_label('Celestial & Weather')
inner += item('balloons/sun_blank.svg', 'Sun', 80, 80)
inner += item('balloons/moon_blank.svg', 'Moon', 70, 80)
inner += item('balloons/lightning_blank.svg', 'Lightning', 60, 90)
b += items_open(inner)

# Bundles
inner = sub_label('Bundles')
inner += item('balloons/balloon_garland.svg', 'Garland', 200, 150)
inner += item('balloons/balloon_bouquet.svg', 'Bouquet', 100, 140)
b += items_open(inner)

balloon_html = f'''            <!-- ====== 2. BALLOONS ====== -->
            <div class="inventory-category">
                <div class="category-header" onclick="toggleCategory(this)">
                    <span>Balloons</span>
                    <i class="fas fa-chevron-down chevron"></i>
                </div>
{b}            </div>

'''

# Replace in content
pattern = re.compile(
    r'<!-- ====== 2\. BALLOONS ====== -->.*?</div>\s*</div>\s*(?=\s*<!-- ====== 3\. DECORATIONS)',
    re.DOTALL
)
# Also need to handle duplicate comment if present
content = re.sub(r'<!-- ====== 3\. DECORATIONS ====== -->\s*<!-- ====== 3\. DECORATIONS ====== -->', '<!-- ====== 3. DECORATIONS ====== -->', content)
new_content = re.sub(pattern, balloon_html, content)

# Now rebuild decorations, furniture, party, themes, texts sections too
dec = '''            <!-- ====== 3. DECORATIONS ====== -->
            <div class="inventory-category">
                <div class="category-header" onclick="toggleCategory(this)">
                    <span>Decorations</span>
                    <i class="fas fa-chevron-down chevron"></i>
                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Florals</div>
''' + item('decorations/flower_pink.svg', 'Pink Flower', 80, 80) + item('decorations/flower_blue.svg', 'Blue Flower', 80, 80) + item('decorations/flower_red.svg', 'Red Flower', 80, 80) + item('decorations/greenery_fern.svg', 'Fern', 70, 100) + '''                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Marquee LED Numbers</div>
''' + ''.join([item(f'decorations/marquee_number_{i}.svg', f'Num {i}', 70, 90) for i in range(10)]) + '''                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Accents</div>
''' + item('decorations/bow_pink.svg', 'Pink Bow', 100, 70) + item('decorations/bow_blue.svg', 'Blue Bow', 100, 70) + item('decorations/bow_gold.svg', 'Gold Bow', 100, 70) + item('decorations/string_lights.svg', 'String Lights', 150, 60) + item('decorations/teepee_tent.svg', 'Teepee', 100, 120) + '''                </div>
            </div>

'''

furn = '''            <!-- ====== 4. FURNITURE ====== -->
            <div class="inventory-category">
                <div class="category-header" onclick="toggleCategory(this)">
                    <span>Furniture</span>
                    <i class="fas fa-chevron-down chevron"></i>
                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Plinths</div>
''' + item('furniture/plinth_white.svg', 'White Plinth', 60, 100) + item('furniture/plinth_pink.svg', 'Pink Plinth', 60, 100) + item('furniture/plinth_gold.svg', 'Gold Plinth', 60, 100) + '''                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Seating</div>
''' + item('furniture/ghost_chair.svg', 'Ghost Chair', 80, 100) + item('furniture/velvet_chair.svg', 'Velvet Chair', 80, 100) + item('furniture/wooden_bench.svg', 'Bench', 120, 70) + '''                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Shelves & Props</div>
''' + item('furniture/wooden_crate.svg', 'Crate', 90, 70) + item('furniture/ladder_shelf.svg', 'Ladder Shelf', 70, 120) + item('furniture/easel.svg', 'Easel', 60, 110) + '''                </div>
            </div>

'''

party = '''            <!-- ====== 5. PARTY ITEMS ====== -->
            <div class="inventory-category">
                <div class="category-header" onclick="toggleCategory(this)">
                    <span>Party Items</span>
                    <i class="fas fa-chevron-down chevron"></i>
                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Cakes & Gifts</div>
''' + item('party/cake.svg', 'Cake', 90, 110) + item('party/gift_box.svg', 'Gift Box', 80, 80) + '''                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Blocks</div>
''' + item('party/block_A.svg', 'Block A', 70, 70) + item('party/block_B.svg', 'Block B', 70, 70) + item('party/block_C.svg', 'Block C', 70, 70) + '''                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Standees</div>
''' + item('party/standee_lion.svg', 'Lion', 90, 110) + item('party/standee_giraffe.svg', 'Giraffe', 85, 130) + '''                </div>
            </div>

'''

themes = '''            <!-- ====== 6. THEME OBJECTS ====== -->
            <div class="inventory-category">
                <div class="category-header" onclick="toggleCategory(this)">
                    <span>Theme Objects</span>
                    <i class="fas fa-chevron-down chevron"></i>
                </div>
                <div class="category-items" style="gap: 5px;">
''' + item('themes/teddy_bear.svg', 'Teddy Bear', 90, 110) + item('themes/rainbow.svg', 'Rainbow', 120, 75) + item('themes/hot_air_balloon.svg', 'Hot Air Balloon', 90, 120) + item('themes/street_lamp.svg', 'Street Lamp', 50, 130) + '''                </div>
            </div>

'''

texts = '''            <!-- ====== 7. TEXT & SIGNS ====== -->
            <div class="inventory-category">
                <div class="category-header" onclick="toggleCategory(this)">
                    <span>Text & Signs</span>
                    <i class="fas fa-chevron-down chevron"></i>
                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Neon Signs</div>
''' + item('texts/neon_happy_birthday.svg', 'Happy Bday', 150, 60) + item('texts/neon_oh_baby.svg', 'Oh Baby', 150, 60) + item('texts/neon_lets_party.svg', 'Party', 150, 60) + '''                </div>
                <div class="category-items" style="gap: 5px;">
                    <div style="width: 100%; font-size: 0.7rem; color: #aaa; margin: 4px 0;">Marquee & Boards</div>
''' + item('texts/marquee_1.svg', 'Marquee 1', 60, 110) + item('texts/acrylic_board.svg', 'Acrylic Sign', 90, 120) + '''
                    <!-- Draggable Interactive Text -->
                    <div class="draggable-item text-draggable" 
                         draggable="true" 
                         data-type="i-text" 
                         data-text="Happy Birthday!" 
                         data-font-family="Arial" 
                         data-color="#333333" 
                         title="Drag onto canvas to add text">
                         <div class="icon-label">
                             <i class="fas fa-font fa-2x" style="color:#007bff; margin-bottom:5px;"></i>
                             <span class="item-label">Custom Text</span>
                         </div>
                    </div>
                </div>
            </div>
'''

# Replace categories 3-7
pattern2 = re.compile(
    r'<!-- ====== 3\. DECORATIONS ====== -->.*?<!-- ====== 7\. TEXT & SIGNS ====== -->.*?</div>\s*</div>',
    re.DOTALL
)
new_content = re.sub(pattern2, dec + furn + party + themes + texts, new_content)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Injection complete! All categories rebuilt with Lineal Color Icon style.")
