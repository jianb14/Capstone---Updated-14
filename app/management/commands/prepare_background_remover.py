import os

from django.core.management.base import BaseCommand, CommandError

from app.background_removal import MODEL_NAME, model_directory, _session


class Command(BaseCommand):
    help = 'Download and warm the local detailed asset background-removal model.'

    def handle(self, *args, **options):
        path = model_directory()
        path.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault('U2NET_HOME', str(path))
        try:
            from rembg.sessions.dis_general_use import DisSession
            DisSession.download_models()
            _session()
        except Exception as error:
            raise CommandError('Unable to prepare background removal. Check the installed CPU dependencies and model download connection.') from error
        self.stdout.write(self.style.SUCCESS(f'Background remover ready: {path / (MODEL_NAME + ".onnx")}'))
