"""Removing obsolete label grouping must retain every canvas asset and its name."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CanvasLabelCleanupMigrationTests(TransactionTestCase):
    def test_cleanup_preserves_named_assets_and_backfills_blank_names(self):
        old = [('app','0115_secure_admin_invitations')]
        target = [('app','0116_remove_canvas_labels')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(old)
            state = executor.loader.project_state(old).apps
            Category = state.get_model('app','CanvasCategory')
            Label = state.get_model('app','CanvasLabel')
            Asset = state.get_model('app','CanvasAsset')
            category=Category.objects.create(name='Migration category')
            label=Label.objects.create(category=category,name='Legacy asset name')
            named=Asset.objects.create(category=category,label_ref=label,label='Existing asset name',static_path='images/retained.svg')
            blank=Asset.objects.create(category=category,label_ref=label,label='',image='canvas_assets/retained.png')
            executor=MigrationExecutor(connection);executor.migrate(target)
            state=executor.loader.project_state(target).apps
            Asset=state.get_model('app','CanvasAsset')
            self.assertEqual(Asset.objects.get(pk=named.pk).label,'Existing asset name')
            self.assertEqual(Asset.objects.get(pk=named.pk).static_path,'images/retained.svg')
            self.assertEqual(Asset.objects.get(pk=blank.pk).label,'Legacy asset name')
            self.assertEqual(Asset.objects.get(pk=blank.pk).image.name,'canvas_assets/retained.png')
            self.assertEqual(Asset.objects.filter(category_id=category.pk).count(),2)
            self.assertNotIn('app_canvaslabel',connection.introspection.table_names())
            with self.assertRaises(LookupError):state.get_model('app','CanvasLabel')
        finally:
            MigrationExecutor(connection).migrate(target)
