"""Structured inclusions and their legacy display/validation projections."""
import re

from .models import CanvasCategory, DesignRequirement, OfferInclusion


def normalized_name(value):
    words = re.sub(r'[^a-z0-9]+', ' ', value.lower()).split()
    words = [word[:-1] if word.endswith('s') and len(word) > 3 else word for word in words]
    result = ' '.join(words)
    return {'styro name': 'styrofoam name'}.get(result, result)


def import_rows(features, categories, rules=()):
    """Only exact normalized matches are safe; dimensions are never quantities."""
    by_name = {}
    for category in categories:
        by_name.setdefault(normalized_name(category.name), []).append(category)
    by_category = {rule.category_id: rule for rule in rules}
    used, rows = set(), []
    for line in features.splitlines():
        if not line.strip():
            continue
        name, quantity = line.strip(), None
        match = re.match(r'^(\d+)\s+(.+)$', name)
        if match and int(match[1]) > 0:
            quantity, name = int(match[1]), match[2]
        clean_name = re.sub(r'\s*\(max\s+\d+\s+colou?rs?\)', '', name, flags=re.I).strip()
        matches = by_name.get(normalized_name(clean_name), [])
        category = matches[0] if len(matches) == 1 and matches[0].pk not in used else None
        if category:
            used.add(category.pk)
            if category.is_balloon:
                name = clean_name
        rule = by_category.get(category.pk) if category else None
        rows.append({'row_type': 'item', 'name': name, 'quantity': rule.maximum if rule else quantity,
                     'category_id': category.pk if category else None,
                     'required_minimum': rule.minimum if rule else 0, 'order': len(rows)})
    for rule in rules:
        if rule.category_id not in used:
            rows.append({'row_type': 'item', 'name': rule.display_name or rule.category.name,
                         'quantity': rule.maximum, 'category_id': rule.category_id,
                         'required_minimum': rule.minimum, 'order': len(rows)})
    return rows


def display_lines(rows, colors=None, balloon_ids=()):
    lines, color_shown = [], False
    for row in rows:
        name = row['name']
        text = f"{row['quantity']} {name}" if row.get('quantity') is not None else name
        if colors and row.get('category_id') in balloon_ids and not color_shown:
            text += f' (max {colors} colors)'
            color_shown = True
        lines.append(text)
    return lines


def store_inclusions(offer, rows, colors, enabled):
    """Called inside the offer form transaction after all validation succeeds."""
    offer.inclusions.all().delete()
    OfferInclusion.objects.bulk_create([OfferInclusion(offer=offer, **row) for row in rows])
    offer.requirements.all().delete()
    DesignRequirement.objects.bulk_create([
        DesignRequirement(offer=offer, category_id=row['category_id'], display_name=row['name'],
                          required=row['required_minimum'] > 0, minimum=row['required_minimum'], maximum=row['quantity'])
        for row in rows if row['row_type'] == 'item' and row['category_id']
    ])
    balloon_ids = set(CanvasCategory.objects.filter(is_balloon=True).values_list('pk', flat=True))
    offer.max_balloon_colors = colors if any(row.get('category_id') in balloon_ids for row in rows) else None
    offer.is_enabled = enabled
    offer.save(update_fields=['max_balloon_colors', 'is_enabled'])
    item = offer.item
    item.features = '\n'.join(display_lines(rows, offer.max_balloon_colors, balloon_ids))
    item.save(update_fields=['features'])
