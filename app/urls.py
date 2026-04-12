from django.urls import path
from .views import (
    HomePageView,
    AboutPageView,
    ServicesPageView,
    GuidelinesPageView,
    PackagePageView,
    GalleryPageView,
    
    register,
    verify_email,
    user_login,
    user_logout,
    dashboard,
    customer_profile,
    my_profile,
    my_reviews,
    change_password,
    admin_profile,
    forgot_password_request,
    password_reset_confirm,
    report_concern,

    create_booking,
    edit_booking,
    delete_booking,
    view_booking,
    submit_review,
    edit_review,
    delete_review,

    request_cancel_booking,
    admin_cancel_action,
    request_edit_booking,
    admin_edit_action,

    admin_booking_list,
    admin_booking_detail,
    admin_booking_action,

    admin_user_list,
    admin_user_edit,
    admin_user_toggle_active,
    admin_user_delete,
    admin_audit_log_list,
    
    admin_package_create,
    admin_package_edit,
    admin_package_delete,
    admin_package_list,
    admin_package_detail,
    admin_service_charge_update,
    package,
    
    admin_addon_create,
    admin_addon_delete,
    admin_addon_edit,
    admin_addon_detail,

    admin_additional_create,
    admin_additional_delete,
    admin_additional_edit,
    admin_additional_detail,
    admin_reports,
    admin_concern_update,
    admin_calendar,
    mark_notifications_read,
    hide_notification,

    chat_api,
    chat_history,
    chat_sessions,
    chat_clear,
    booking_page,
    reviews_page,
    like_review,
    mark_customer_notification_read,
    clear_all_notifications,
    design_canvas_page,
    my_designs_page,
    select_design_type,
    save_user_design,
    rename_user_design,
    delete_user_design,
    admin_gallery,
    admin_gallery_category_create,
    admin_gallery_category_edit,
    admin_gallery_category_delete,
    admin_gallery_image_create,
    admin_gallery_image_detail,
    admin_gallery_image_edit,
    admin_gallery_image_delete,
    admin_canvas_assets,
    admin_canvas_category_create,
    admin_canvas_category_edit,
    admin_canvas_category_delete,
    admin_canvas_label_create,
    admin_canvas_label_edit,
    admin_canvas_label_delete,
    admin_canvas_asset_create,
    admin_canvas_asset_detail,
    admin_canvas_asset_edit,
    admin_canvas_asset_delete,
)

