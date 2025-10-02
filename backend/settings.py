# from python_decouple import config, Csv
from pathlib import Path
import os
from datetime import timedelta
from decouple import config
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",  # For local development with your Vite/React/Vue app
    "http://127.0.0.1:5173",
    "https://winnersclubx.netlify.app",  # A common alternative for local host
    "https://mlm-pmif.onrender.com",
    # Add your deployed frontend URL here when you have one (e.g., "https://your-frontend-domain.com")
]
# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-5*(zbso#o2n0ur6wt1-2ku#r^!ev0m9=ob8y67d1u37522s@rr'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True
#DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = ["mlm-pmif.onrender.com", '127.0.0.1:8000', '127.0.0.1', 'localhost', 'https://mlm-oiat.onrender.com']


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt.token_blacklist',
    'rest_framework_simplejwt',
    'cloudinary_storage',
    'cloudinary',
    'corsheaders',
    'profiles',
    'users',
    'level',
    'reports',
    'notifications',
    'adminreport'  
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware', 
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'neondb',
        'USER': 'neondb_owner',
        'PASSWORD': 'npg_OAZPrjz8Mp0w',
        'HOST': 'ep-floral-resonance-adgcweml-pooler.c-2.us-east-1.aws.neon.tech',
        'PORT': '5432',
        'OPTIONS': {
            'sslmode': 'require',
        },
        'CONN_MAX_AGE': 600,
    }
}

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': config('DB_NAME'),
#         'USER': config('DB_USER'),
#         'PASSWORD': config('DB_PASSWORD'),
#         'HOST': config('DB_HOST'),
#         'PORT': config('DB_PORT', cast=int),
#         'OPTIONS': {
#             'sslmode': 'require',
#         },
#         'CONN_MAX_AGE': 600,
#     }
# }


# ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())



# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = os.environ.get('EMAIL_HOST')
# EMAIL_PORT = os.environ.get('EMAIL_PORT')
# # EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS') == 'True'
# EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
# EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
# DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL')
# EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
# EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool) # <-- Ensures no conflict with TLS

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'zecserbusiness@gmail.com'
EMAIL_HOST_PASSWORD = 'lfqx aljl srkx ttur'
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# # Email Settings
# EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
# EMAIL_HOST = config("EMAIL_HOST")
# EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
# EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)

# # These will be pulled from .env locally, and from Render Env Vars in production
# EMAIL_HOST_USER = config("EMAIL_HOST_USER") 
# EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD") 

# DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER)
# Email Settings (Consolidated and Corrected)

# EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
# EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
# EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
# EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
# EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "zecserbusiness@gmail.com")
# EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "wlsx ausq sxkm qxhr")
# DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@example.com")

# RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_RMYgDd9o5n2SOD")
# RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "7rV1tuKez0XP6x6Ue8euXjBs")


# Cloudinary Settings
CLOUDINARY_CLOUD_NAME = "dunlntdy3"
CLOUDINARY_API_KEY = "454341219174761"
CLOUDINARY_API_SECRET = "NIhM0PgdElTPwPg6dZr2LQmBprE"
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': 'dunlntdy3',
    'API_KEY': '454341219174761',
    'API_SECRET': 'NIhM0PgdElTPwPg6dZr2LQmBprE',
}
# Set Cloudinary as the default storage backend for media files
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# ------------------ STATIC FILES ------------------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
# MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

# STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = "users.CustomUser"

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 12,
}


SIMPLE_JWT = {
    
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1), 

    'REFRESH_TOKEN_LIFETIME': timedelta(days=2),  

}

# RAZORPAY_KEY_ID ='rzp_test_nGk98ngKrPHf2J'
# RAZORPAY_KEY_SECRET ='Gh7CpAcNtrKTQsE35rLEAm19'
RAZORPAY_KEY_ID='rzp_test_RMYgDd9o5n2SOD'
RAZORPAY_KEY_SECRET='7rV1tuKez0XP6x6Ue8euXjBs'


# OTP settings for email verification before registration
OTP_EXPIRY_MINUTES = 10     # OTP validity in minutes (configurable)
OTP_LENGTH = 6              # number of digits in OTP
OTP_MAX_ATTEMPTS = 5        # max verification attempts allowed
