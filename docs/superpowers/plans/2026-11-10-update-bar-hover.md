# Customer update bar hover and early restoration

User requested underline only on action hover, a square close hover, and no apparent notification restart between pages. Scope is the existing bar and its startup timing.

Diagnosis: action underline was unconditional and all button hovers inherited a background; close hit area was 32x44 (26x44 on mobile). Public navbar links load whole documents; the carried bar was recreated by deferred scripts after the document parsed. Account routes already retain their shell.

- [x] Reproduce action styling failure with real computed styles, then change only the action and close hover rules. Retain 44x44 close hit area with a subtle 32x32 square visual hover.
- [x] Reproduce missing early bar with a browser assertion injected before `</body>` on a real navbar destination. Initialize existing bar scripts immediately after navbar and restore the handoff synchronously before parsing page content. Preserve remaining time, modal guards, delivery receipts and grouped state.
- [x] Run focused backend/browser checks and independent read-only review; synchronize served assets and document results.

Result: 34 focused tests passed in 104.044s, including six live-browser tests. Independent review found no blockers. Django checks, JavaScript syntax, whitespace and served-asset equality checks pass.

No global navigation replacement is included: a full document navigation necessarily recreates the DOM. This correction removes waiting for page parsing/fetch before rendering the carried bar, without claiming the site has become a single-page application. Existing workspace edits are preserved.
