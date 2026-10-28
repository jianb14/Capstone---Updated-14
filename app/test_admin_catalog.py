"""Catalog authorization, field validation, paging, protected deletion and shared offer rules."""
import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import (AddOn, AdditionalOnly, CanvasAsset, CanvasCategory, DesignOffer,
    DesignRequirement, GalleryCategory, GalleryImage, Package, User)


def upload(name='catalog.png'):
    stream = io.BytesIO(); Image.new('RGB', (30, 24), '#aba39c').save(stream, 'PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminCatalogTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='catalog-admin', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='catalog-customer', role='customer', email_verified=True)
        self.client.force_login(self.admin)
        self.ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        self.gallery = GalleryCategory.objects.create(name='Catalog birthdays')
        self.canvas = CanvasCategory.objects.create(name='Catalog panels', available_entrance=True, available_stand=True)

    def url(self, resource, action='create', pk=0):
        return reverse('admin_catalog_action', args=[resource, action, pk])

    def test_all_workspaces_and_resources_return_async_tables_and_dialogs(self):
        for route, tabs in [('admin_package_list', ('package','entrance','stand')),
                            ('admin_gallery', ('gallery-image','gallery-category')),
                            ('admin_canvas_assets', ('canvas-asset','canvas-category'))]:
            for tab in tabs:
                with self.subTest(tab=tab):
                    page = self.client.get(reverse(route), {'tab': tab})
                    self.assertEqual(page.status_code, 200)
                    self.assertContains(page, 'data-catalog-dialog')
                    self.assertContains(page, 'data-bulk-bar hidden')
                    async_page = self.client.get(reverse(route), {'tab': tab}, **self.ajax)
                    self.assertEqual(async_page.status_code, 200)
                    self.assertIn('data-catalog-filters', async_page.json()['html'])
                    self.assertEqual(async_page['Cache-Control'], 'private, no-store')
                    form = self.client.get(self.url(tab), **self.ajax)
                    self.assertEqual(form.status_code, 200)
                    self.assertIn('html', form.json())
                    if tab in ('package','entrance','stand'):
                        self.assertIn('form="offerEditorForm"',form.json()['footer_html'])
                        self.assertNotIn('id="saveOfferButton"',form.json()['html'])
                        self.assertNotIn('offerSaveStatus',form.json()['footer_html'])
                        self.assertNotIn('Changes are saved together.',form.json()['footer_html'])
                    else:
                        self.assertIn('form="catalogEditorForm"',form.json()['footer_html'])
                        self.assertNotIn('type="submit"',form.json()['html'])

    def test_permissions_csrf_and_read_only_gets(self):
        image = GalleryImage.objects.create(category=self.gallery, image='gallery/test.png')
        self.assertEqual(self.client.get(self.url('gallery-image','delete',image.pk)).status_code,405)
        self.assertTrue(GalleryImage.objects.filter(pk=image.pk).exists())
        self.assertEqual(self.client.get(reverse('admin_gallery_image_delete',args=[image.pk])).status_code,405)
        client = Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(self.url('gallery-image','delete',image.pk)).status_code,403)
        self.client.force_login(self.customer)
        for resource in ('package','entrance','stand','gallery-image','gallery-category','canvas-asset','canvas-category'):
            self.assertEqual(self.client.get(self.url(resource)).status_code,403)
            self.assertEqual(self.client.post(self.url(resource,'bulk-delete'),{'ids':[1]}).status_code,403)
        self.assertEqual(self.client.get(reverse('admin_gallery')).status_code,403)

    def test_category_dialogs_validate_then_save_and_delete(self):
        for resource, data, model in (
            ('gallery-category', {'name':'New album','order':2}, GalleryCategory),
            ('canvas-category', {'name':'New canvas group','available_for':['package'],'is_active':'on'}, CanvasCategory),
        ):
            response=self.client.post(self.url(resource), data, **self.ajax)
            self.assertEqual(response.status_code,200,response.content)
            item=model.objects.get(name=data['name'])
            data['name']='Edited '+data['name']
            response=self.client.post(self.url(resource,'edit',item.pk),data,**self.ajax)
            self.assertEqual(response.status_code,200,response.content)
            item.refresh_from_db();self.assertEqual(item.name,data['name'])
            response=self.client.post(self.url(resource,'delete',item.pk),**self.ajax)
            self.assertEqual(response.status_code,200,response.content)
            self.assertFalse(model.objects.filter(pk=item.pk).exists())

    def test_labels_are_removed_from_workspace_and_routes(self):
        from django.apps import apps
        from django.urls import Resolver404, resolve
        response=self.client.get(reverse('admin_canvas_assets'),{'tab':'canvas-label'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['resource'],'canvas-asset')
        self.assertNotContains(response,'Add canvas label')
        self.assertEqual(len(response.context['tabs']),2)
        self.assertEqual(self.client.get(self.url('canvas-label')).status_code,404)
        with self.assertRaises(Resolver404):resolve('/staff/canvas-assets/label/create/')
        with self.assertRaises(LookupError):apps.get_model('app','CanvasLabel')

    def test_paging_search_status_and_empty_state(self):
        for i in range(19):
            GalleryImage.objects.create(category=self.gallery, caption=f'Celebration {i}', image='gallery/test.png', is_active=i%2==0)
        url = reverse('admin_gallery')
        first = self.client.get(url, **self.ajax).json()['html']
        self.assertEqual(first.count('data-catalog-row='),8)
        page = self.client.get(url, {'page':2,'per_page':4}, **self.ajax).json()
        self.assertEqual(page['html'].count('data-catalog-row='),4)
        self.assertEqual(page['page'],2)
        filtered = self.client.get(url, {'status':'hidden','q':self.gallery.name}, **self.ajax).json()['html']
        self.assertEqual(filtered.count('>Hidden</span>'),8)
        empty = self.client.get(url, {'q':'nothing-matches'}, **self.ajax).json()['html']
        self.assertIn('No matching photos',empty); self.assertNotIn('<thead>',empty); self.assertNotIn('data-list-footer',empty)
        self.assertEqual(self.client.get(url, {'page':999,'per_page':999}, **self.ajax).json()['page'],3)

    def test_gallery_batch_upload_validation_and_edit_without_reupload(self):
        url = self.url('gallery-image')
        invalid = self.client.post(url, {'caption':'x'*256}, **self.ajax)
        self.assertEqual(invalid.status_code,400)
        self.assertEqual(set(invalid.json()['errors']),{'category','caption','images'})
        self.assertEqual(GalleryImage.objects.count(),0)
        for files in ([upload(f'{i}.png') for i in range(5)], [SimpleUploadedFile('bad.png',b'not-image',content_type='image/png')]):
            response=self.client.post(url, {'category':self.gallery.pk,'images':files}, **self.ajax)
            self.assertEqual(response.status_code,400); self.assertIn('images',response.json()['errors'])
        response=self.client.post(url, {'category':self.gallery.pk,'caption':'Valid caption','images':[upload(),upload('second.png')],'is_active':'on'}, **self.ajax)
        self.assertEqual(response.status_code,200,response.content); self.assertEqual(GalleryImage.objects.count(),2)
        image=GalleryImage.objects.first(); old=image.image.name
        response=self.client.post(self.url('gallery-image','edit',image.pk), {'category':self.gallery.pk,'caption':'Edited'}, **self.ajax)
        self.assertEqual(response.status_code,200,response.content)
        image.refresh_from_db(); self.assertEqual(image.caption,'Edited'); self.assertEqual(image.image.name,old); self.assertFalse(image.is_active)

    def test_canvas_dimensions_availability_and_duplicate_validation(self):
        data={'label':'My panel','category':self.canvas.pk,'width':'0','height':'a','available_for':['package'],'image':upload()}
        response=self.client.post(self.url('canvas-asset'),data,**self.ajax)
        self.assertEqual(response.status_code,400); self.assertEqual(set(response.json()['errors']),{'width','height'})
        data.update(width=100,height=120,image=upload(),available_for=['package','entrance'],is_active='on')
        response=self.client.post(self.url('canvas-asset'),data,**self.ajax)
        self.assertEqual(response.status_code,200,response.content)
        item=CanvasAsset.objects.get(label='My panel'); self.assertTrue(item.available_entrance)
        response=self.client.post(self.url('canvas-category'), {'name':self.canvas.name,'order':'-1','available_for':['package']},**self.ajax)
        self.assertEqual(response.status_code,400); self.assertIn('name',response.json()['errors']); self.assertIn('order',response.json()['errors'])
        response=self.client.post(self.url('canvas-category','edit',self.canvas.pk), {'name':self.canvas.name,'order':1,'available_for':['package']},**self.ajax)
        self.assertEqual(response.status_code,400); self.assertIn('available_for',response.json()['errors'])

    def test_bulk_delete_is_atomic_and_rejects_protected_or_stale_selection(self):
        one=GalleryImage.objects.create(category=self.gallery,image='gallery/one.png')
        two=GalleryImage.objects.create(category=self.gallery,image='gallery/two.png')
        url=self.url('gallery-image','bulk-delete')
        for ids in ([],[one.pk,one.pk],[one.pk,999999],['no'],[0],list(range(101))):
            response=self.client.post(url,{'ids':ids},**self.ajax)
            self.assertIn(response.status_code,(400,409));self.assertEqual(GalleryImage.objects.count(),2)
        response=self.client.post(url,{'ids':[one.pk,two.pk]},**self.ajax)
        self.assertEqual(response.status_code,200);self.assertFalse(GalleryImage.objects.exists())
        built_in=CanvasAsset.objects.exclude(builtin_key=None).first()
        custom=CanvasAsset.objects.create(category=self.canvas,label='Custom')
        response=self.client.post(self.url('canvas-asset','bulk-delete'),{'ids':[custom.pk,built_in.pk]},**self.ajax)
        self.assertEqual(response.status_code,400);self.assertTrue(CanvasAsset.objects.filter(pk=custom.pk).exists())

    def test_category_deletion_preserves_children_and_offer_rules(self):
        GalleryImage.objects.create(category=self.gallery,image='gallery/child.png')
        response=self.client.post(self.url('gallery-category','delete',self.gallery.pk),**self.ajax)
        self.assertEqual(response.status_code,400); self.assertTrue(GalleryCategory.objects.filter(pk=self.gallery.pk).exists())
        package=Package.objects.create(name='Configured',price=1000)
        offer=DesignOffer.objects.create(kind='package',package=package)
        DesignRequirement.objects.create(offer=offer,category=self.canvas,required=True,minimum=1)
        response=self.client.post(self.url('canvas-category','delete',self.canvas.pk),**self.ajax)
        self.assertEqual(response.status_code,400); self.assertTrue(self.canvas.design_requirements.exists())

    def test_all_offer_types_keep_shared_inclusions_and_validation(self):
        for kind,model in [('package',Package),('entrance',AddOn),('stand',AdditionalOnly)]:
            data={'name':'Offer '+kind,'price':'2500','solo_price':'5000','inclusions':json.dumps([{'row_type':'service','name':'Setup','quantity':None,'category_id':None,'required_minimum':0}]),'active_present':'1','is_active':'on'}
            response=self.client.post(self.url(kind),data,**self.ajax)
            self.assertEqual(response.status_code,200,response.content)
            item=model.objects.get(name='Offer '+kind)
            self.assertEqual(item.features,'Setup')
            self.assertEqual(DesignOffer.objects.get(**{kind:item}).inclusions.count(),1)
            data['price']='NaN'
            self.assertEqual(self.client.post(self.url(kind,'edit',item.pk),data,**self.ajax).status_code,400)
            item.refresh_from_db();self.assertEqual(item.price,2500)

    def test_details_escape_user_text_and_builtin_edit_is_rejected(self):
        category=GalleryCategory.objects.create(name='<script>bad</script>')
        GalleryImage.objects.create(category=category,image='gallery/detail.png')
        response=self.client.get(self.url('gallery-category','detail',category.pk),**self.ajax)
        self.assertIn('&lt;script&gt;',response.json()['html']); self.assertNotIn('<script>',response.json()['html'])
        self.assertIn('<dt>Items</dt><dd>1</dd>',response.json()['html'])
        builtin=CanvasAsset.objects.exclude(builtin_key=None).first()
        self.assertEqual(self.client.get(self.url('canvas-asset','edit',builtin.pk),**self.ajax).status_code,400)
