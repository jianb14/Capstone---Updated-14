"""Check the first painted focus frames with normal animation enabled."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase


@skipUnless(os.environ.get('RUN_PACKAGES_BROWSER') == '1', 'Optional Playwright verification')
class ClientFocusFrameTests(SimpleTestCase):
    def test_booking_focus_and_errors_do_not_flash_between_colors(self):
        from playwright.sync_api import sync_playwright

        css_root = Path(settings.BASE_DIR) / 'static/css'
        css = '\n'.join((css_root / name).read_text(encoding='utf-8') for name in (
            'base.css', 'client_booking.css', 'booking_form_components.css',
            'booking_workspace.css', 'client_form_focus.css',
        ))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page(reduced_motion='no-preference')
                page.route('**/*', lambda route: route.abort())
                page.set_content('<html><style>' + css + '</style><body class="booking-page">'
                    '<div id="bookingModalOverlay"><form id="bookingForm">'
                    '<div class="form-group"><input id="field"><textarea id="notes"></textarea>'
                    '<div class="custom-select-container"><button type="button" '
                    'class="custom-select-trigger" id="dropdown">Select event</button></div></div>'
                    '</form></div></body></html>')
                for theme in ('light', 'dark'):
                    page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
                    for invalid in (False, True):
                        page.evaluate('''invalid=>{
                            document.querySelector('.form-group').classList.toggle('has-error',invalid);
                            document.querySelectorAll('input,textarea,button').forEach(el=>el.setAttribute('aria-invalid',String(invalid)));
                        }''', invalid)
                        border = ('rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)') if invalid else (
                            'rgb(206, 206, 206)' if theme == 'light' else 'rgb(74, 74, 74)')
                        ring = ('rgba(184, 53, 60, 0.4)' if theme == 'light' else 'rgba(241, 145, 145, 0.4)') if invalid else (
                            'rgba(105, 105, 105, 0.4)' if theme == 'light' else 'rgba(153, 153, 153, 0.45)')
                        for selector in ('#field', '#notes', '#dropdown'):
                            frames = page.locator(selector).evaluate('''async el=>{
                                el.blur(); void el.offsetWidth; el.focus();
                                const read=()=>{const style=getComputedStyle(el);return {
                                    border:style.borderColor,ring:style.outlineColor,width:style.outlineWidth,
                                    shadow:style.boxShadow};};
                                const frames=[read()];
                                for(let i=0;i<20;i++){
                                    await new Promise(requestAnimationFrame);frames.push(read());
                                }
                                el.blur();return frames;
                            }''')
                            self.assertTrue(all(frame == {'border': border, 'ring': ring, 'width': '2px', 'shadow': 'none'}
                                for frame in frames), f'{theme}, invalid={invalid}, {selector}: {frames}')
            finally:
                browser.close()
