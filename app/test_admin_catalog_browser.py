"""Opt-in real-browser checks for content management without document navigation."""
import io
import os
import base64
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from .models import AddOn, AdditionalOnly, CanvasAsset, CanvasCategory, GalleryCategory, GalleryImage, Package, User


@skipUnless(os.environ.get('RUN_CATALOG_BROWSER') == '1', 'Optional catalog browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class CatalogBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        admin=User.objects.create_user(username='catalog-browser-admin',role='admin',email_verified=True)
        self.client.force_login(admin)
        self.category=GalleryCategory.objects.create(name='Browser birthdays')
        self.canvas=CanvasCategory.objects.create(name='Browser panels',available_entrance=True,available_stand=True)
        stream=io.BytesIO();Image.new('RGB',(90,80),'#bdb8b2').save(stream,'PNG');self.photo=stream.getvalue()
        for index in range(12):
            GalleryImage.objects.create(category=self.category,caption=f'Event {index}',image=SimpleUploadedFile(f'photo{index}.png',self.photo,content_type='image/png'))
            Package.objects.create(name=f'Package {index}',price=1000+index,features='Setup')
        AddOn.objects.create(name='Entrance browser',price=1000,solo_price=2000,features='Entrance setup')
        AdditionalOnly.objects.create(name='Stand browser',price=500,features='Welcome stand')
        CanvasAsset.objects.create(category=self.canvas,label='Browser asset',image=SimpleUploadedFile('asset.png',self.photo,content_type='image/png'),available_entrance=True,available_stand=True)
        self.artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'

    def browser(self,p):
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
        context.route('https://cdnjs.cloudflare.com/**',lambda route:route.abort())
        context.route('https://cdn.jsdelivr.net/**',lambda route:route.fulfill(status=200,content_type='application/javascript',body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser,context

    def assert_feedback(self,page,message,kind='success'):
        from playwright.sync_api import expect
        toast=page.locator('.cfg-toast')
        expect(toast).to_be_visible()
        expect(toast).to_contain_text(message)
        expect(toast).to_have_attribute('data-kind',kind)
        self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
        self.assertLess(toast.bounding_box()['y'],100)
        self.assertGreaterEqual(toast.bounding_box()['x'],0)
        self.assertLessEqual(toast.bounding_box()['x']+toast.bounding_box()['width'],page.viewport_size['width'])
        return toast

    def test_gallery_async_filter_pagination_inline_validation_upload_edit_and_bulk_delete(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();documents=[];errors=[]
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('admin_gallery'))
                expect(page.locator('.cfg-toast')).to_be_hidden()
                expect(page.locator('[data-catalog-row]')).to_have_count(8)
                page.get_by_role('link',name='Page 2',exact=True).click()
                expect(page.locator('[data-catalog-row]')).to_have_count(4)
                page.get_by_role('button',name='Rows per page: 8',exact=True).click();page.get_by_role('option',name='4',exact=True).click()
                expect(page.locator('[aria-current=page][aria-label="Page 1"]')).to_be_visible()
                search=page.get_by_role('searchbox',name='Search library');search.fill('missing-gallery')
                expect(page.get_by_text('No matching photos',exact=True)).to_be_visible()
                expect(page.locator('.catalog-table thead')).to_have_count(0)
                page.get_by_role('button',name='Clear search',exact=True).click()
                expect(page.locator('[data-catalog-row]')).to_have_count(4)
                page.get_by_role('button',name='Add gallery image',exact=True).click()
                dialog=page.locator('[data-catalog-dialog]');expect(dialog).to_be_visible()
                expect(dialog.get_by_text('Caption (optional)',exact=True)).to_be_visible()
                expect(dialog.get_by_text('Visibility',exact=True)).to_be_visible()
                expect(dialog.get_by_label('Visible in gallery',exact=True)).to_be_checked()
                category=dialog.locator('[data-field=category] .ac-select-trigger')
                self.assertAlmostEqual(category.bounding_box()['width'],dialog.locator('.catalog-fields').bounding_box()['width'],delta=1)
                page.get_by_role('button',name='Add item',exact=True).click()
                expect(dialog.locator('[data-error-for=images]')).to_have_text('Choose at least one image.')
                expect(dialog.locator('[data-error-for=category]')).to_have_text('Category is required.')
                expect(page.locator('.cfg-toast')).to_be_hidden()
                page.get_by_role('button',name='Category: Choose a category',exact=True).click()
                page.get_by_role('option',name=self.category.name,exact=True).click()
                page.locator('#catalog_caption').fill('Uploaded from browser')
                page.locator('#catalog_images').set_input_files([{'name':'browser-upload.png','mimeType':'image/png','buffer':self.photo}])
                expect(dialog.locator('[data-upload-previews] img')).to_have_count(1)
                page.locator('[data-upload-zone]').evaluate('''(zone,encoded)=>{
                    const bytes=Uint8Array.from(atob(encoded),char=>char.charCodeAt(0));
                    const transfer=new DataTransfer();transfer.items.add(new File([bytes],'dropped.png',{type:'image/png'}));
                    zone.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
                }''',base64.b64encode(self.photo).decode())
                expect(dialog.locator('[data-upload-previews] img')).to_have_count(2)
                page.get_by_role('button',name='Remove selected image 2',exact=True).click()
                expect(dialog.locator('[data-upload-previews] img')).to_have_count(1)
                page.get_by_role('button',name='Add item',exact=True).click()
                expect(dialog).to_be_hidden()
                expect(page.get_by_text('Uploaded from browser',exact=True)).to_be_visible()
                self.assert_feedback(page,'Gallery image saved successfully.')
                page.get_by_role('button',name='Edit Uploaded from browser',exact=True).click()
                page.locator('#catalog_caption').fill('Edited from browser')
                page.get_by_role('button',name='Save changes',exact=True).click();expect(dialog).to_be_hidden()
                self.assert_feedback(page,'Gallery image saved successfully.')
                page.get_by_role('button',name='View Edited from browser',exact=True).last.click()
                expect(dialog.locator('h3')).to_have_count(0)
                expect(dialog.get_by_text('Edited from browser',exact=True)).to_have_count(1)
                page.get_by_role('button',name='Open full-size image 1',exact=True).click()
                expect(page.locator('[data-catalog-image]')).to_be_visible()
                page.get_by_role('button',name='Close photo',exact=True).click()
                page.get_by_role('button',name='Close dialog',exact=True).click()
                page.locator('[data-select-all]').check()
                expect(page.locator('[data-selected-count]')).to_have_text('4')
                page.get_by_role('button',name='Delete selected',exact=True).click()
                page.get_by_role('button',name='Delete items',exact=True).click()
                expect(page.locator('[data-delete-dialog]')).to_be_hidden()
                expect(page.locator('[data-catalog-row]')).to_have_count(4)
                expect(page.get_by_text('Edited from browser',exact=True)).to_have_count(0)
                self.assert_feedback(page,'4 item(s) deleted.')
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_all_offer_types_save_in_modal_without_reload(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url+reverse('admin_package_list'))
                for tab, singular, save in [('Packages','package','Package'),('Entrance arches','entrance arch','Entrance Arch'),('Welcome stands','welcome stand','Welcome Stand')]:
                    page.locator('.catalog-tabs a').filter(has_text=tab).click()
                    page.get_by_role('button',name=f'Add {singular}',exact=True).click()
                    expect(page.locator('#offerEditorForm')).to_be_visible()
                    page.get_by_role('button',name=f'Save {save}',exact=True).click()
                    expect(page.locator('#error_name')).not_to_be_empty()
                    expect(page.get_by_role('tab',name='Details',exact=True)).to_have_attribute('aria-selected','true')
                    expect(page.locator('#id_name')).to_have_css('border-color','rgb(184, 53, 60)')
                    page.locator('#id_name').fill('New '+save);page.locator('#id_price').fill('1200')
                    if singular=='entrance arch':page.locator('#id_solo_price').fill('2200')
                    page.get_by_role('tab',name='Inclusions',exact=False).click()
                    page.get_by_role('button',name='Add Service',exact=True).click()
                    page.locator('[data-row-field=name]').fill('Setup and delivery')
                    page.get_by_role('tab',name='Photos',exact=True).click()
                    page.locator('#previewImageInput').set_input_files({'name':'offer.png','mimeType':'image/png','buffer':self.photo})
                    page.get_by_role('tab',name='Visibility',exact=True).click()
                    expect(page.get_by_label('Active offer',exact=False)).to_be_checked()
                    page.get_by_role('button',name=f'Save {save}',exact=True).click()
                    expect(page.locator('[data-catalog-dialog]')).to_be_hidden()
                    expect(page.get_by_text('New '+save,exact=True)).to_be_visible()
                    self.assert_feedback(page,'saved successfully.')
                    page.get_by_role('button',name='Edit New '+save,exact=True).click()
                    expect(page.locator('#id_name')).to_have_value('New '+save)
                    page.locator('#id_name').fill('Edited '+save)
                    page.get_by_role('tab',name='Inclusions',exact=False).click()
                    expect(page.locator('[data-row-field=name]')).to_have_value('Setup and delivery')
                    page.get_by_role('button',name=f'Save {save}',exact=True).click()
                    expect(page.locator('[data-catalog-dialog]')).to_be_hidden()
                    expect(page.get_by_text('Edited '+save,exact=True)).to_be_visible()
                    self.assert_feedback(page,'saved successfully.')
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_canvas_modal_validation_and_design_type_filter_are_async(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('admin_canvas_assets'))
                expect(page.locator('.catalog-tabs a')).to_have_count(2)
                page.get_by_role('button',name='Add canvas asset',exact=True).click()
                page.get_by_role('button',name='Add item',exact=True).click()
                expect(page.locator('[data-error-for=label]')).to_have_text('Asset name is required.')
                expect(page.locator('[data-error-for=image]')).to_have_text('Image is required.')
                page.locator('#catalog_label').fill('New canvas panel')
                page.get_by_role('button',name='Category: Choose a category',exact=True).click();page.get_by_role('option',name=self.canvas.name,exact=True).click()
                page.locator('#catalog_image').set_input_files({'name':'new-panel.png','mimeType':'image/png','buffer':self.photo})
                page.get_by_role('button',name='Add item',exact=True).click()
                expect(page.locator('[data-catalog-dialog]')).to_be_hidden()
                expect(page.get_by_text('New canvas panel',exact=True)).to_be_visible()
                self.assert_feedback(page,'Canvas asset saved successfully.')
                page.get_by_role('button',name='Category filter: All categories',exact=True).click()
                page.get_by_role('option',name=self.canvas.name,exact=True).click()
                expect(page.get_by_role('button',name='Category filter: '+self.canvas.name,exact=True)).to_be_visible()
                page.get_by_role('button',name='Design type: Packages',exact=True).click();page.get_by_role('option',name='Entrance arches',exact=True).click()
                expect(page.get_by_role('button',name='Category filter: All categories',exact=True)).to_be_visible()
                expect(page.get_by_text('New canvas panel',exact=True)).to_have_count(0)
                expect(page.get_by_text('Browser asset',exact=True)).to_be_visible()
                page.locator('.catalog-tabs a').filter(has_text='Categories').click()
                page.get_by_role('button',name='Add canvas category',exact=True).click()
                expect(page.get_by_text('Enable only for balloon categories. Other decorations do not use this color limit.',exact=True)).to_be_visible()
                expect(page.get_by_label('Uses the shared balloon color limit',exact=True)).not_to_be_checked()
                page.get_by_role('button',name='Close dialog',exact=True).click()
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_workspaces_forms_details_light_dark_and_mobile(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                for route, singular in [('admin_package_list','package'),('admin_gallery','gallery image'),('admin_canvas_assets','canvas asset')]:
                    page.goto(self.live_server_url+reverse(route))
                    for theme in ('light','dark'):
                        page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                        trash=page.locator('.ac-icon-button.catalog-delete').first
                        trash.scroll_into_view_if_needed()
                        color=trash.evaluate('(node)=>getComputedStyle(node).color')
                        background=trash.evaluate('(node)=>getComputedStyle(node).backgroundColor')
                        trash.hover();page.wait_for_timeout(200)
                        self.assertEqual(trash.evaluate('(node)=>getComputedStyle(node).color'),color)
                        self.assertNotEqual(trash.evaluate('(node)=>getComputedStyle(node).backgroundColor'),background)
                        for width in (1440,768,390,320):
                            page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(150)
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),f'{route}/{theme}/{width}')
                            search=page.get_by_role('searchbox',name='Search library');search.focus()
                            self.assertEqual(search.evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                            page.screenshot(path=str(self.artifacts/f'{route}-{theme}-{width}.png'),animations='disabled')
                        page.get_by_role('button',name=f'Add {singular}',exact=True).click()
                        expect(page.locator('[data-catalog-dialog]')).to_be_visible()
                        expect(page.locator('#offerEditorForm' if route=='admin_package_list' else '[data-catalog-form]')).to_be_visible()
                        self.assertFalse(page.locator('[data-catalog-body]').evaluate('(node)=>node.scrollWidth>node.clientWidth'),f'Modal {route}/{theme}')
                        field=page.locator('#id_name' if route=='admin_package_list' else '#catalog_caption' if route=='admin_gallery' else '#catalog_label')
                        field.focus();self.assertEqual(field.evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid',f'Input focus {route}/{theme}')
                        if route=='admin_canvas_assets':
                            expect(page.get_by_text('Status',exact=True).last).to_be_visible()
                            expect(page.get_by_label('Active asset',exact=True)).to_be_checked()
                            for width in (1440,320):
                                page.set_viewport_size({'width':width,'height':1000})
                                name=page.locator('#catalog_label');dropdown=page.locator('[data-field=category] .ac-select-trigger')
                                self.assertAlmostEqual(name.bounding_box()['height'],dropdown.bounding_box()['height'],delta=1)
                        page.screenshot(path=str(self.artifacts/f'{route}-modal-{theme}.png'),animations='disabled')
                        if route=='admin_package_list':
                            page.set_viewport_size({'width':1440,'height':1000})
                            page.screenshot(path=str(self.artifacts/f'{route}-modal-desktop-{theme}.png'),animations='disabled')
                            page.get_by_role('tab',name='Inclusions',exact=False).click()
                            page.get_by_role('button',name='Add Service',exact=True).click()
                            remove=page.get_by_role('button',name='Remove inclusion',exact=True)
                            color=remove.evaluate('(node)=>getComputedStyle(node).color')
                            remove.hover()
                            self.assertEqual(remove.evaluate('(node)=>getComputedStyle(node).color'),color)
                            page.screenshot(path=str(self.artifacts/f'{route}-inclusions-{theme}.png'),animations='disabled')
                        page.get_by_role('button',name='Close dialog',exact=True).click()
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_offer_footer_and_controls_match_gallery_in_both_themes(self):
        from playwright.sync_api import expect,sync_playwright
        def styles(node):
            return node.evaluate('''node=>{const s=getComputedStyle(node);return {
                background:s.backgroundColor,color:s.color,border:s.borderColor,
                image:s.backgroundImage,width:s.width,height:s.height,
                after:getComputedStyle(node,'::after').content};}''')
        def checkbox_styles(node):
            # The visible check is a background image; inherited text color is unused.
            result=styles(node);result.pop('color');return result
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                for theme in ('light','dark'):
                    page.set_viewport_size({'width':1440,'height':650})
                    page.goto(self.live_server_url+reverse('admin_gallery'))
                    page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                    page.get_by_role('button',name='Add gallery image',exact=True).click()
                    expect(page.locator('[data-catalog-form]')).to_be_visible()
                    gallery_checkbox=checkbox_styles(page.get_by_label('Visible in gallery',exact=True))
                    field_background=styles(page.locator('#catalog_caption'))['background']
                    gallery_cancel=page.get_by_role('button',name='Cancel',exact=True)
                    gallery_cancel.hover();cancel_hover=styles(gallery_cancel)
                    close=page.get_by_role('button',name='Close dialog',exact=True)
                    close.hover();close_hover=styles(close)
                    close.click()
                    page.goto(self.live_server_url+reverse('admin_package_list'))
                    page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                    page.get_by_role('button',name='Add package',exact=True).click()
                    dialog=page.locator('[data-catalog-dialog]');form=page.locator('#offerEditorForm')
                    expect(form).to_be_visible()
                    save=page.get_by_role('button',name='Save Package',exact=True)
                    self.assertTrue(save.evaluate('node=>node.form.id==="offerEditorForm"&&!node.form.contains(node)&&!!node.closest(".ac-dialog-footer")'))
                    expect(dialog.locator('#offerSaveStatus')).to_have_count(0)
                    expect(dialog.locator('.ac-dialog-footer')).to_have_css('border-top-width','0px')
                    save.click()
                    expect(page.locator('#id_name')).to_have_attribute('aria-invalid','true')
                    expect(page.locator('#id_name')).to_have_css('background-color',field_background)
                    expect(page.locator('#offerErrorSummary')).to_have_css('border-left-width','0px')
                    expect(page.get_by_text('Short description (optional)',exact=True)).to_be_visible()
                    cancel=page.get_by_role('button',name='Cancel',exact=True)
                    cancel.hover()
                    for prop in ('background','color','border'):
                        self.assertEqual(styles(cancel)[prop],cancel_hover[prop],f'Cancel/{theme}/{prop}')
                    page.screenshot(path=str(self.artifacts/f'offer-validation-{theme}.png'),animations='disabled')
                    page.get_by_role('tab',name='Inclusions',exact=False).click()
                    add=page.get_by_role('button',name='Add Item',exact=True);add.hover()
                    for prop in ('background','color','border'):
                        self.assertEqual(styles(add)[prop],cancel_hover[prop],f'Add Item/{theme}/{prop}')
                    add.click()
                    picker=page.locator('#categoryPicker');expect(picker).to_be_visible()
                    close_picker=page.get_by_role('button',name='Close category picker',exact=True);close_picker.hover()
                    self.assertEqual(styles(close_picker)['background'],close_hover['background'])
                    page.screenshot(path=str(self.artifacts/f'offer-category-picker-{theme}.png'),animations='disabled')
                    page.locator('#categoryPickerOptions button').filter(has_text=self.canvas.name).click()
                    required=page.locator('[data-row-required]');required.check()
                    self.assertEqual(checkbox_styles(required),gallery_checkbox)
                    page.get_by_role('tab',name='Visibility',exact=True).click()
                    self.assertEqual(checkbox_styles(page.locator('#id_is_active')),gallery_checkbox)
                    page.screenshot(path=str(self.artifacts/f'offer-checkboxes-{theme}.png'),animations='disabled')
                    page.get_by_role('tab',name='Details',exact=True).click()
                    body=dialog.locator('[data-catalog-body]');footer=dialog.locator('.ac-dialog-footer')
                    for width in (1440,390,320):
                        page.set_viewport_size({'width':width,'height':560})
                        page.wait_for_timeout(150)
                        self.assertFalse(dialog.evaluate('node=>node.scrollWidth>node.clientWidth'))
                        start=footer.bounding_box()['y']
                        for position in (0,99999):
                            body.evaluate('(node,y)=>node.scrollTop=y',position)
                            self.assertAlmostEqual(footer.bounding_box()['y'],start,delta=1)
                            self.assertLessEqual(body.bounding_box()['y']+body.bounding_box()['height'],footer.bounding_box()['y']+1)
                            self.assertTrue(footer.evaluate('node=>{const b=node.getBoundingClientRect();return node.contains(document.elementFromPoint(b.x+b.width/2,b.bottom-5));}'))
                        page.screenshot(path=str(self.artifacts/f'offer-footer-{theme}-{width}.png'),animations='disabled')
                    page.get_by_role('button',name='Close dialog',exact=True).click()
                    expect(dialog).to_be_hidden()
                    page.get_by_role('button',name='View Package 11',exact=True).last.click()
                    expect(dialog.get_by_role('button',name='Close',exact=True)).to_be_visible()
                    expect(dialog.locator('#saveOfferButton')).to_have_count(0)
                    page.get_by_role('button',name='Close dialog',exact=True).click()
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_gallery_and_canvas_create_edit_footers_stay_visible_and_submit_async(self):
        from playwright.sync_api import expect,sync_playwright
        cases=[('admin_gallery','gallery-image','gallery image','Event 11','#catalog_caption'),
            ('admin_gallery','gallery-category','gallery category',self.category.name,'#catalog_name'),
            ('admin_canvas_assets','canvas-asset','canvas asset','Browser asset','#catalog_label'),
            ('admin_canvas_assets','canvas-category','canvas category',self.canvas.name,'#catalog_name')]
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            try:
                for route,resource,singular,name,field in cases:
                    page.goto(self.live_server_url+reverse(route)+'?tab='+resource)
                    for theme in ('light','dark'):
                        page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                        for action in ('create','edit'):
                            page.get_by_role('button',name=f'Add {singular}' if action=='create' else f'Edit {name}',exact=True).click()
                            dialog=page.locator('[data-catalog-dialog]');form=dialog.locator('[data-catalog-form]')
                            expect(form).to_be_visible()
                            footer=dialog.locator('.ac-dialog-footer');body=dialog.locator('[data-catalog-body]')
                            submit=footer.get_by_role('button',name='Add item' if action=='create' else 'Save changes',exact=True)
                            self.assertTrue(submit.evaluate('node=>node.form.id==="catalogEditorForm"&&!node.form.contains(node)'))
                            expect(footer).to_have_css('border-top-width','0px')
                            for width in (1440,390,320):
                                page.set_viewport_size({'width':width,'height':560});page.wait_for_timeout(80)
                                initial=footer.bounding_box()['y']
                                for position in (0,99999):
                                    body.evaluate('(node,y)=>node.scrollTop=y',position)
                                    self.assertAlmostEqual(footer.bounding_box()['y'],initial,delta=1)
                                    self.assertLessEqual(body.bounding_box()['y']+body.bounding_box()['height'],initial+1)
                                    self.assertLess(submit.bounding_box()['y']+submit.bounding_box()['height'],560)
                            if action=='create':
                                body.evaluate('node=>node.scrollTop=0');submit.click()
                                expect(form.locator('.catalog-field-error:not([hidden])').first).not_to_be_empty()
                                footer.get_by_role('button',name='Cancel',exact=True).click()
                            elif theme=='dark':
                                form.locator(field).fill(name+' revised');submit.click()
                                expect(dialog).to_be_hidden()
                                expect(page.get_by_text(name+' revised',exact=True)).to_be_visible()
                                self.assert_feedback(page,'saved successfully.')
                            else:
                                footer.get_by_role('button',name='Cancel',exact=True).click()
                            expect(dialog).to_be_hidden()
                self.assertEqual(len(documents),len(cases));self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_category_failure_feedback_preserves_draft_and_single_delete_can_retry(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url+reverse('admin_gallery')+'?tab=gallery-category')
                page.get_by_role('button',name='Add gallery category',exact=True).click()
                dialog=page.locator('[data-catalog-dialog]');form=dialog.locator('[data-catalog-form]')
                form.locator('#catalog_name').fill('Feedback category')
                action=form.get_attribute('action')
                page.route('**'+action,lambda route:route.fulfill(status=503,content_type='application/json',body='{"message":"Category could not be saved. Please try again."}'),times=1)
                page.get_by_role('button',name='Add item',exact=True).click()
                self.assert_feedback(page,'Category could not be saved.','error')
                expect(form.locator('#catalog_name')).to_have_value('Feedback category')
                expect(dialog).to_be_visible()
                page.route('**'+action,lambda route:route.fulfill(status=200,content_type='application/json',body='{"success":false,"message":"The save was not confirmed."}'),times=1)
                page.get_by_role('button',name='Add item',exact=True).click()
                self.assert_feedback(page,'The save was not confirmed.','error')
                expect(dialog).to_be_visible()
                page.evaluate("document.documentElement.dataset.theme='dark'")
                page.set_viewport_size({'width':390,'height':844})
                page.route('**/staff/gallery/?**',lambda route:route.abort())
                page.get_by_role('button',name='Add item',exact=True).click()
                expect(dialog).to_be_hidden()
                expect(page.locator('[data-list-feedback]')).not_to_be_empty()
                toast=self.assert_feedback(page,'Gallery category saved successfully.')
                self.assertEqual(toast.evaluate('el=>getComputedStyle(el).backgroundColor'),'rgb(22, 22, 22)')
                page.unroute('**/staff/gallery/?**')
                page.get_by_role('searchbox',name='Search library').fill('Feedback category')
                expect(page.locator('[data-catalog-row]')).to_have_count(1)
                page.get_by_role('button',name='Delete Feedback category',exact=True).click()
                confirm=page.locator('[data-delete-dialog]')
                page.route('**/delete/*/',lambda route:route.fulfill(status=503,content_type='application/json',body='{"message":"Deletion failed. Nothing was deleted."}'),times=1)
                confirm.locator('[data-delete-confirm]').click()
                self.assert_feedback(page,'Deletion failed. Nothing was deleted.','error')
                expect(confirm).to_be_visible()
                expect(page.locator('[data-catalog-row]')).to_have_count(1)
                confirm.locator('[data-delete-confirm]').click()
                expect(confirm).to_be_hidden()
                self.assert_feedback(page,'1 item(s) deleted.')
                expect(page.locator('[data-catalog-row]')).to_have_count(0)
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_offer_failure_feedback_preserves_fields_and_retries_without_reload(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url+reverse('admin_package_list'))
                page.get_by_role('button',name='Add package',exact=True).click()
                form=page.locator('#offerEditorForm')
                page.locator('#id_name').fill('Retry package')
                page.locator('#id_price').fill('1500')
                page.get_by_role('tab',name='Inclusions',exact=False).click()
                page.get_by_role('button',name='Add Service',exact=True).click()
                page.locator('[data-row-field=name]').fill('Setup and delivery')
                action=form.get_attribute('action')
                page.route('**'+action,lambda route:route.fulfill(status=503,content_type='application/json',body='{"message":"The service is temporarily unavailable."}'),times=1)
                page.get_by_role('button',name='Save Package',exact=True).click()
                self.assert_feedback(page,'The service is temporarily unavailable.','error')
                expect(page.locator('#offerErrorSummary')).to_have_text('The service is temporarily unavailable.')
                expect(page.locator('#id_name')).to_have_value('Retry package')
                expect(page.locator('#id_price')).to_have_value('1500')
                expect(page.locator('[data-row-field=name]')).to_have_value('Setup and delivery')
                expect(page.get_by_role('button',name='Save Package',exact=True)).to_be_enabled()
                page.route('**'+action,lambda route:route.abort(),times=1)
                page.get_by_role('button',name='Save Package',exact=True).click()
                self.assert_feedback(page,'The offer could not be saved. Your changes are still here.','error')
                expect(form).to_be_visible()
                expect(page.locator('#id_name')).to_have_value('Retry package')
                page.get_by_role('button',name='Save Package',exact=True).click()
                expect(page.locator('[data-catalog-dialog]')).to_be_hidden()
                self.assert_feedback(page,'Package saved successfully.')
                expect(page.get_by_text('Retry package',exact=True)).to_be_visible()
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_stale_search_and_network_failure_preserve_current_list(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();documents=[];errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url+reverse('admin_gallery'))
                page.evaluate('''()=>{
                    const original=window.fetch;
                    window.fetch=(...args)=>original(...args).then(async response=>{
                        if(String(args[0]).includes('q=missing-slow'))await new Promise(resolve=>setTimeout(resolve,700));
                        return response;
                    });
                }''')
                search=page.get_by_role('searchbox',name='Search library')
                search.fill('missing-slow');page.wait_for_timeout(350);search.fill('Event')
                expect(page.locator('[data-catalog-row]')).to_have_count(8)
                page.wait_for_timeout(1000);expect(page.locator('[data-catalog-row]')).to_have_count(8)
                page.route('**/staff/gallery/?**',lambda route:route.abort())
                search.fill('network-down')
                expect(page.locator('[data-list-feedback]')).not_to_be_empty()
                expect(page.locator('[data-catalog-row]')).to_have_count(8)
                page.unroute('**/staff/gallery/?**')
                page.get_by_role('button',name='Clear search',exact=True).click()
                expect(page.get_by_role('searchbox',name='Search library')).to_have_value('')
                expect(page.locator('[data-list-feedback]')).to_be_empty()
                self.assertEqual(documents,[self.live_server_url+reverse('admin_gallery')]);self.assertEqual(errors,[])
            finally:context.close();browser.close()
