"""Popular-first, natural package order for catalogs and booking pickers."""
import re

from .models import Package


def ordered_packages(queryset=None):
    def natural_name(package):
        parts = tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                      for part in re.split(r'(\d+)', package.name.strip()))
        return parts, package.pk

    if queryset is None:
        queryset = Package.objects.all()
    packages = sorted(queryset, key=natural_name)
    for position, package in enumerate(packages):
        package.catalog_position = position
    return sorted(packages, key=lambda package: not package.is_featured)
