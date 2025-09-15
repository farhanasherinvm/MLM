from django.contrib import admin
from . models import Level,UserLevel,LevelPayment
# Register your models here.
admin.site.register(Level)
admin.site.register(UserLevel)
admin.site.register(LevelPayment)
