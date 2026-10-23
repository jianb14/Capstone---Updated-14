"""Numbering and safe text behavior for real browser list rendering."""
import html
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
class AiMarkdownBrowserTests(SimpleTestCase):
    def test_numbered_packages_nested_details_and_distinct_procedures(self):
        from playwright.sync_api import sync_playwright, expect
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                page = browser.new_page()
                page.set_content('<main></main>')
                page.add_script_tag(path=str(Path(settings.BASE_DIR) / 'static/js/ai_markdown.js'))

                def render(text):
                    page.evaluate('(text) => document.querySelector("main").innerHTML = window.renderAiMarkdown(text)', html.escape(text))

                for numbers in ((1, 1, 1), (1, 2, 3)):
                    for indentation in ('', '  ', '    '):
                        with self.subTest(numbers=numbers, indentation=len(indentation)):
                            render('\n\n'.join(f'{number}. **Package {name}**\n{indentation}- Panel\n{indentation}- Balloons'
                                for number, name in zip(numbers, ('1-A', '1-B', '2'))))
                            expect(page.locator('main > ol')).to_have_count(1)
                            expect(page.locator('main > ol > li')).to_have_count(3)
                            expect(page.locator('main > ol > li > strong')).to_have_text(['Package 1-A', 'Package 1-B', 'Package 2'])
                            expect(page.locator('main > ol > li > ul')).to_have_count(3)
                            expect(page.locator('main > ol > li > ul > li')).to_have_count(6)
                            self.assertEqual(page.locator('main > ol').evaluate('(el) => el.start'), 1)

                render('3. Continue booking\n   1. Pick a date\n   1. Pick a time\n4. Confirm\n\nPayment steps:\n\n1. Choose a method\n2. Submit proof')
                expect(page.locator('main > ol')).to_have_count(2)
                expect(page.locator('main > ol').first.locator(':scope > li')).to_have_count(2)
                expect(page.locator('main > ol > li > ol > li')).to_have_count(2)
                self.assertEqual(page.locator('main > ol').first.evaluate('(el) => el.start'), 3)
                self.assertEqual(page.locator('main > ol').last.evaluate('(el) => el.start'), 1)

                render('**Sofia** and _gold_.\n\n<img src=x onerror=alert(1)>\n<script>alert(1)</script>')
                expect(page.locator('main strong')).to_have_text('Sofia')
                expect(page.locator('main em')).to_have_text('gold')
                expect(page.locator('main img, main script')).to_have_count(0)
                expect(page.locator('main')).to_contain_text('<img src=x onerror=alert(1)>')
            finally:
                browser.close()