urlpatterns = [
    path('', HomePageView.as_view(), name='home'),
    path('about/', AboutPageView.as_view(), name='about'),
    path('services/', ServicesPageView.as_view(), name='services'),
    path('guidelines/', GuidelinesPageView.as_view(), name='guidelines'),
    path('package/', PackagePageView.as_view(), name='package'),
    path('gallery/', GalleryPageView.as_view(), name='gallery'),
    
    # Custom Design Dashboard
    path('my-designs/', my_designs_page, name='my_designs'),
    path('select-design/', select_design_type, name='select_design_type'),
    path('my-designs/save/', save_user_design, name='save_user_design'),
    path('my-designs/rename/<int:id>/', rename_user_design, name='rename_user_design'),
    path('my-designs/delete/<int:id>/', delete_user_design, name='delete_user_design'),

    path('register/', register, name='register'),
    path('verify-email/<uidb64>/<token>/', verify_email, name='verify_email'),
    path('login/', user_login, name='login'),
    path('forgot-password/', forgot_password_request, name='forgot_password'),
    path('reset-password/<uidb64>/<token>/', password_reset_confirm, name='password_reset_confirm'),
    path('logout/', user_logout, name='logout'),

    path('dashboard/', dashboard, name='dashboard'),
    path('customer/', customer_profile, name='customer_profile'), # This will act as My Bookings
    path('my-profile/', my_profile, name='my_profile'),
    path('my-reviews/', my_reviews, name='my_reviews'),
    path('report-concern/', report_concern, name='report_concern'),
    path('change-password/', change_password, name='change_password'),
    path('admin-profile/', admin_profile, name='admin_profile'),
    path('reviews/', reviews_page, name='reviews'),
    path('reviews/<int:review_id>/like/', like_review, name='like_review'),
    path('reviews/<int:review_id>/edit/', edit_review, name='edit_review'),
    path('reviews/<int:review_id>/delete/', delete_review, name='delete_review'),
    # Booking
    path('booking/', booking_page, name='booking_page'),
    path('booking/create/', create_booking, name='create_booking'),
    path('booking/<int:id>/', view_booking, name='view_booking'),
    path('booking/<int:id>/edit/', edit_booking, name='edit_booking'),
    path('booking/<int:id>/delete/', delete_booking, name='delete_booking'),
    path('booking/<int:id>/review/', submit_review, name='submit_review'),
    path('design/', design_canvas_page, name='design_canvas'),

    # Admin Booking Approval
    path('staff/bookings/', admin_booking_list, name='admin_booking_list'),
    path('staff/bookings/<int:id>/view/', admin_booking_detail, name='admin_booking_detail'),
    path('staff/bookings/<int:id>/<str:action>/', admin_booking_action, name='admin_booking_action'),

    path('booking/<int:id>/cancel/', request_cancel_booking, name='request_cancel_booking'),
    path('staff/cancel-requests/<int:id>/<str:action>/', admin_cancel_action, name='admin_cancel_action'),

    path('booking/<int:id>/request-edit/', request_edit_booking, name='request_edit_booking'),
    path('staff/bookings/<int:id>/edit/<str:action>/', admin_edit_action, name='admin_edit_action'),

    # Admin User Management
    path('staff/users/', admin_user_list, name='admin_user_list'),
    path('staff/users/<int:id>/edit/', admin_user_edit, name='admin_user_edit'),
    path('staff/users/<int:id>/toggle/', admin_user_toggle_active, name='admin_user_toggle'),
    path('staff/users/<int:id>/delete/', admin_user_delete, name='admin_user_delete'),
    
    # Audit Log
    path('staff/audit-log/', admin_audit_log_list, name='admin_audit_log'),

    # Reports
    path('staff/reports/', admin_reports, name='admin_reports'),
    path('staff/reports/concerns/<int:id>/update/', admin_concern_update, name='admin_concern_update'),

    # Admin Calendar & Notifications
    path('staff/calendar/', admin_calendar, name='admin_calendar'),
    path('staff/notifications/read/', mark_notifications_read, name='mark_notifications_read'),
    path('staff/notifications/<int:id>/hide/', hide_notification, name='hide_notification'),

    # Admin Package Management
    path('staff/packages/', admin_package_list, name='admin_package_list'),
    path('staff/packages/create/', admin_package_create, name='admin_package_create'),
    path('staff/packages/<int:id>/edit/', admin_package_edit, name='admin_package_edit'),
    path('staff/packages/<int:id>/delete/', admin_package_delete, name='admin_package_delete'),
    path('staff/packages/<int:id>/view/', admin_package_detail, name='admin_package_detail'),
    path('staff/packages/service-charge/', admin_service_charge_update, name='admin_service_charge_update'),
    path('packages/', package, name='package'),
    
    # ADDONS
    path('staff/addons/create/', admin_addon_create, name='admin_addon_create'),
    path('staff/addons/<int:id>/edit/', admin_addon_edit, name='admin_addon_edit'),
    path('staff/addons/<int:id>/delete/', admin_addon_delete, name='admin_addon_delete'),
    path('staff/addons/<int:id>/view/', admin_addon_detail, name='admin_addon_detail'),

    # ADDITIONAL ONLY
    path('staff/additional/create/', admin_additional_create, name='admin_additional_create'),
    path('staff/additional/<int:id>/edit/', admin_additional_edit, name='admin_additional_edit'),
    path('staff/additional/<int:id>/delete/', admin_additional_delete, name='admin_additional_delete'),
    path('staff/additional/<int:id>/view/', admin_additional_detail, name='admin_additional_detail'),

    # AI Features
    path('api/chat/', chat_api, name='chat_api'),
    path('api/chat/history/', chat_history, name='chat_history'),
    path('api/chat/sessions/', chat_sessions, name='chat_sessions'),
    path('api/chat/clear/', chat_clear, name='chat_clear'),

    # Customer Notifications
    path('notifications/<int:id>/read/', mark_customer_notification_read, name='mark_customer_notification_read'),
    path('notifications/clear-all/', clear_all_notifications, name='clear_all_notifications'),

    # Admin Gallery Management
    path('staff/gallery/', admin_gallery, name='admin_gallery'),
    path('staff/gallery/category/create/', admin_gallery_category_create, name='admin_gallery_category_create'),
    path('staff/gallery/category/<int:id>/edit/', admin_gallery_category_edit, name='admin_gallery_category_edit'),
    path('staff/gallery/category/<int:id>/delete/', admin_gallery_category_delete, name='admin_gallery_category_delete'),
    path('staff/gallery/image/create/', admin_gallery_image_create, name='admin_gallery_image_create'),
    path('staff/gallery/image/<int:id>/view/', admin_gallery_image_detail, name='admin_gallery_image_detail'),
    path('staff/gallery/image/<int:id>/edit/', admin_gallery_image_edit, name='admin_gallery_image_edit'),
    path('staff/gallery/image/<int:id>/delete/', admin_gallery_image_delete, name='admin_gallery_image_delete'),

    # Admin Canvas Assets Management
    path('staff/canvas-assets/', admin_canvas_assets, name='admin_canvas_assets'),
    path('staff/canvas-assets/category/create/', admin_canvas_category_create, name='admin_canvas_category_create'),
    path('staff/canvas-assets/category/<int:id>/edit/', admin_canvas_category_edit, name='admin_canvas_category_edit'),
    path('staff/canvas-assets/category/<int:id>/delete/', admin_canvas_category_delete, name='admin_canvas_category_delete'),
    path('staff/canvas-assets/label/create/', admin_canvas_label_create, name='admin_canvas_label_create'),
    path('staff/canvas-assets/label/<int:id>/edit/', admin_canvas_label_edit, name='admin_canvas_label_edit'),
    path('staff/canvas-assets/label/<int:id>/delete/', admin_canvas_label_delete, name='admin_canvas_label_delete'),
    path('staff/canvas-assets/asset/create/', admin_canvas_asset_create, name='admin_canvas_asset_create'),
    path('staff/canvas-assets/asset/<int:id>/view/', admin_canvas_asset_detail, name='admin_canvas_asset_detail'),
    path('staff/canvas-assets/asset/<int:id>/edit/', admin_canvas_asset_edit, name='admin_canvas_asset_edit'),
    path('staff/canvas-assets/asset/<int:id>/delete/', admin_canvas_asset_delete, name='admin_canvas_asset_delete'),
]
