from django.contrib import admin

# Register your models here.
from .models import *
# Register your models here.

admin.site.register(CustomUser)
admin.site.register(UserAccountDetails)
admin.site.register(Payment)
admin.site.register(AdminAccountDetails)

# # Register EmailVerification so admins can view/clean up expired/abused OTPs
# try:
#     admin.site.register(EmailVerification)
# except Exception:
#     # avoid failing if already registered
#     pass