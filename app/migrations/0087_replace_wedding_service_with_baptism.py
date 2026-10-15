from django.db import migrations


def replace_wedding_service_with_baptism(apps, schema_editor):
    """Palitan ang default na 'Wedding Balloon Installations' service ng
    'Baptism & Christening Balloon Styling' kasama ang bagong description,
    Key Inclusions (features), at best_for.

    Guarded: only tumakbo kapag hindi pa ito pinalitan ng admin (title must
    still match) para hindi ma-overwrite ang mga later edits sa UI.
    Image ay hindi hinahawakan — naka-upload na ito sa admin."""
    Service = apps.get_model("app", "Service")

    Service.objects.filter(title="Wedding Balloon Installations").update(
        title="Baptism & Christening Balloon Styling",
        description=(
            "We style baptism and christening celebrations with soft, heartfelt "
            "balloon designs — gentle pastel palettes, elegant backdrops, and "
            "tasteful installs that honor your little one's special day. From "
            "the church entrance to the reception, we coordinate closely with "
            "your family and suppliers for a smooth, stress-free setup."
        ),
        features=(
            "Styled backdrop panels with styrofoam name\n"
            "Balloons in your chosen color motif\n"
            "Cake table, celebrant chair, and souvenir rack setup"
        ),
        best_for="Baptisms, christenings, and baby celebrations",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0086_repair_payment_admin_notified_column"),
    ]

    operations = [
        migrations.RunPython(
            replace_wedding_service_with_baptism,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
