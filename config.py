"""
Módulo de configuración para el agente de voz María.
Maneja la carga y validación de variables de entorno.
"""

import os
import logging
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator

# CRÍTICO: Cargar variables de entorno ANTES que cualquier otra importación
from dotenv import load_dotenv
load_dotenv()

# Asegurar que las variables críticas estén disponibles para el SDK de LiveKit
if not os.getenv("LIVEKIT_API_KEY"):
    # Cargar explícitamente desde dotenv si no están en el entorno
    from dotenv import dotenv_values
    env_vars = dotenv_values('.env')
    for key, value in env_vars.items():
        if value is not None:
            os.environ[key] = value

class AppSettings(BaseSettings):
    """
    Configuración de la aplicación cargada desde variables de entorno.
    """
    # LiveKit
    livekit_url: str = Field(..., env='LIVEKIT_URL')
    livekit_api_key: str = Field(..., env='LIVEKIT_API_KEY')
    livekit_api_secret: str = Field(..., env='LIVEKIT_API_SECRET')
    livekit_agent_port: int = Field(8000, env='LIVEKIT_AGENT_PORT')

    # Backend API
    api_base_url: str = Field('https://mar-ia-7s6y.onrender.com', env='API_BASE_URL')

    # OpenAI
    openai_api_key: str = Field(..., env='OPENAI_API_KEY')
    openai_model: str = Field('gpt-4o-mini', env='OPENAI_MODEL')

    # Cartesia TTS
    cartesia_api_key: str = Field(..., env='CARTESIA_API_KEY')
    cartesia_model: str = Field('sonic-2', env='CARTESIA_MODEL')
    cartesia_voice_id: str = Field('5c5ad5e7-1020-476b-8b91-fdcbe9cc313c', env='CARTESIA_VOICE_ID')
    cartesia_language: str = Field('es', env='CARTESIA_LANGUAGE')
    cartesia_speed: float = Field(1.0, env='CARTESIA_SPEED')
    cartesia_emotion: Optional[str] = Field(None, env='CARTESIA_EMOTION')

    # Deepgram STT
    deepgram_api_key: str = Field(..., env='DEEPGRAM_API_KEY')
    deepgram_model: str = Field('nova-2', env='DEEPGRAM_MODEL')

    @field_validator('livekit_agent_port', mode='before')
    def _clean_port(cls, v):
        # Elimina cualquier comentario tras '#' y espacios
        if isinstance(v, str):
            v = v.split('#', 1)[0].strip()
        return v

    class Config:
        env_file = '.env'
        case_sensitive = False
        extra = 'ignore'

class DefaultSettings:
    """
    Configuración por defecto para desarrollo cuando falla la validación de AppSettings.
    """
    def __init__(self):
        self.livekit_url = os.getenv('LIVEKIT_URL', 'wss://localhost:7880')
        self.livekit_api_key = os.getenv('LIVEKIT_API_KEY', '')
        self.livekit_api_secret = os.getenv('LIVEKIT_API_SECRET', '')
        self.livekit_agent_port = int(os.getenv('LIVEKIT_AGENT_PORT', '7880'))
        self.api_base_url = os.getenv('API_BASE_URL', 'https://mar-ia-7s6y.onrender.com')
        self.openai_api_key = os.getenv('OPENAI_API_KEY', '')
        self.openai_model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
        self.cartesia_api_key = os.getenv('CARTESIA_API_KEY', '')
        self.cartesia_model = os.getenv('CARTESIA_MODEL', 'sonic-2')
        self.cartesia_voice_id = os.getenv('CARTESIA_VOICE_ID', '5c5ad5e7-1020-476b-8b91-fdcbe9cc313c')
        self.cartesia_language = os.getenv('CARTESIA_LANGUAGE', 'es')
        self.cartesia_speed = float(os.getenv('CARTESIA_SPEED', '1.0'))
        self.cartesia_emotion = os.getenv('CARTESIA_EMOTION')
        self.deepgram_api_key = os.getenv('DEEPGRAM_API_KEY', '')
        self.deepgram_model = os.getenv('DEEPGRAM_MODEL', 'nova-2')

def create_settings():
    """
    Factory function para crear la configuración con manejo de errores.
    
    Returns:
        Instancia de AppSettings o DefaultSettings según la validación.
    """
    try:
        settings = AppSettings()
        logging.info("✅ Configuración cargada exitosamente")
        logging.info(f"🔗 LiveKit URL: {settings.livekit_url}")
        logging.info(f"🌐 API Base URL: {settings.api_base_url}")
        logging.info(f"🤖 OpenAI Model: {settings.openai_model}")
        logging.info(f"🎵 Cartesia Voice ID: {settings.cartesia_voice_id}")
        logging.info("🎭 Usando avatar CSS en frontend")
        return settings
    except Exception as e:
        logging.error(f"❌ Error cargando configuración: {e}")
        settings = DefaultSettings()
        logging.warning("⚠️ Usando configuración por defecto debido a errores de validación")
        return settings

# Constantes globales
DEFAULT_TASK_TIMEOUT = 30.0  # Segundos para timeout de tareas como TTS
DEFAULT_DATA_PUBLISH_TIMEOUT = 5.0  # Segundos para timeout al publicar datos por DataChannel
SAVE_MESSAGE_MAX_RETRIES = 3  # Número máximo de reintentos para guardar mensajes
SAVE_MESSAGE_RETRY_DELAY = 1.0  # Segundos de delay base para reintentos de guardado de mensajes

# Configuraciones de rendimiento y escalabilidad
PERFORMANCE_CONFIG = {
    # Pool de conexiones HTTP
    'max_concurrent_requests': 50,
    'max_data_channel_concurrent': 10,
    'connector_limit': 100,
    'connector_limit_per_host': 30,
    'http_timeout_total': 30,
    'http_timeout_connect': 10,
    'http_timeout_read': 10,
    
    # Timeouts específicos para operaciones
    'data_channel_timeout': 8.0,  # Aumentado de 5.0s
    'tts_generation_timeout': 15.0,
    'llm_response_timeout': 30.0,
    'message_save_timeout': 10.0,
    
    # Control de back-pressure
    'message_queue_max_size': 100,
    'data_channel_buffer_size': 50,
    'concurrent_tts_limit': 3,
    
    # Reintentos y backoff
    'max_retries_critical': 5,
    'max_retries_normal': 3,
    'retry_base_delay': 1.0,
    'retry_max_delay': 10.0,
    
    # Métricas y monitoring
    'enable_performance_metrics': True,
    'metrics_log_interval': 60.0,  # Log métricas cada 60s
} 