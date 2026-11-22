import io
import os
from unittest import skipUnless
from unittest.mock import patch

from PIL import Image, ImageDraw
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from . import test_canvas_uploads as uploads
from .test_canvas_uploads import photo


class BackgroundPreviewTests(uploads.TemporaryCanvasStorage, TestCase):
    setUpTestData = classmethod(uploads.CanvasUploadTests.setUpTestData.__func__)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def preview(self, **fields):
        return self.client.post('/my-designs/uploads/preview/', {
            'image':photo('JPEG'), 'category_id':self.category.pk,
            'design_offer_id':self.offer.pk, **fields})

    def test_preview_is_private_png_and_does_not_save_library_record(self):
        from .models import CanvasUpload
        output = io.BytesIO()
        Image.new('RGBA',(12,6),(100,20,40,0)).save(output,'PNG')
        with patch('app.views.canvas_uploads.remove_image_background', return_value=output.getvalue()) as remove:
            response = self.preview()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(Image.open(io.BytesIO(response.content)).mode,'RGBA')
        self.assertFalse(CanvasUpload.objects.exists())
        remove.assert_called_once()

    def test_bad_file_and_excluded_category_do_not_run_model(self):
        with patch('app.views.canvas_uploads.remove_image_background') as remove:
            self.assertEqual(self.preview(image=SimpleUploadedFile('bad.png',b'bad')).status_code,400)
            self.assertEqual(self.preview(image=SimpleUploadedFile('large.png',b'x'*(10*1024**2+1))).status_code,413)
            self.rule.delete()
            self.assertEqual(self.preview().status_code,400)
            remove.assert_not_called()

    def test_model_failure_returns_retry_without_saving(self):
        from .background_removal import BackgroundRemovalUnavailable
        from .models import CanvasUpload
        with patch('app.views.canvas_uploads.remove_image_background', side_effect=BackgroundRemovalUnavailable):
            response=self.preview()
        self.assertEqual(response.status_code,503)
        self.assertIn('original',response.json()['message'])
        self.assertFalse(CanvasUpload.objects.exists())

    def test_preview_requires_customer_and_rejects_get(self):
        self.assertEqual(self.client.get('/my-designs/uploads/preview/').status_code,405)
        self.owner.role='admin';self.owner.save()
        self.assertEqual(self.preview().status_code,403)
        self.client.logout()
        self.assertEqual(self.preview().status_code,302)

    @skipUnless(os.environ.get('RUN_BACKGROUND_MODEL') == '1','Optional prepared CPU model smoke test')
    def test_real_model_preview_removes_background_and_saves_no_record(self):
        from .background_removal import _session
        self.assertEqual(_session().model_name,'isnet-general-use')
        from .models import CanvasUpload
        image=Image.new('RGB',(240,320),'white')
        ImageDraw.Draw(image).ellipse((55,20,185,200),fill=(210,40,40))
        data=io.BytesIO();image.save(data,'PNG')
        response=self.preview(image=SimpleUploadedFile('balloon.png',data.getvalue()))
        self.assertEqual(response.status_code,200)
        output=Image.open(io.BytesIO(response.content))
        self.assertLess(output.getpixel((0,0))[3],10)
        self.assertGreater(output.getpixel((120,100))[3],200)
        self.assertFalse(CanvasUpload.objects.exists())


class BackgroundProcessingTests(SimpleTestCase):
    def test_mask_cleanup_clears_residue_and_keeps_soft_edges(self):
        from .background_removal import _clean_mask
        mask=Image.new('L',(7,1));mask.putdata([0,4,8,126,245,250,255])
        result=_clean_mask(mask)
        self.assertEqual(list(result.get_flattened_data()),[0,0,0,127,255,255,255])

    def test_generated_cutout_fits_the_existing_upload_size_limit(self):
        from .background_removal import remove_image_background
        noise=Image.frombytes('RGBA',(2048,2048),os.urandom(2048*2048*4))
        with patch('app.background_removal._remove',return_value=noise):
            output=remove_image_background(photo('JPEG',size=(2048,2048)).read())
        self.assertLessEqual(len(output),10*1024**2)
        self.assertEqual(Image.open(io.BytesIO(output)).mode,'RGBA')

    def test_existing_alpha_is_preserved_without_running_model(self):
        from .background_removal import remove_image_background
        with patch('app.background_removal._remove') as remove:
            result=remove_image_background(photo().read())
        remove.assert_not_called()
        self.assertEqual(Image.open(io.BytesIO(result)).getpixel((0,0))[3],42)

    def test_model_mask_is_rgba_and_empty_result_is_rejected(self):
        from .background_removal import remove_image_background, BackgroundRemovalUnavailable
        image=Image.new('RGBA',(12,6),(10,20,30,255))
        image.putpixel((0,0),(10,20,30,0))
        with patch('app.background_removal._remove',return_value=image):
            result=remove_image_background(photo('JPEG').read())
        self.assertEqual(Image.open(io.BytesIO(result)).getpixel((0,0))[3],0)
        with patch('app.background_removal._remove',return_value=Image.new('RGBA',(12,6),(0,0,0,0))):
            with self.assertRaises(BackgroundRemovalUnavailable):
                remove_image_background(photo('JPEG').read())

    def test_busy_model_rejects_quickly_and_releases_after_failure(self):
        from .background_removal import _processing, remove_image_background, BackgroundRemovalUnavailable
        _processing.acquire()
        try:
            with self.assertRaises(BackgroundRemovalUnavailable):
                remove_image_background(photo('JPEG').read())
        finally:
            _processing.release()
        with patch('app.background_removal._remove',side_effect=RuntimeError('test failure')):
            with self.assertRaises(BackgroundRemovalUnavailable):
                remove_image_background(photo('JPEG').read())
        self.assertTrue(_processing.acquire(blocking=False))
        _processing.release()
