import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Project.settings")
django.setup()

import re

import app.services as S

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


# --- 1. Theme detection -----------------------------------------------------
theme_cases = {
    "gawa ka ng spiderman theme para sa 1st birthday ko": "spiderman",
    "spider man design please": "spiderman",
    "unicorn theme debut": "unicorn",
    "jungle safari birthday": "jungle_safari",
    "gawan mo ako ng under the sea": "under_the_sea",
    "frozen theme para sa binyag": "frozen_winter",
    "harry potter themed backdrop": "wizard_magic",
    "prinsesa theme": "princess",
    "pink and gold wedding backdrop": "",
}
for message, expected in theme_cases.items():
    got = S._detect_image_theme(message)
    check(
        f"theme:{message[:40]!r}",
        got == expected,
        f"expected={expected!r} got={got!r}",
    )

# Word-boundary safety: no false positives from substrings.
check(
    "no-false-positive: 'spacious area rentals'",
    S._detect_image_theme("spacious area rentals") == "",
    f"got={S._detect_image_theme('spacious area rentals')!r}",
)

# --- 2. Spiderman prompt: theme block first + theme palette default ---------
spider_msg = "gawa ka ng spiderman theme 1st birthday"
prompt = S.build_image_generation_prompt(spider_msg, "")
first_theme = S.IMAGE_THEME_LIBRARY["spiderman"]["look"]
theme_pos = prompt.find(first_theme)
event_pos = prompt.find("backdrop design inspired by the theme")
check(
    "spiderman: theme block leads the prompt",
    0 < theme_pos < event_pos,
    f"theme_pos={theme_pos} event_pos={event_pos}",
)
check(
    "spiderman: theme palette default (no explicit colors)",
    "color palette: bold red, royal blue and black" in prompt,
    "",
)
check(
    "spiderman: web pattern motifs present",
    "spider web pattern" in prompt,
    "",
)

# Explicit user colors override the theme palette.
prompt_explicit = S.build_image_generation_prompt(
    "spiderman theme but make it gold and black", ""
)
check(
    "spiderman: explicit user colors override palette",
    "color palette: gold, black" in prompt_explicit,
    prompt_explicit.split("color palette: ")[1][:40] if "color palette: " in prompt_explicit else "missing",
)

# Non-themed request still works and has no theme block.
plain = S.build_image_generation_prompt("pink and gold wedding backdrop", "")
check(
    "plain: no theme block injected",
    first_theme not in plain and "color palette: pink, gold" in plain,
    "",
)

# --- 3. Anti-repeat variety --------------------------------------------------
seen = set()
structures = set()
for i in range(6):
    p = S.build_image_generation_prompt(spider_msg, "")
    # Signature = the rolled axes (everything between palette and arch tail).
    sig_start = p.find("focal point: ")
    sig_end = p.find("use balloon garlands")
    if sig_end == -1:
        sig_end = p.find("include a clear entrance arch")
    signature = p[sig_start:sig_end] if sig_start != -1 and sig_end != -1 else p
    seen.add(signature)
    for structure in S.IMAGE_STRUCTURE_VARIATIONS:
        if structure in p:
            structures.add(structure)

check(
    "variety: 6 same-request generations all differ",
    len(seen) == 6,
    f"unique_signatures={len(seen)}/6",
)
check(
    "variety: multiple backdrop structures used",
    len(structures) >= 3,
    f"structures_used={len(structures)}/6",
)

# --- 4. Mood board: 3 options must be distinct prompts ----------------------
mood_msg = "3 options para sa jungle safari birthday"
options = [S.build_image_generation_prompt(mood_msg, "") for _ in range(3)]
check(
    "mood board: 3 options are distinct prompts",
    len(set(options)) == 3,
    f"unique={len(set(options))}/3",
)
check(
    "mood board: jungle theme present in each",
    all("jungle safari theme backdrop" in o for o in options),
    "",
)

# --- 5. Previous-concept preserve logic still works --------------------------
context = (
    "Previous generated image prompt: pink gold wedding round panels "
    "Recent user image instructions: lagyan ng arch"
)
preserved = S.build_image_generation_prompt("lagyan ng arch", context)
check(
    "followup: previous concept preserved",
    "preserve this previous concept" in preserved,
    "",
)
fresh = S.build_image_generation_prompt("gawa ka ng unicorn theme", context)
check(
    "followup: fresh theme request does NOT inherit previous concept",
    "preserve this previous concept" not in fresh,
    "",
)

# --- 6. is_image_request themed phrasing -------------------------------------
check(
    "is_image_request: 'gawa ka ng spiderman'",
    S.is_image_request("gawa ka ng spiderman") is True,
    "",
)
check(
    "is_image_request: pricing question stays text-only",
    S.is_image_request("magkano ang spiderman themed backdrop niyo?") is False,
    "",
)

# --- Output ------------------------------------------------------------------
out_lines = []
all_ok = True
for name, ok, detail in results:
    status = "PASS" if ok else "FAIL"
    if not ok:
        all_ok = False
    line = f"[{status}] {name}" + (f" — {detail}" if detail else "")
    out_lines.append(line)
    print(line)
out_lines.append("ALL_OK" if all_ok else "SOME_FAILED")
with open("_image_prompts_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
print("\n" + ("ALL_OK" if all_ok else "SOME_FAILED"))
