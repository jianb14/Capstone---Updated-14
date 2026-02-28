from django.urls import path
from .views import (
    HomePageView,
    AboutPageView,
    ServicesPageView,
    PackagePageView,
    GalleryPageView,
    
    register,
    user_login,
    user_logout,
    dashboard,
    customer_profile,
    change_password,
    admin_profile,

    create_booking,
    edit_booking,
    delete_booking,
    view_booking,

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

    chat_api,
    chat_history,
    chat_sessions,
    chat_clear,
)

urlpatterns = [
    path('', HomePageView.as_view(), name='home'),
    path('about/', AboutPageView.as_view(), name='about'),
    path('services/', ServicesPageView.as_view(), name='services'),
    path('package/', PackagePageView.as_view(), name='package'),
    path('gallery/', GalleryPageView.as_view(), name='gallery'),

    path('register/', register, name='register'),
    path('login/', user_login, name='login'),
    path('logout/', user_logout, name='logout'),

    path('dashboard/', dashboard, name='dashboard'),
    path('customer/', customer_profile, name='customer_profile'),
    path('change-password/', change_password, name='change_password'),
    path('admin-profile/', admin_profile, name='admin_profile'),

    # Booking CRUD
    path('booking/create/', create_booking, name='create_booking'),
    path('booking/<int:id>/', view_booking, name='view_booking'),
    path('booking/<int:id>/edit/', edit_booking, name='edit_booking'),
    path('booking/<int:id>/delete/', delete_booking, name='delete_booking'),

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

    # Admin Package Management
    path('staff/packages/', admin_package_list, name='admin_package_list'),
    path('staff/packages/create/', admin_package_create, name='admin_package_create'),
    path('staff/packages/<int:id>/edit/', admin_package_edit, name='admin_package_edit'),
    path('staff/packages/<int:id>/delete/', admin_package_delete, name='admin_package_delete'),
    path('staff/packages/<int:id>/view/', admin_package_detail, name='admin_package_detail'),
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

]
