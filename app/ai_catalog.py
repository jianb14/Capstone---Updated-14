"""Immediate answers for an unambiguous request to list the live package catalog."""
import re

from .models import Package


def package_catalog_reply(message):
    text = ' '.join((message or '').lower().split()).strip(' ?!.')
    if not re.fullmatch(
        r'(?:our packages|your packages|packages|package list|'
        r'(?:please )?(?:list|show)(?: me)?(?: all)?(?: your| the)? packages|'
        r'what are (?:your|the) packages|'
        r'ano(?: ano)? (?:ang|yung) (?:mga )?package(?:s)?(?: (?:niyo|ninyo))?)', text):
        return None
    packages = Package.objects.filter(is_active=True).order_by('name', 'pk')
    lines = ['Here are our available packages:']
    for index, package in enumerate(packages, 1):
        lines.extend(['', f'{index}. **{package.name}: PHP {package.price:,.2f}**'])
        for feature in package.feature_list():
            if feature.strip():
                lines.append('   - ' + feature.strip())
        if package.service_charge:
            lines.append(f'   - Service charge: PHP {package.service_charge:,.2f}')
        if package.notes:
            lines.append('   ' + ' '.join(package.notes.split()))
    if len(lines) == 1:
        return 'No packages are currently listed. Please contact our team for current options.'
    lines.extend(['', 'Final pricing and availability are confirmed during booking.'])
    return '\n'.join(lines)
