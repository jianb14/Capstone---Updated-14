# Gallery categories and packages

Gallery photos have an event category and an optional link to an existing package from Admin Packages. Categories such as Birthday and Baptism remain separate from package names.

In **Admin → Gallery → Photos**, add or edit a photo and choose its category and package. A batch upload applies the same selection to every uploaded photo. Use **No specific package** for general/custom setups. The admin list supports combined category/package filters, package-name search, and a filter for photos without an assignment.

On the client Gallery page, categories and packages share one filter bar and the same pill-button style. Choose a category to see that event type, or a package to see its photos across event types. All Projects resets the selection. Only one filter is active at a time. Package options come only from active packages with visible photos. Photos show their package badge, and the image modal includes the category, package, and optional caption.

Migration `0117_galleryimage_package` adds a nullable package reference. Existing photos remain visible under **All Projects** until assigned through Edit. Deactivating a package removes its public filter and badge while retaining its gallery photos; deleting a package clears the assignment and preserves the photos. Existing inactive assignments remain available for admin editing.

Verification covers assignment and validation, batch upload, editing without re-uploading, combined filters, unassigned photos, inactive/deleted packages, authorization/CSRF, responsive controls, image-modal metadata, and the existing masonry/lightbox behavior. Run browser checks with `RUN_GALLERY_BROWSER=1`; the existing admin catalog browser checks use `RUN_CATALOG_BROWSER=1`.
