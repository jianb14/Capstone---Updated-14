# Balloorina error pages

Implement the user's approved custom 403, 404 and 500 pages using the existing monochrome Balloorina branding. All visible copy is English. The user requested careful testing and authorized implementation in the current project.

## Approach

Use Django error handlers and one shared standalone template. A small response middleware also styles existing HTML 403 responses, since many views return those directly. Editing every permission check would be larger and risk changing authorization; inheriting the normal layout would introduce database and notification dependencies during failures.

## Behavior and design

- Large error number, Balloorina logo, clear heading, explanation and Back to Home link; responsive desktop and mobile layouts, saved light/dark theme and keyboard focus.
- 403 offers Sign In; 404 offers Explore Services. A GET/HEAD 500 may offer Try Again as a GET link; unsafe submissions must never be replayed automatically.
- Preserve status codes, headers and existing JSON/AJAX response bodies. Do not expose exception messages, paths, CSRF reasons or account details.
- Error handlers render without request context processors or database access. Keep CSS inline, use local assets with system font fallbacks, and avoid animation or remote dependencies.
- Keep DEBUG behavior unchanged. Production handlers are verified with DEBUG=False. No public routes that deliberately crash the app.

## Verification

Test real exception handling, direct forbidden responses, CSRF rejection, API preservation, error rendering without database/context processors, and safe navigation after POST. Run Django checks and the full test suite; inspect and exercise each error page at desktop, tablet and narrow mobile widths in both themes.
