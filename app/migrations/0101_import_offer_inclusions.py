import re
from django.db import migrations


def normalized(value):
    words = re.sub(r'[^a-z0-9]+', ' ', value.lower()).split()
    result = ' '.join(word[:-1] if word.endswith('s') and len(word) > 3 else word for word in words)
    return {'styro name': 'styrofoam name'}.get(result, result)


def import_inclusions(apps, schema_editor):
    Category = apps.get_model('app', 'CanvasCategory')
    Offer = apps.get_model('app', 'DesignOffer')
    Inclusion = apps.get_model('app', 'OfferInclusion')
    Requirement = apps.get_model('app', 'DesignRequirement')
    for category in Category.objects.all():
        if 'balloon' in normalized(category.name).split():
            category.is_balloon = True
            category.save(update_fields=['is_balloon'])
    for offer in Offer.objects.all():
        if Inclusion.objects.filter(offer_id=offer.pk).exists():
            continue
        item = getattr(offer, offer.kind)
        categories = {}
        by_id = {}
        for category in Category.objects.filter(**{'available_' + offer.kind: True}):
            categories.setdefault(normalized(category.name), []).append(category)
            by_id[category.pk] = category
        rules = {rule.category_id: rule for rule in offer.requirements.select_related('category')}
        used, rows = set(), []
        for line in item.features.splitlines():
            name, quantity = line.strip(), None
            if not name:
                continue
            match = re.match(r'^(\d+)\s+(.+)$', name)
            if match and int(match[1]) > 0:
                quantity, name = int(match[1]), match[2]
            clean = re.sub(r'\s*\(max\s+\d+\s+colou?rs?\)', '', name, flags=re.I).strip()
            matches = categories.get(normalized(clean), [])
            category = matches[0] if len(matches) == 1 and matches[0].pk not in used else None
            if category:
                used.add(category.pk)
                if category.is_balloon:
                    name = clean
            rule = rules.get(category.pk) if category else None
            rows.append(Inclusion(offer_id=offer.pk, name=name, quantity=rule.maximum if rule else quantity,
                                  category_id=category.pk if category else None,
                                  required_minimum=rule.minimum if rule else 0, order=len(rows)))
        for cid, rule in rules.items():
            if cid not in used:
                rows.append(Inclusion(offer_id=offer.pk, name=rule.display_name or rule.category.name,
                                      quantity=rule.maximum, category_id=cid, required_minimum=rule.minimum, order=len(rows)))
        Inclusion.objects.bulk_create(rows)
        lines, color_shown = [], False
        for row in rows:
            line = f'{row.quantity} {row.name}' if row.quantity is not None else row.name
            category = by_id.get(row.category_id)
            if category and category.is_balloon and offer.max_balloon_colors and not color_shown:
                line += f' (max {offer.max_balloon_colors} colors)'
                color_shown = True
            lines.append(line)
            if row.category_id in rules:
                offer.requirements.filter(category_id=row.category_id).update(display_name=row.name)
            elif row.category_id:
                Requirement.objects.create(
                    offer_id=offer.pk, category_id=row.category_id, display_name=row.name,
                    required=False, minimum=0, maximum=row.quantity,
                )
        item.features = '\n'.join(lines)
        item.save(update_fields=['features'])


class Migration(migrations.Migration):
    dependencies = [('app', '0100_structured_offer_inclusions')]
    operations = [migrations.RunPython(import_inclusions, migrations.RunPython.noop)]
