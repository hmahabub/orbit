"""Orbit ERP settings — a lean order-to-supplier-PO workflow for a garment buying house."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path):
    """Read KEY=VALUE lines from a .env file into the environment. Variables
    already set in the real environment win, so a server can override it."""
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(BASE_DIR / '.env')


def env_list(name, default):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


SECRET_KEY = os.environ.get('ORBIT_SECRET_KEY', 'django-insecure-orbit-dev-key-change-me-in-production')
DEBUG = os.environ.get('ORBIT_DEBUG', '1') == '1'
ALLOWED_HOSTS = env_list('ORBIT_ALLOWED_HOSTS', 'localhost,127.0.0.1,orbit.asgroupbd.com')
# Forms posted from the live site over HTTPS pass Django's CSRF origin check.
CSRF_TRUSTED_ORIGINS = env_list('ORBIT_CSRF_TRUSTED_ORIGINS', 'https://orbit.asgroupbd.com')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'apps.orders',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # serves /static/ under any web server
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'config.wsgi.application'

# Database, from .env. SQLite needs only a file name; PostgreSQL and MySQL
# need their driver installed (psycopg / mysqlclient) and the connection details.
DB_ENGINES = {
    'sqlite': 'django.db.backends.sqlite3',
    'postgresql': 'django.db.backends.postgresql',
    'mysql': 'django.db.backends.mysql',
}
DB_ENGINE = os.environ.get('ORBIT_DB_ENGINE', 'sqlite').strip().lower() or 'sqlite'
if DB_ENGINE not in DB_ENGINES:
    raise ValueError(f'ORBIT_DB_ENGINE must be one of {", ".join(DB_ENGINES)}, not "{DB_ENGINE}".')
if DB_ENGINE == 'sqlite':
    DATABASES = {'default': {
        'ENGINE': DB_ENGINES['sqlite'],
        'NAME': BASE_DIR / os.environ.get('ORBIT_DB_NAME', 'db.sqlite3'),  # relative to the project folder
    }}
else:
    DATABASES = {'default': {
        'ENGINE': DB_ENGINES[DB_ENGINE],
        'NAME': os.environ.get('ORBIT_DB_NAME', 'orbit'),
        'USER': os.environ.get('ORBIT_DB_USER', ''),
        'PASSWORD': os.environ.get('ORBIT_DB_PASSWORD', ''),
        'HOST': os.environ.get('ORBIT_DB_HOST', 'localhost'),
        'PORT': os.environ.get('ORBIT_DB_PORT', ''),
    }}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Also serve straight from static/, so CSS/JS work even if collectstatic
# hasn't been run after a deploy.
WHITENOISE_USE_FINDERS = True

DATE_INPUT_FORMATS = ['%Y-%m-%d']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Letterhead on the Excel supplier PO and cost sheet, from .env.
COMPANY_NAME = os.environ.get('ORBIT_COMPANY_NAME', 'Orbit')
COMPANY_ADDRESS = os.environ.get('ORBIT_COMPANY_ADDRESS', '')
COMPANY_LOGO = BASE_DIR / os.environ.get('ORBIT_COMPANY_LOGO', 'static/image/orbit_logo.png')

MESSAGE_TAGS = {40: 'danger'}  # messages.ERROR -> Bootstrap's alert-danger
