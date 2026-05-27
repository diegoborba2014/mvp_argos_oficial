"""
Extensões Flask inicializadas sem app context para evitar imports circulares.
Importar em app.py para registrar com init_app(); importar em routes para usar decorators.
"""
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# S-13: Proteção CSRF para todos os formulários HTML
csrf = CSRFProtect()

# S-14: Rate limiting — limite configurado por view, default vazio (sem limite global)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",   # suficiente para 1 dyno Railway; trocar por Redis se escalar
)
