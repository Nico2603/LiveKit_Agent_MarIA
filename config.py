import os
from dotenv import load_dotenv
import logging
from typing import List, Optional
from pydantic import BaseSettings, Field, validator

class AppSettings(BaseSettings):
    """
    Centraliza la carga y acceso a las variables de entorno de la aplicación.
    """
    # LiveKit credentials
    livekit_url: str = Field(..., env="LIVEKIT_URL")
    livekit_api_key: str = Field(..., env="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(..., env="LIVEKIT_API_SECRET")
    livekit_agent_port: int = Field(0, env="LIVEKIT_AGENT_PORT")

    # Backend API
    api_base_url: str = Field(..., env="API_BASE_URL")

    # OpenAI settings
    openai_chat_model: str = Field("gpt-4o-mini", env="OPENAI_CHAT_MODEL")

    # Cartesia TTS settings
    cartesia_api_key: str = Field(..., env="CARTESIA_API_KEY")
    cartesia_model: str = Field("sonic-spanish", env="CARTESIA_MODEL")
    cartesia_voice_id: str = Field(..., env="CARTESIA_VOICE_ID")
    cartesia_language: str = Field("es", env="CARTESIA_LANGUAGE")
    cartesia_speed: float = Field(1.0, env="CARTESIA_SPEED")
    cartesia_emotion: List[str] = Field(["neutral"], env="CARTESIA_EMOTION")

    # Tavus Avatar settings
    tavus_api_key: Optional[str] = Field(None, env="TAVUS_API_KEY")
    tavus_replica_id: Optional[str] = Field(None, env="TAVUS_REPLICA_ID")

    # STT Deepgram
    deepgram_api_key: str = Field(..., env="DEEPGRAM_API_KEY")
    deepgram_model: Optional[str] = Field("nova-2", env="DEEPGRAM_MODEL") # Default a nova-2 si no se especifica

    class Config:
        env_file = ".env"
        case_sensitive = False
        # Asegurarse de que Pydantic cargue las variables de entorno al inicio.
        # load_dotenv() no es necesario aquí explícitamente si se usa env_file,
        # pero es buena práctica que Pydantic se encargue de esto.
        # Pydantic v1 usa `dotenv_path` o lee directamente de `.env` si `env_file` se especifica.
        # Para Pydantic v2, la carga de .env es automática si python-dotenv está instalado.

    @validator("cartesia_emotion", pre=True)
    def split_emotion(cls, v):
        if isinstance(v, str):
            return [e.strip() for e in v.split(',') if e.strip()]
        return v

    def _validate_critical_settings(self):
        """Valida que las configuraciones críticas estén presentes."""
        critical_vars = {
            "LIVEKIT_URL": self.livekit_url,
            "LIVEKIT_API_KEY": self.livekit_api_key,
            "LIVEKIT_API_SECRET": self.livekit_api_secret,
            "API_BASE_URL": self.api_base_url,
            # Aunque Cartesia y OpenAI son esenciales para la funcionalidad,
            # sus claves son verificadas por los plugins mismos.
            # No es estrictamente necesario chequear CARTESIA_API_KEY aquí
            # si el plugin de Cartesia lo hace y lanza un error.
        }
        missing_vars = [name for name, value in critical_vars.items() if not value]
        if missing_vars:
            error_message = f"Variables de entorno críticas faltantes: {', '.join(missing_vars)}. La aplicación no puede iniciarse."
            logging.critical(error_message)
            raise ValueError(error_message)

# Instancia global de configuración para ser importada por otros módulos
settings = AppSettings() 