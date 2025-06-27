import asyncio
import logging
import os
import json # Para parsear metadata
import uuid # Para generar IDs únicos para mensajes de IA
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path # Para leer el archivo de prompt
import time
import re

# CRÍTICO: Cargar variables de entorno ANTES que cualquier otra importación
from dotenv import load_dotenv
load_dotenv()

# Asegurar que las variables críticas estén disponibles para el SDK de LiveKit
import os
if not os.getenv("LIVEKIT_API_KEY"):
    # Cargar explícitamente desde dotenv si no están en el entorno
    from dotenv import dotenv_values
    env_vars = dotenv_values('.env')
    for key, value in env_vars.items():
        if value is not None:
            os.environ[key] = value

import aiohttp # Para llamadas HTTP asíncronas

from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli, # Importar cli como módulo desde livekit.agents
    stt,
    llm, # Mantener esta importación
    tts,
    vad,
    AgentSession,
    Agent,
    WorkerType,
    RoomOutputOptions,
    RoomInputOptions,
)
from livekit.agents.llm import ChatMessage # Importar ChatMessage
from livekit.rtc import RemoteParticipant, Room
# Importar plugins de LiveKit
from livekit.plugins import deepgram, openai, silero, cartesia

# TABUS removido - ahora usando avatar CSS en frontend

# Contenido de config.py movido aquí
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, Extra, field_validator

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

    # Tavus Avatar - REMOVIDO (ahora usando avatar CSS)

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

# Instancia global de configuración con manejo de errores
try:
    settings = AppSettings()
    logging.info("✅ Configuración cargada exitosamente")
    logging.info(f"🔗 LiveKit URL: {settings.livekit_url}")
    logging.info(f"🌐 API Base URL: {settings.api_base_url}")
    logging.info(f"🤖 OpenAI Model: {settings.openai_model}")
    logging.info(f"🎵 Cartesia Voice ID: {settings.cartesia_voice_id}")
    logging.info("🎭 Usando avatar CSS en frontend")
except Exception as e:
    logging.error(f"❌ Error cargando configuración: {e}")
    # Crear configuración por defecto para desarrollo
    import os
    class DefaultSettings:
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
            # Tavus removido - usando avatar CSS
            self.deepgram_api_key = os.getenv('DEEPGRAM_API_KEY', '')
            self.deepgram_model = os.getenv('DEEPGRAM_MODEL', 'nova-2')
    
    settings = DefaultSettings()
    logging.warning("⚠️ Usando configuración por defecto debido a errores de validación")

class MessageThrottler:
    """Clase para reducir el spam de logs de eventos repetitivos."""
    def __init__(self):
        self.last_log_times = {}
        self.event_configs = {
            # Configuraciones específicas para diferentes tipos de eventos
            'system.replica_present': {'throttle_seconds': 30, 'log_every_n': 20},  # Log cada 30s o cada 20 intentos
            'system.heartbeat': {'throttle_seconds': 60, 'log_every_n': 100},  # Log cada 60s o cada 100 heartbeats
            'datachannel_success': {'throttle_seconds': 10, 'log_every_n': 50},  # Menos logs de éxito de DataChannel
            'tts_events': {'throttle_seconds': 2, 'log_every_n': 1},  # TTS events normales
            'conversation_events': {'throttle_seconds': 0, 'log_every_n': 1},  # Eventos importantes siempre
            'default': {'throttle_seconds': 5, 'log_every_n': 10}  # Default para otros eventos
        }
        self.event_counters = {}
    
    def should_log(self, event_key, event_type='default', attempt_number=None):
        """
        Determina si un evento debe loguearse basado en tiempo y frecuencia.
        
        Args:
            event_key: Clave única del evento
            event_type: Tipo de evento para configuración específica
            attempt_number: Número de intento para eventos numerados
        """
        now = time.time()
        config = self.event_configs.get(event_type, self.event_configs['default'])
        
        # Inicializar counters si no existen
        if event_key not in self.event_counters:
            self.event_counters[event_key] = 0
        
        # Incrementar contador
        self.event_counters[event_key] += 1
        
        # Verificar si ha pasado suficiente tiempo
        last_time = self.last_log_times.get(event_key, 0)
        time_passed = now - last_time >= config['throttle_seconds']
        
        # Verificar si es cada N intentos
        count_reached = self.event_counters[event_key] % config['log_every_n'] == 0
        
        # Para eventos numerados, siempre loguear el primer intento
        if attempt_number == 1:
            should_log = True
        else:
            should_log = time_passed or count_reached
        
        if should_log:
            self.last_log_times[event_key] = now
            return True
        return False

    def get_stats(self, event_key):
        """Obtiene estadísticas de un evento específico."""
        return {
            'total_events': self.event_counters.get(event_key, 0),
            'last_log_time': self.last_log_times.get(event_key, 0)
        }

# Instancia global del throttler
message_throttler = MessageThrottler()

# Variables de entorno ya cargadas al inicio del script

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Silenciar logs de livekit para reducir ruido en consola
logging.getLogger('livekit').setLevel(logging.CRITICAL)
logging.getLogger('livekit.agents').setLevel(logging.CRITICAL)
logging.getLogger('livekit.plugins').setLevel(logging.CRITICAL)
logging.getLogger('livekit.rtc').setLevel(logging.CRITICAL)
logging.getLogger('livekit.protocol').setLevel(logging.CRITICAL)
logging.getLogger('livekit.api').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('asyncio').setLevel(logging.CRITICAL)
logging.getLogger('aiohttp').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# Constantes
DEFAULT_TASK_TIMEOUT = 30.0  # Segundos para timeout de tareas como TTS
DEFAULT_DATA_PUBLISH_TIMEOUT = 5.0  # Segundos para timeout al publicar datos por DataChannel
SAVE_MESSAGE_MAX_RETRIES = 3 # Número máximo de reintentos para guardar mensajes
SAVE_MESSAGE_RETRY_DELAY = 1.0 # Segundos de delay base para reintentos de guardado de mensajes

# Cargar la plantilla del prompt del sistema desde el archivo
try:
    PROMPT_FILE_PATH = Path(__file__).parent / "maria_system_prompt.txt"
    MARIA_SYSTEM_PROMPT_TEMPLATE = PROMPT_FILE_PATH.read_text(encoding="utf-8")
    # Validar contenido del prompt template
    if "{username}" not in MARIA_SYSTEM_PROMPT_TEMPLATE:
        logging.warning(
            f"El archivo de prompt {PROMPT_FILE_PATH} no contiene la llave {{username}}. "
            "Esto podría causar errores en la personalización del prompt."
        )
except FileNotFoundError:
    logging.error(f"Error: No se encontró el archivo de prompt en {PROMPT_FILE_PATH}. Usando un prompt de respaldo genérico.")
    MARIA_SYSTEM_PROMPT_TEMPLATE = "Eres una asistente virtual llamada María. Tu objetivo es ayudar con la ansiedad. Saluda al usuario {username}."
except Exception as e:
    logging.error(f"Error al cargar o validar el archivo de prompt {PROMPT_FILE_PATH}: {e}. Usando un prompt de respaldo genérico.", exc_info=True)
    MARIA_SYSTEM_PROMPT_TEMPLATE = "Eres una asistente virtual llamada María. Tu objetivo es ayudar con la ansiedad. Saluda al usuario {username}."

class MariaVoiceAgent(Agent):
    def __init__(self,
                 http_session: aiohttp.ClientSession,
                 base_url: str,
                 target_participant: RemoteParticipant, # Útil para logging o referencia interna
                 chat_session_id: Optional[str] = None,
                 username: str = "Usuario",
                 local_agent_identity: Optional[str] = None,  # AGREGADO: Para identificar al agente local
                 # Los plugins STT, LLM, TTS, VAD ya no se pasan aquí
                 **kwargs):
        """
        Inicializa el agente de voz Maria.

        Args:
            http_session: Sesión aiohttp para realizar solicitudes HTTP.
            base_url: URL base para las API del backend.
            target_participant: El participante remoto al que este agente está atendiendo.
            chat_session_id: ID de la sesión de chat actual.
            username: Nombre del usuario.
            local_agent_identity: Identidad del agente local para filtrar mensajes.
            **kwargs: Argumentos adicionales para la clase base Agent.
        """

        system_prompt = MARIA_SYSTEM_PROMPT_TEMPLATE.format(
            username=username if username and username != "Usuario" else "Usuario",
            latest_summary="No hay información previa relevante."
        ).strip()

        # Los plugins se configuran en AgentSession, por lo que no se pasan a super()
        super().__init__(instructions=system_prompt,
                         # stt, llm, tts, vad ya no se pasan aquí
                         **kwargs)

        self._http_session = http_session
        self._base_url = base_url
        self._chat_session_id = chat_session_id
        self._username = username
        self._local_agent_identity = local_agent_identity  # AGREGADO: Almacenar identidad del agente local
        self._ai_message_meta: Dict[str, Dict[str, Any]] = {}
        self._initial_greeting_text: Optional[str] = None
        self.target_participant = target_participant
        self._agent_session: Optional[AgentSession] = None  # CORREGIDO: Cambio de nombre para evitar conflicto
        self._room: Optional[Room] = None  # AGREGADO: Referencia al room

        logging.info(f"MariaVoiceAgent inicializada → chatSessionId: {self._chat_session_id}, Usuario: {self._username}, Atendiendo: {self.target_participant.identity}")

    def set_session(self, session: AgentSession, room: Room):
        """AGREGADO: Método para asignar la AgentSession y Room después de su creación."""
        self._agent_session = session  # CORREGIDO: Usar _agent_session
        self._room = room  # AGREGADO: Almacenar referencia al room
        logging.info("✅ AgentSession y Room asignados, callbacks conectados")

        # Conectar callbacks del agente a la sesión
        # CORREGIDO: Wrapper síncrono para callback async
        def on_conversation_item_added_wrapper(item):
            asyncio.create_task(self._on_conversation_item_added(item))
        
        def on_tts_playback_started_wrapper(event):
            asyncio.create_task(self.on_tts_playback_started(event))
        
        def on_tts_playback_finished_wrapper(event):
            asyncio.create_task(self.on_tts_playback_finished(event))

        session.on("llm_conversation_item_added", on_conversation_item_added_wrapper)
        session.on("tts_playback_started", on_tts_playback_started_wrapper)
        session.on("tts_playback_finished", on_tts_playback_finished_wrapper)

    def register_data_received_event(self):
        """Registra el evento data_received después de que la sesión esté completamente inicializada."""
        if self._room and hasattr(self, '_agent_session') and self._agent_session:
            def on_data_received_wrapper(data_packet):
                # El DataPacket contiene: data, kind, participant, topic
                asyncio.create_task(self._handle_frontend_data(data_packet.data, data_packet.participant))
            
            self._room.on("data_received", on_data_received_wrapper)
            logging.info("✅ Evento data_received registrado exitosamente en el room")
        else:
            logging.warning("❌ No se pudo registrar evento data_received: room o agent_session no disponible")

    async def _send_custom_data(self, data_type: str, data_payload: Dict[str, Any]):
        """
        Envía datos personalizados al frontend a través de un DataChannel.
        Adapta el formato según si se está usando Tavus o no.

        Args:
            data_type: El tipo de mensaje a enviar (ej. "tts_started", "user_transcription_result").
            data_payload: El contenido del mensaje.
        """
        try:
            # Log más detallado para debug
            logging.info(f"🔧 _send_custom_data iniciado: type='{data_type}', payload={data_payload}")
            
            # Verificar estado de la room
            logging.info(f"🔍 Estado self._room: {self._room is not None}")
            logging.info(f"🔍 Estado self._room.local_participant: {self._room.local_participant is not None if self._room else 'N/A'}")
            
            if self._room and self._room.local_participant:
                 
                logging.info("✅ Room y local_participant están disponibles")
                
                # Enviar en formato directo (Tavus removido)
                message_data = {
                    "type": data_type,
                    **data_payload  # Expandir directamente el payload
                }
                logging.info(f"📦 Mensaje preparado para envío: {message_data}")
                
                # Serializar a JSON
                json_message = json.dumps(message_data)
                logging.info(f"📄 JSON serializado (primeros 200 chars): {json_message[:200]}")
                
                logging.info(f"🚀 Enviando via DataChannel (timeout: {DEFAULT_DATA_PUBLISH_TIMEOUT}s)...")
                await asyncio.wait_for(
                    self._room.local_participant.publish_data(json_message),
                    timeout=DEFAULT_DATA_PUBLISH_TIMEOUT
                )
                
                logging.info(f"✅ Mensaje '{data_type}' enviado exitosamente via DataChannel")
            else:
                 logging.warning("No se pudo enviar custom data: room no está disponible.")
        except asyncio.TimeoutError:
            logging.error(f"❌ TIMEOUT al enviar DataChannel: type={data_type}, timeout={DEFAULT_DATA_PUBLISH_TIMEOUT}s")
        except Exception as e:
            logging.error(f"❌ EXCEPCIÓN al enviar DataChannel: {e}", exc_info=True)

    # Método _convert_to_tavus_format removido - ya no necesario

    async def _handle_frontend_data(self, payload: bytes, participant: 'livekit.RemoteParticipant'):
        """Maneja los DataChannels enviados desde el frontend (formato directo, sin Tavus)."""
        # CORREGIDO: Usar la identidad del agente local almacenada para ignorar mensajes propios
        if participant and self._local_agent_identity and participant.identity == self._local_agent_identity:
             if message_throttler.should_log(f"ignore_own_message_{participant.identity}", 'default'):
                 logging.debug(f"Ignorando mensaje del propio agente: {participant.identity}")
             return

        try:
            data_str = payload.decode('utf-8')
            message_data = json.loads(data_str)
            
            # Solo log detallado para mensajes importantes
            participant_name = participant.identity if participant else 'N/A'
            if message_throttler.should_log(f"datachannel_received_{participant_name}", 'default'):
                logging.debug(f"DataChannel recibido: Participante='{participant_name}', Payload='{data_str[:100]}...'")

            # Extraer tipo de mensaje
            message_type = message_data.get("type")

            # Manejar mensajes de texto del usuario
            if message_type == "submit_user_text":
                user_text = message_data.get("text")
                logging.info(f"📨 Mensaje de usuario recibido: submit_user_text")
                
                if user_text and hasattr(self, '_agent_session'):
                    logging.info(f"✅ Procesando mensaje de usuario: '{user_text[:50]}...'")
                    await self._send_user_transcript_and_save(user_text)
                    logging.info(f"🤖 Generando respuesta para: '{user_text[:50]}...'")
                    self._agent_session.generate_reply(user_input=user_text)
                elif not hasattr(self, '_agent_session'):
                    logging.warning("❌ _agent_session no disponible.")
                else:
                    logging.warning(f"❌ Mensaje vacío del participante: {participant_name}")
                return

            # Eventos directos con throttling
            if message_type:
                if message_throttler.should_log(f'direct_event_{message_type}', 'default'):
                    logging.info(f"📨 Evento directo: tipo='{message_type}'")
                return

            # Mensajes desconocidos con throttling
            if message_throttler.should_log('unknown_message_format', 'default'):
                logging.info(f"ℹ️ Mensaje formato desconocido recibido")

        except json.JSONDecodeError:
            if message_throttler.should_log('json_decode_error', 'default'):
                logging.warning(f"❌ Error decodificando JSON del DataChannel: {payload.decode('utf-8', errors='ignore')[:100]}...")
        except Exception as e:
            logging.error(f"❌ Error procesando DataChannel: {e}", exc_info=True)

    async def _save_message(self, content: str, sender: str, message_id: Optional[str] = None, is_sensitive: bool = False):
        """
        Guarda un mensaje en el backend mediante una solicitud HTTP POST.
        Implementa una lógica de reintentos con backoff exponencial para errores de servidor.

        Args:
            content: El contenido del mensaje.
            sender: El remitente del mensaje ("user" o "assistant").
            message_id: ID único del mensaje. Si es None, se generará uno.
            is_sensitive: Si el contenido del mensaje es sensible y no debe loguearse completo.
        """
        if not self._chat_session_id:
            logging.warning("chat_session_id no está disponible, no se puede guardar el mensaje.")
            return

        if not message_id:
            message_id = f"{sender}-{uuid.uuid4()}"

        payload = {
            "id": message_id,
            "chatSessionId": self._chat_session_id,
            "sender": sender,
            "content": content,
        }

        log_content_display = "[CONTENIDO SENSIBLE OMITIDO]" if is_sensitive else content[:100] + ("..." if len(content) > 100 else "")
        logging.info(f"Intentando guardar mensaje: ID={message_id}, chatSessionId={self._chat_session_id}, sender={sender}, content='{log_content_display}'")

        attempts = 0
        while attempts < SAVE_MESSAGE_MAX_RETRIES:
            attempts += 1
            try:
                async with self._http_session.post(f"{self._base_url}/api/messages", json=payload) as resp:
                    if resp.status == 201:
                        logging.info(f"Mensaje (ID: {message_id}) guardado exitosamente en intento {attempts}.")
                        return

                    error_text = await resp.text()
                    if resp.status >= 500: # Errores de servidor, reintentables
                        logging.warning(f"Intento {attempts}/{SAVE_MESSAGE_MAX_RETRIES} fallido al guardar mensaje (ID: {message_id}). Status: {resp.status}. Error: {error_text}")
                        if attempts == SAVE_MESSAGE_MAX_RETRIES:
                            logging.error(f"Error final del servidor ({resp.status}) al guardar mensaje (ID: {message_id}) después de {SAVE_MESSAGE_MAX_RETRIES} intentos: {error_text}")
                            return
                        await asyncio.sleep(SAVE_MESSAGE_RETRY_DELAY * (2**(attempts - 1)))
                    else: # Errores de cliente (4xx) u otros no reintentables por código de estado
                        logging.error(f"Error no reintentable del cliente ({resp.status}) al guardar mensaje (ID: {message_id}): {error_text}")
                        return

            except aiohttp.ClientError as e_http: # Errores de red/conexión de aiohttp
                logging.warning(f"Excepción de red en intento {attempts}/{SAVE_MESSAGE_MAX_RETRIES} al guardar mensaje (ID: {message_id}): {e_http}")
                if attempts == SAVE_MESSAGE_MAX_RETRIES:
                    logging.error(f"Excepción final de red al guardar mensaje (ID: {message_id}) después de {SAVE_MESSAGE_MAX_RETRIES} intentos: {e_http}", exc_info=True)
                    return
                await asyncio.sleep(SAVE_MESSAGE_RETRY_DELAY * (2**(attempts - 1)))

            except Exception as e: # Otras excepciones inesperadas durante el POST
                logging.error(f"Excepción inesperada en intento {attempts} al guardar mensaje (ID: {message_id}): {e}", exc_info=True)
                return

        logging.error(f"Todos los {SAVE_MESSAGE_MAX_RETRIES} intentos para guardar el mensaje (ID: {message_id}) fallaron.")

    async def _send_user_transcript_and_save(self, user_text: str):
        """Guarda el mensaje del usuario y lo envía al frontend."""
        logging.info(f"Usuario ({self._username}) transcribió/envió: '{user_text}'")
        await self._save_message(user_text, "user")
        await self._send_custom_data("user_transcription_result", {"transcript": user_text})

    def _process_closing_message(self, text: str) -> Tuple[str, bool]:
        """
        Procesa el texto de un mensaje para detectar y limpiar una señal de cierre de sesión.
        Busca la etiqueta [CIERRE_DE_SESION] en el texto, la remueve, y devuelve
        información sobre si se detectó esta señal.

        Args:
            text: El texto del mensaje.

        Returns:
            Una tupla conteniendo el texto procesado (sin la etiqueta de cierre)
            y un booleano indicando si se detectó la señal de cierre.
        """
        is_closing_message = False
        
        # Detectar automáticamente despedidas naturales y añadir el tag internamente
        auto_detected_closing = self._detect_natural_closing_message(text)
        
        # Si ya contiene la etiqueta manual o se detectó automáticamente
        if "[CIERRE_DE_SESION]" in text or auto_detected_closing:
            is_closing_message = True
            
            if "[CIERRE_DE_SESION]" in text:
                logging.info(f"Se detectó señal manual [CIERRE_DE_SESION] en el texto: '{text}'")
                # Remover completamente la etiqueta y limpiar espacios
                text = text.replace("[CIERRE_DE_SESION]", "").strip()
            else:
                logging.info(f"Se detectó despedida automática en el texto: '{text}'")
            
            # Asegurar que hay texto válido para el TTS
            if not text or len(text.strip()) == 0:
                # Si el texto quedó vacío, usar un mensaje de despedida genérico
                text = f"Hasta pronto, {self._username}."
                logging.info(f"Texto vacío después de procesar cierre, usando despedida genérica: '{text}'")
            elif self._username != "Usuario" and self._username not in text:
                # Agregar el nombre del usuario si no está presente
                text = f"{text.rstrip('.')} {self._username}."
            
            logging.info(f"Texto final para TTS después de procesar cierre: '{text}'")
        
        return text, is_closing_message

    def _detect_natural_closing_message(self, text: str) -> bool:
        """
        Detecta automáticamente si un mensaje es una despedida natural
        basándose en patrones de texto comunes.
        
        Args:
            text: El texto del mensaje a analizar
            
        Returns:
            True si se detecta como mensaje de cierre natural
        """
        if not text:
            return False
            
        # Convertir a minúsculas para análisis
        lower_text = text.lower().strip()
        
        # Patrones de despedida con el nombre del usuario
        username_patterns = [
            f"gracias por confiar en mí hoy, {self._username.lower()}",
            f"gracias por compartir conmigo, {self._username.lower()}",
            f"ha sido un honor acompañarte, {self._username.lower()}",
            f"ha sido un placer acompañarte, {self._username.lower()}",
            f"que tengas un día tranquilo, {self._username.lower()}",
            f"que tengas un buen día, {self._username.lower()}",
            f"hasta pronto, {self._username.lower()}",
            f"hasta la próxima, {self._username.lower()}",
            f"cuídate mucho, {self._username.lower()}",
            f"cuídate bien, {self._username.lower()}",
            f"nos vemos pronto, {self._username.lower()}",
            f"espero verte pronto, {self._username.lower()}",
            f"que descanses, {self._username.lower()}",
            f"que te vaya bien, {self._username.lower()}",
        ]
        
        # Patrones de despedida generales - frases completas
        closing_patterns = [
            "que las herramientas que exploramos te acompañen",
            "que las herramientas te acompañen",
            "que las técnicas que vimos te ayuden",
            "que los recursos que compartimos te sirvan",
            "recuerda que tienes recursos internos muy valiosos",
            "recuerda que tienes herramientas valiosas",
            "recuerda las técnicas que practicamos",
            "estoy aquí cuando necesites apoyo con la ansiedad",
            "estoy aquí cuando necesites hablar",
            "estoy aquí cuando me necesites",
            "siempre puedes volver cuando necesites apoyo",
            "puedes regresar cuando lo necesites",
            "que tengas un día tranquilo",
            "que tengas un buen día",
            "que tengas una buena tarde",
            "que tengas una buena noche",
            "cuídate mucho",
            "cuídate bien",
            "hasta la próxima",
            "hasta pronto",
            "nos vemos pronto",
            "que descanses bien",
            "que te vaya muy bien",
            "que todo salga bien",
            "espero haberte ayudado",
            "me alegra haber podido ayudarte",
            "ha sido un placer acompañarte",
            "gracias por permitirme acompañarte",
            "gracias por compartir conmigo",
        ]
        
        # Patrones de finalización con contexto - frases que indican fin de conversación
        ending_phrases = [
            "gracias por confiar en mí",
            "gracias por compartir",
            "ha sido un honor acompañarte",
            "ha sido un placer acompañarte",
            "espero haberte ayudado",
            "me alegra haber podido ayudarte",
            "que las herramientas te acompañen",
            "que las técnicas te ayuden",
            "recuerda que tienes recursos",
            "recuerda las herramientas",
            "estoy aquí cuando necesites",
            "puedes volver cuando necesites",
            "siempre puedes regresar",
            "hasta la próxima sesión",
            "nos vemos en la próxima",
            "que tengas un día",
            "que tengas una buena",
            "cuídate mucho",
            "cuídate bien",
            "hasta pronto",
            "hasta luego",
            "nos vemos",
            "que descanses",
            "que todo salga bien",
            "que te vaya bien",
        ]
        
        # Verificar patrones con nombre de usuario
        for pattern in username_patterns:
            if pattern in lower_text:
                logging.info(f"Detectado patrón de cierre con usuario: '{pattern}'")
                return True
        
        # Verificar patrones generales de despedida (frases completas)
        for pattern in closing_patterns:
            if pattern in lower_text:
                logging.info(f"Detectado patrón de cierre general: '{pattern}'")
                return True
        
        # Detectar mensajes que terminan la conversación de forma natural
        # Solo para mensajes relativamente cortos (menos de 300 caracteres)
        if len(lower_text) < 300:
            for phrase in ending_phrases:
                if phrase in lower_text:
                    logging.info(f"Detectada frase de finalización: '{phrase}'")
                    return True
        
        # Patrones adicionales para detectar despedidas en contexto
        # Buscar combinaciones de palabras clave que sugieren cierre
        farewell_keywords = ["gracias", "acompañar", "ayudar", "confiar", "compartir", "herramientas", "técnicas", "recursos"]
        closing_keywords = ["cuídate", "hasta", "nos vemos", "pronto", "día", "noche", "tarde", "descanses", "bien"]
        
        farewell_count = sum(1 for keyword in farewell_keywords if keyword in lower_text)
        closing_count = sum(1 for keyword in closing_keywords if keyword in lower_text)
        
        # Si hay múltiples palabras clave de despedida Y de cierre, es probable que sea un mensaje de cierre
        if farewell_count >= 2 and closing_count >= 1 and len(lower_text) < 250:
            logging.info(f"Detectado mensaje de cierre por combinación de palabras clave (despedida: {farewell_count}, cierre: {closing_count})")
            return True
        
        return False

    def _process_video_suggestion(self, text: str) -> Tuple[str, Optional[Dict[str, str]]]:
        """
        Procesa el texto de un mensaje para detectar y extraer una sugerencia de video.
        Soporta ambos formatos: [SUGERIR_VIDEO: Título, URL] y [SUGERIR_VIDEO: Título|URL]

        Args:
            text: El texto del mensaje.

        Returns:
            Una tupla conteniendo el texto procesado (sin la etiqueta de video)
            y un diccionario con la información del video si se encontró, o None.
        """
        video_payload = None
        video_tag_start = "[SUGERIR_VIDEO:"
        if video_tag_start in text:
            try:
                start_index = text.find(video_tag_start)
                end_index = text.find("]", start_index)
                if start_index != -1 and end_index != -1:
                    video_info_str = text[start_index + len(video_tag_start):end_index].strip()
                    
                    # Soportar tanto el formato con | como con ,
                    if '|' in video_info_str:
                        parts = [p.strip() for p in video_info_str.split('|')]
                    else:
                        parts = [p.strip() for p in video_info_str.split(',')]
                    
                    if len(parts) >= 2:
                        video_title = parts[0].strip()
                        video_url = parts[1].strip()
                        
                        # Validar que la URL sea válida
                        if video_url.startswith('http'):
                            logging.info(f"Se detectó sugerencia de video: Título='{video_title}', URL='{video_url}'")
                            video_payload = {"title": video_title, "url": video_url}
                            processed_text = text[:start_index].strip() + " " + text[end_index+1:].strip()
                            text = processed_text.strip()
                        else:
                            logging.warning(f"URL de video inválida: {video_url}")
                    else:
                        logging.warning(f"Formato de video inválido: {video_info_str}")
            except Exception as e:
                logging.error(f"Error al procesar sugerencia de video: {e}", exc_info=True)
        return text, video_payload

    async def _on_conversation_item_added(self, item: llm.ChatMessage):
        """
        Callback que se ejecuta cuando se añade un nuevo item a la conversación por el LLM.
        Procesa la respuesta del asistente, la guarda, y gestiona la reproducción de TTS.

        Args:
            item: El mensaje de chat añadido a la conversación.
        """
        if item.role == llm.ChatRole.ASSISTANT and item.content:
            ai_original_response_text = item.content
            if not ai_original_response_text:
                logging.warning(f"Mensaje de asistente (ID: {item.id}) recibido sin contenido.")
                return

            ai_message_id = str(item.id) if item.id else f"assistant-{uuid.uuid4()}"
            logging.info(f"Assistant message added (ID: {ai_message_id}): '{ai_original_response_text}'")

            # Procesar el texto para eliminar videos y detectar despedidas
            processed_text, video_payload = self._process_video_suggestion(ai_original_response_text)
            processed_text, is_closing_message = self._process_closing_message(processed_text)
            
            # El texto procesado es lo que se mostrará en el chat
            # Crear una versión limpia para TTS
            processed_text_for_tts = clean_text_for_tts(processed_text)
            
            # Verificar si es saludo inicial
            is_initial_greeting = self._initial_greeting_text is None
            
            if is_initial_greeting:
                logging.info(f"🎯 PRIMER SALUDO DETECTADO - Almacenando texto TTS base")
                self._initial_greeting_text = processed_text_for_tts

            # Log de verificación de consistencia texto-voz
            logging.info(f"💬 TEXTO EXACTO para mostrar en chat: '{processed_text}'")
            logging.info(f"🔊 TEXTO EXACTO para convertir a voz: '{processed_text_for_tts}'")
            if processed_text != processed_text_for_tts:
                logging.info(f"🔍 DIFERENCIAS TTS detectadas:")
                logging.info(f"   📝 Chat: {len(processed_text)} caracteres")
                logging.info(f"   🎤 Voz: {len(processed_text_for_tts)} caracteres")
            else:
                logging.info(f"✅ TEXTO IDÉNTICO para chat y voz - {len(processed_text)} caracteres")

            await self._save_message(ai_original_response_text, "assistant", message_id=ai_message_id)

            # Almacenar metadatos para los manejadores de eventos TTS
            self._ai_message_meta[ai_message_id] = {
                "is_closing_message": is_closing_message,
            }

            if is_initial_greeting:
                logging.info(f"📢 Enviando saludo inicial (ID: {ai_message_id}): '{processed_text}'")
            else:
                logging.info(f"💬 Enviando respuesta del asistente (ID: {ai_message_id}): '{processed_text[:100]}...'")

            # IMPORTANTE: Enviar ai_response_generated ANTES del TTS para que aparezca el texto en el chat
            video_data = video_payload if video_payload else None
            logging.info(f"💬 Enviando evento ai_response_generated con texto para chat")
            
            await self._send_custom_data("ai_response_generated", {
                "id": ai_message_id,
                "text": processed_text,  # El texto procesado que se mostrará en el chat
                "suggestedVideo": video_data,
                "isInitialGreeting": is_initial_greeting
            })

            metadata_for_speak_call = {
                "messageId": ai_message_id,
                "is_closing_message": is_closing_message
            }

            # Reproducir TTS después de enviar el evento de texto
            logging.info(f"🔊 Reproduciendo TTS para mensaje (ID: {ai_message_id}): '{processed_text_for_tts[:100]}...'")
            await self._agent_session.speak(processed_text_for_tts, metadata=metadata_for_speak_call)

    async def on_tts_playback_started(self, event: Any):
        """Callback cuando el TTS comienza a reproducirse."""
        ai_message_id = getattr(event, 'item_id', None) # Usar getattr para acceso seguro
        if ai_message_id:
            if message_throttler.should_log(f'tts_started_{ai_message_id}', 'tts_events'):
                logging.debug(f"TTS Playback Started for item_id: {ai_message_id}")
            await self._send_custom_data("tts_started", {"messageId": ai_message_id})
        else:
            logging.warning("on_tts_playback_started: event.item_id is missing.")

    async def on_tts_playback_finished(self, event: Any):
        """Callback cuando el TTS termina de reproducirse."""
        ai_message_id = getattr(event, 'item_id', None) # Usar getattr para acceso seguro
        if ai_message_id:
            if message_throttler.should_log(f'tts_finished_{ai_message_id}', 'tts_events'):
                logging.debug(f"TTS Playback Finished for item_id: {ai_message_id}")

            is_closing_message = None
            event_metadata = getattr(event, 'metadata', None)
            # Intentar obtener is_closing_message desde event.metadata (poblado por nuestra llamada a speak)
            if event_metadata and "is_closing_message" in event_metadata:
                is_closing_message = event_metadata["is_closing_message"]

            # Fallback a _ai_message_meta si no está en event.metadata
            # (especialmente útil para el saludo inicial donde no llamamos a speak directamente)
            if is_closing_message is None:
                message_meta = self._ai_message_meta.get(ai_message_id)
                if message_meta:
                    is_closing_message = message_meta.get("is_closing_message", False)
                else:
                    is_closing_message = False # Default si no se encuentra
                    if message_throttler.should_log(f'missing_meta_{ai_message_id}', 'default'):
                        logging.warning(f"No se encontró metadata para {ai_message_id} en _ai_message_meta.")

            await self._send_custom_data("tts_ended", {
                "messageId": ai_message_id,
                "isClosing": is_closing_message if isinstance(is_closing_message, bool) else False
            })
        else:
            logging.warning("on_tts_playback_finished: event.item_id is missing.")

def parse_participant_metadata(metadata_str: Optional[str]) -> Dict[str, Optional[str]]:
    """Parsea los metadatos del participante (JSON string) en un diccionario."""
    if not metadata_str:
        logging.warning("No se proporcionaron metadatos para el participante o están vacíos.")
        return {"userId": None, "username": None, "chatSessionId": None, "targetParticipantIdentity": None}

    try:
        metadata = json.loads(metadata_str)
        # Extraer valores y asegurar que son del tipo esperado o None
        user_id = metadata.get("userId")
        username = metadata.get("username")
        chat_session_id = metadata.get("chatSessionId")
        target_participant_identity = metadata.get("targetParticipantIdentity")

        # Validaciones de tipo (opcional pero recomendado para robustez)
        if user_id is not None and not isinstance(user_id, str):
            logging.warning(f"userId esperado como string, se recibió {type(user_id)}. Se usará None.")
            user_id = None
        if username is not None and not isinstance(username, str):
            logging.warning(f"username esperado como string, se recibió {type(username)}. Se usará None.")
            username = None
        if chat_session_id is not None and not isinstance(chat_session_id, str):
            logging.warning(f"chatSessionId esperado como string, se recibió {type(chat_session_id)}. Se usará None.")
            chat_session_id = None
        if target_participant_identity is not None and not isinstance(target_participant_identity, str):
            logging.warning(f"targetParticipantIdentity esperado como string, se recibió {type(target_participant_identity)}. Se usará None.")
            target_participant_identity = None

        return {
            "userId": user_id,
            "username": username,
            "chatSessionId": chat_session_id,
            "targetParticipantIdentity": target_participant_identity,
        }
    except json.JSONDecodeError:
        logging.error(f"Error al decodificar metadatos JSON del participante: {metadata_str}")
        return {"userId": None, "username": None, "chatSessionId": None, "targetParticipantIdentity": None}
    except Exception as e:
        logging.error(f"Error inesperado al parsear metadatos del participante: {e}", exc_info=True)
        return {"userId": None, "username": None, "chatSessionId": None, "targetParticipantIdentity": None}

async def _setup_plugins(job: JobContext) -> Tuple[Optional[stt.STT], Optional[llm.LLM], Optional[vad.VAD], Optional[tts.TTS]]:
    """
    Configura y devuelve los plugins STT, LLM, VAD y TTS.

    Args:
        job: El contexto del job actual, potencialmente usado para configuración avanzada de plugins.

    Returns:
        Una tupla con las instancias de los plugins (STT, LLM, VAD, TTS).
        Retorna Nones si hay un error crítico durante la configuración.

    Raises:
        Puede propagar excepciones si las variables de entorno requeridas por los plugins
        (ej. claves API) no están configuradas.
    """
    try:
        logging.info("🔧 Configurando plugins del agente...")
        
        stt_plugin = deepgram.STT(
            model=settings.deepgram_model, 
            language="es", 
            interim_results=True,
            smart_format=True,
            punctuate=True,
            utterance_end_ms=1000,  # Esperar 1 segundo de silencio antes de finalizar utterance
            vad_events=True,
            endpointing=300         # Tiempo mínimo antes de endpoint en ms
        )
        llm_plugin = openai.LLM(model=settings.openai_model)
        
        vad_plugin = silero.VAD.load(
            prefix_padding_duration=0.2,    # 200ms para capturar inicio completo
            min_silence_duration=1.5,       # 1500ms - más tiempo para pausas naturales
            activation_threshold=0.4,       # Más sensible para detectar voz suave
            min_speech_duration=0.15        # 150ms - detectar palabras más cortas
            # sample_rate y force_cpu usarán los valores por defecto (16000 y True respectivamente)
        )

        tts_cartesia_plugin = cartesia.TTS(
            api_key=settings.cartesia_api_key,
            model=settings.cartesia_model,
            voice=settings.cartesia_voice_id, # Cambiado de voice_id a voice
            language=settings.cartesia_language,
            speed=settings.cartesia_speed,
            emotion=settings.cartesia_emotion,
        )

        logging.info(f"✅ Plugins configurados: STT({settings.deepgram_model}), LLM({settings.openai_model}), VAD(Silero), TTS({settings.cartesia_model})")
        return stt_plugin, llm_plugin, vad_plugin, tts_cartesia_plugin
    except Exception as e_plugins:
        logging.error(f"❌ Error crítico configurando plugins: {e_plugins}", exc_info=True)
        return None, None, None, None

# Función _setup_and_start_tavus_avatar removida - usando avatar CSS en frontend
        return None

async def find_target_participant_in_room(room: Room, identity_str: str, timeout: float = 60.0) -> Optional[RemoteParticipant]:
    # Si ya está en la sala:
    for p in room.participants.values():
        if p.identity == identity_str:
            return p

    # Si no, esperar a que se conecte
    future = asyncio.get_event_loop().create_future()

    def on_participant_connected_handler(new_p: RemoteParticipant, *args): # La firma puede variar, *args para flexibilidad
        # El SDK livekit-rtc pasa RemoteParticipant directamente para PARTICIPANT_CONNECTED
        if new_p.identity == identity_str and not future.done():
            future.set_result(new_p)

    # Suscribirse al evento. El evento 'participant_connected' es de Room, no de RoomEvent.
    room.on("participant_connected", on_participant_connected_handler)

    try:
        # Esperar con timeout
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        logging.warning(f"Timeout esperando al participante con ID '{identity_str}'")
        return None
    finally:
        # Limpiar el listener
        room.off("participant_connected", on_participant_connected_handler)

async def find_first_remote(room: Room, local_identity: str, timeout: float = 60.0) -> Optional[RemoteParticipant]:
    """
    Espera al primer RemoteParticipant que se conecte a la sala y cuya identidad
    no coincida con la identidad local proporcionada.

    Args:
        room: La instancia de la sala de LiveKit.
        local_identity: La identidad del participante local, para excluirlo.
        timeout: Tiempo máximo en segundos para esperar al participante.

    Returns:
        El primer RemoteParticipant encontrado, o None si se agota el tiempo.
    """
    # Listener
    fut = asyncio.get_event_loop().create_future()
    def on_join(p: RemoteParticipant, *args):
        if p.identity != local_identity and not fut.done():
            fut.set_result(p)

    room.on("participant_connected", on_join)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        room.off("participant_connected", on_join)

async def job_entrypoint(job: JobContext):
    """
    Punto de entrada principal para el job del agente de LiveKit.
    Este método es llamado por el worker de LiveKit cuando se asigna un nuevo job (sala).

    Configura el agente, los plugins, maneja la conexión a la sala,
    encuentra al participante remoto y arranca la sesión del agente.

    Args:
        job: El contexto del job proporcionado por LiveKit, que incluye
             información de la sala y metadatos.
    """
    logging.info(f"Iniciando job_entrypoint para la sala: {job.room.name}")
    logging.info(f"Metadata del Job (job.job.metadata): {job.job.metadata}")
    
    # Conectar al JobContext (gestionado por LiveKit)
    try:
        await job.connect()
        logging.info(f"Conectado exitosamente a la sala: {job.room.name}")
    except Exception as e_connect:
        logging.critical(f"Error al conectar con job.connect(): {e_connect}", exc_info=True)
        return

    # Obtener la identidad local primero
    local_id = job.room.local_participant.identity
    logging.info(f"Agente local identity: {local_id}")

    # CORREGIDO: Acceder a la metadata desde el participante remoto (usuario), no del local (agente)
    # Auto-descubrimiento del participante remoto y obtención de metadatos
    participants = list(job.room.remote_participants.values())
    candidates = [p for p in participants if p.identity != local_id]
    target_remote_participant: Optional[RemoteParticipant] = None
    participant_metadata = None
    
    if candidates:
        # Si ya hay participantes remotos, usar el primero
        target_remote_participant = candidates[0]
        participant_metadata = getattr(target_remote_participant, 'metadata', None)
        logging.info(f"Auto-descubrimiento: elegido participante {target_remote_participant.identity}")
        logging.info(f"Metadata del participante remoto {target_remote_participant.identity}: {participant_metadata}")
    else:
        # Si no hay participantes remotos aún, esperar al primero
        logging.info(f"No se encontraron participantes remotos existentes. Esperando al primero en conectarse (distinto de {local_id})...")
        target_remote_participant = await find_first_remote(job.room, local_id)
        if not target_remote_participant:
            logging.error("No llegó ningún usuario remoto; abortando.")
            await job.disconnect() # Desconectar si no hay participante
            return
        participant_metadata = getattr(target_remote_participant, 'metadata', None)
        logging.info(f"Auto-descubrimiento por espera: elegido participante {target_remote_participant.identity}")
        logging.info(f"Metadata del participante remoto {target_remote_participant.identity}: {participant_metadata}")
    
    # Parsear metadata del participante para obtener chat_session_id, username, etc.
    parsed_metadata = parse_participant_metadata(participant_metadata)
    chat_session_id = parsed_metadata.get("chatSessionId")
    username = parsed_metadata.get("username", "Usuario") # Default a "Usuario" si no se provee

    # CORREGIR: Si no hay username en metadata, extraer del participant.identity
    if not username or username == "Usuario":
        # Extraer nombre del participant.identity (formato: "Nombre_sessionId")
        participant_identity = target_remote_participant.identity
        if participant_identity and "_" in participant_identity:
            extracted_name = participant_identity.split("_")[0]
            # Reemplazar guiones bajos con espacios para nombres compuestos
            extracted_name = extracted_name.replace("_", " ")
            username = extracted_name
            logging.info(f"Nombre de usuario extraído de participant.identity: '{username}'")
        elif participant_identity:
            username = participant_identity
            logging.info(f"Usando participant.identity completo como nombre: '{username}'")

    # NUEVO: Extraer solo el primer nombre para una conversación más natural
    if username and username != "Usuario":
        # Dividir por espacios y tomar solo la primera palabra (primer nombre)
        first_name = username.split()[0].strip()
        if first_name:
            username = first_name
            logging.info(f"Usando solo el primer nombre para conversación natural: '{username}'")

    # MODIFICACIÓN PARA MODO DEV SIN METADATA FLAG
    # Si no se encontró chatSessionId (lo que ocurre si participant_metadata es None o no lo contiene),
    # asignamos un valor por defecto. Esto es útil para desarrollo local con `python main.py dev`
    # sin necesidad de pasar el flag --metadata.
    if not chat_session_id:
        default_dev_session_id = "dev_default_chat_session_id_123"
        logging.warning(
            f"chatSessionId no se encontró en la metadata del participante (participant.metadata era '{participant_metadata}'). "
            f"Asignando valor por defecto para desarrollo: '{default_dev_session_id}'."
        )
        chat_session_id = default_dev_session_id
        # Ya no necesitamos asignar username por defecto aquí porque ya lo extrajimos arriba

    if not chat_session_id:
        logging.critical("chatSessionId no encontrado en la metadata y no se pudo establecer un valor por defecto. Abortando.")
        return

    # Obtener Room SID de forma asíncrona
    room_sid = await job.room.sid
    logging.info(f"JobContext - Room ID: {room_sid}, Room Name: {job.room.name}")
    logging.info(f"ChatSessionId: {chat_session_id}, Username: {username if username else '(No especificado)'}") # Asegurar que username no sea None en el log

    # Configurar plugins
    stt_plugin, llm_plugin, vad_plugin, tts_plugin = await _setup_plugins(job) # job puede ser necesario para contexto de plugins
    if not all([stt_plugin, llm_plugin, vad_plugin, tts_plugin]):
        logging.critical("Faltan uno o más plugins esenciales. Abortando.")
        return

    # Crear sesión HTTP para que MariaVoiceAgent la use para guardar mensajes
    async with aiohttp.ClientSession() as http_session:
        # Crear AgentSession y pasarle los plugins
        logging.info("Creando AgentSession con los plugins configurados...")
        agent_session = AgentSession(
            stt=stt_plugin,
            llm=llm_plugin,
            tts=tts_plugin,
            vad=vad_plugin,
            # context=job # Podría ser necesario si AgentSession lo usa internamente
        )
        logging.info("AgentSession creada.")

        # Evento para manejar el fin de la sesión y mantener el job vivo
        session_ended_event = asyncio.Event()

        def on_session_end_handler(payload: Any): # payload podría contener info de la razón del cierre
            logging.info(f"Evento 'session_ended' recibido. Payload: {payload}")
            session_ended_event.set()

        agent_session.on("session_ended", on_session_end_handler)

        # Tavus removido - usando avatar CSS en frontend
        logging.info("🎭 Usando avatar CSS visual en frontend (Tavus removido)")

        # Configurar RoomInputOptions y RoomOutputOptions como especificaste
        room_input_options = RoomInputOptions(
            text_enabled=True,    # habilita el canal de texto
            audio_enabled=True,    # habilita el micrófono para STT
            video_enabled=False    # no envías video desde tu cámara
        )
        room_output_options = RoomOutputOptions(
            transcription_enabled=True,  # suscribe la pista de texto
            audio_enabled=True            # suscribe la pista de audio TTS
        )
        logging.info(f"RoomInputOptions configurado: audio_enabled={room_input_options.audio_enabled}, video_enabled={room_input_options.video_enabled}, text_enabled={room_input_options.text_enabled}")
        logging.info(f"RoomOutputOptions configurado: audio_enabled={room_output_options.audio_enabled}, transcription_enabled={room_output_options.transcription_enabled}")

        # Inicializar el agente principal (MariaVoiceAgent)
        agent = MariaVoiceAgent(
            http_session=http_session,
            base_url=settings.api_base_url, # Usar settings #
            target_participant=target_remote_participant,
            chat_session_id=chat_session_id,
            username=username,
            local_agent_identity=local_id,  # AGREGADO: Pasar la identidad del agente local
        )

        # AGREGADO: Asignar la sesión al agente para que pueda acceder a los métodos de TTS
        agent.set_session(agent_session, job.room)

        # Iniciar la lógica del agente a través de AgentSession
        logging.info(
            "Iniciando MariaVoiceAgent a través de AgentSession para el participante: %s",
            target_remote_participant.identity,
        )
        try:
            await agent_session.start(
                agent=agent,
                room=job.room,
                room_input_options=room_input_options, # Añadido
                room_output_options=room_output_options, # Modificado/Añadido
            )
            
            # AGREGADO: Registrar evento data_received después de que la sesión esté completamente inicializada
            logging.info("AgentSession iniciada exitosamente. Registrando evento data_received...")
            agent.register_data_received_event()
            
            # AGREGADO: Generar saludo inicial automáticamente
            logging.info("🚀 INICIANDO SECUENCIA DE SALUDO INICIAL...")
            
            # Esperar un poco para que todo el sistema se estabilice
            logging.info("⏳ Esperando estabilización del sistema (2 segundos)...")
            await asyncio.sleep(2)
            
            # Verificar que la conexión esté estable antes de generar el saludo
            logging.info(f"🔍 Verificando estado del job.room: {job.room is not None}")
            logging.info(f"🔍 Verificando estado del job.room.local_participant: {job.room.local_participant is not None if job.room else 'N/A'}")
            
            if not job.room or not job.room.local_participant:
                logging.error("❌ No se puede generar saludo inicial: room o local_participant no disponible")
            else:
                logging.info(f"✅ Job room está disponible, generando saludo inicial para '{username}'")
                
                # Generar saludo aleatorio de múltiples opciones
                logging.info("📝 Generando mensaje de bienvenida...")
                immediate_greeting = generate_welcome_message(username)
                logging.info(f"💬 Saludo generado: '{immediate_greeting}'")
                
                # Limpiar el saludo para TTS
                immediate_greeting_clean = clean_text_for_tts(immediate_greeting)
                logging.info(f"🧹 Saludo limpio para TTS: '{immediate_greeting_clean}'")
                
                # Crear mensaje del saludo inmediato
                immediate_greeting_id = f"immediate-greeting-{int(time.time() * 1000)}"
                logging.info(f"🆔 ID del saludo inicial: '{immediate_greeting_id}'")
                
                # Verificar que tenemos room disponible antes de enviar
                logging.info(f"🔍 Verificando estado del agent._room: {agent._room is not None}")
                logging.info(f"🔍 Verificando estado del agent._room.local_participant: {agent._room.local_participant is not None if agent._room else 'N/A'}")
                
                if not agent._room:
                    logging.error("❌ No hay room disponible para enviar saludo inicial")
                elif not agent._room.local_participant:
                    logging.error("❌ No hay local_participant disponible para enviar saludo inicial")
                else:
                    logging.info(f"✅ Room y local_participant disponibles para enviar saludo")
                
                # Enviar inmediatamente el saludo al frontend
                logging.info(f"📢 ENVIANDO SALUDO INMEDIATO AL FRONTEND...")
                logging.info(f"🆔 ID: '{immediate_greeting_id}'")
                logging.info(f"💬 TEXTO EXACTO que se mostrará en el chat: '{immediate_greeting}'")
                logging.info(f"🔊 TEXTO EXACTO que se convertirá a voz: '{immediate_greeting_clean}'")
                logging.info(f"🔍 Diferencias de limpieza TTS: Original={len(immediate_greeting)} chars, Limpio={len(immediate_greeting_clean)} chars")
                
                # Preparar payload
                saludo_payload = {
                    "id": immediate_greeting_id,
                    "text": immediate_greeting,
                    "isInitialGreeting": True
                }
                logging.info(f"📦 Payload del saludo: {saludo_payload}")
                
                # Enviar al frontend
                try:
                    logging.info("🚀 Llamando a agent._send_custom_data...")
                    await agent._send_custom_data("ai_response_generated", saludo_payload)
                    logging.info("✅ agent._send_custom_data completado exitosamente")
                except Exception as e:
                    logging.error(f"❌ Error en agent._send_custom_data: {e}", exc_info=True)
                
                # Marcar como saludo inicial procesado
                agent._initial_greeting_text = immediate_greeting_clean
                
                # Generar TTS real para que María hable
                logging.info(f"🔊 Iniciando TTS para que María pronuncie el saludo")
                try:
                    # Usar el método say del agent_session directamente con texto limpio
                    await agent_session.say(immediate_greeting_clean, allow_interruptions=True)
                    logging.info("✅ María está hablando - TTS iniciado exitosamente")
                    
                except Exception as e:
                    logging.warning(f"⚠️ Error con agent_session.say: {e}, intentando método alternativo")
                    
                    try:
                        # Método alternativo: usar el TTS directamente
                        if hasattr(agent_session, 'tts') and agent_session.tts:
                            tts_audio = agent_session.tts.synthesize(immediate_greeting_clean)
                            # El audio se manejará automáticamente por el sistema
                            logging.info("✅ TTS alternativo iniciado correctamente")
                        else:
                            # Si no tenemos TTS disponible, usar eventos manuales
                            raise Exception("No hay TTS disponible")
                    
                    except Exception as e2:
                        logging.warning(f"⚠️ Error con TTS alternativo: {e2}, usando fallback manual")
                        
                        # Fallback final: eventos manuales
                        await agent._send_custom_data("tts_started", {"messageId": immediate_greeting_id})
                        logging.info("🔊 Simulando TTS con eventos manuales")
                        
                        # Tiempo estimado para pronunciar el saludo
                        await asyncio.sleep(10)  # Tiempo suficiente para el saludo completo
                        
                        await agent._send_custom_data("tts_ended", {
                            "messageId": immediate_greeting_id,
                            "isClosing": False
                        })
                        logging.info("🔇 TTS manual completado")
                
                logging.info("✅ Saludo inicial procesado completamente")
                
                # COMENTADO: Saludo personalizado adicional deshabilitado para evitar duplicados
                # El saludo inmediato ya incluye el nombre del usuario y es suficiente
                # try:
                #     greeting_instructions = f"Genera un saludo personalizado muy breve (máximo 2 oraciones) para {username} en una sesión de terapia virtual. Sé cálida pero profesional."
                #     
                #     # Esto generará otro mensaje, pero no será el saludo inicial
                #     logging.info(f"🎯 Generando saludo personalizado adicional...")
                #     agent_session.generate_reply(user_input=greeting_instructions)
                #     
                # except Exception as e:
                #     logging.warning(f"⚠️ Error al generar saludo personalizado adicional: {e}")
                #     # No es crítico si falla, ya tenemos el saludo inmediato
                
                # Mantener el job vivo hasta que la sesión del agente termine
                logging.info("🔄 AgentSession.start() completado. Esperando a que el evento 'session_ended' se active...")
                await session_ended_event.wait()
                logging.info("🏁 Evento 'session_ended' activado. El job_entrypoint continuará para finalizar.")

        except Exception as e:
            logging.critical(
                "Error crítico durante agent_session.start(): %s",
                e,
                exc_info=True,
            )
        finally:
            logging.info(
                "MariaVoiceAgent (y su AgentSession) ha terminado o encontrado un error. job_entrypoint finalizando."
            )
            
            # Mostrar estadísticas de throttling para diagnóstico
            if hasattr(message_throttler, 'event_counters') and message_throttler.event_counters:
                logging.info("📊 Resumen de eventos durante la sesión:")
                for event_key, count in message_throttler.event_counters.items():
                    if count > 10:  # Solo mostrar eventos frecuentes
                        logging.info(f"   {event_key}: {count} eventos")
            
            # En lugar de ctx.shutdown(), usamos job.disconnect() para cerrar la conexión del job actual.
            # Esto es más limpio y específico para el contexto del job.
            # ctx.shutdown() podría usarse si quisiéramos cerrar todo el worker, no sólo este job.
            logging.info("Desconectando el Job de LiveKit...")
            job.shutdown(reason="Dev mode complete") # Cambio a shutdown
            logging.info("Job desconectado.")

def convert_numbers_to_text(text: str) -> str:
    """
    Convierte números del 0 al 100 a su representación en texto en español
    para mejorar la pronunciación del TTS.
    
    Args:
        text: El texto que puede contener números
        
    Returns:
        El texto con números convertidos a palabras
    """
    # Diccionario de conversión de números a texto
    number_dict = {
        '0': 'cero', '1': 'uno', '2': 'dos', '3': 'tres', '4': 'cuatro',
        '5': 'cinco', '6': 'seis', '7': 'siete', '8': 'ocho', '9': 'nueve',
        '10': 'diez', '11': 'once', '12': 'doce', '13': 'trece', '14': 'catorce',
        '15': 'quince', '16': 'dieciséis', '17': 'diecisiete', '18': 'dieciocho',
        '19': 'diecinueve', '20': 'veinte', '21': 'veintiuno', '22': 'veintidós',
        '23': 'veintitrés', '24': 'veinticuatro', '25': 'veinticinco', '26': 'veintiséis',
        '27': 'veintisiete', '28': 'veintiocho', '29': 'veintinueve', '30': 'treinta',
        '40': 'cuarenta', '50': 'cincuenta', '60': 'sesenta', '70': 'setenta',
        '80': 'ochenta', '90': 'noventa', '100': 'cien'
    }
    
    def replace_number(match):
        num_str = match.group()
        num = int(num_str)
        
        # Números directos en el diccionario
        if num_str in number_dict:
            return number_dict[num_str]
        
        # Números del 31-39, 41-49, etc.
        if 31 <= num <= 99:
            tens = (num // 10) * 10
            ones = num % 10
            if ones == 0:
                return number_dict[str(tens)]
            else:
                tens_word = number_dict[str(tens)]
                ones_word = number_dict[str(ones)]
                return f"{tens_word} y {ones_word}"
        
        # Para números mayores a 100, devolver el original
        return num_str
    
    # Patrones para diferentes formatos de números
    patterns = [
        # Horas (ej: 8:00, 15:30)
        (r'\b(\d{1,2}):(\d{2})\b', lambda m: f"{convert_numbers_to_text(m.group(1))} {convert_numbers_to_text(m.group(2))}"),
        # Números enteros simples (ej: 5, 23, 100)
        (r'\b\d{1,2}\b', replace_number),
        # Números con unidades comunes (ej: 5 minutos, 3 veces)
        (r'\b(\d{1,2})\s+(minutos?|segundos?|horas?|veces?|días?)\b', 
         lambda m: f"{convert_numbers_to_text(m.group(1))} {m.group(2)}"),
    ]
    
    processed_text = text
    for pattern, replacement in patterns:
        processed_text = re.sub(pattern, replacement, processed_text)
    
    return processed_text

def generate_welcome_message(username: str) -> str:
    """
    Genera un mensaje de bienvenida aleatorio de múltiples opciones variadas.
    Todos los mensajes mantienen el tono empático y especializado en ansiedad.
    
    Args:
        username: El nombre del usuario
        
    Returns:
        Un mensaje de bienvenida personalizado
    """
    import random
    
    # Normalizar el nombre del usuario
    name_part = f" {username}" if username and username != "Usuario" else ""
    
    # Lista de mensajes de bienvenida variados
    welcome_options = [
        # Opción original mejorada
        f"¡Hola{name_part}! Soy María, tu asistente especializada en manejo de ansiedad. Estoy aquí para escucharte y acompañarte. Cuéntame, ¿qué te ha traído hoy hasta aquí?",
        
        # Saludos cálidos y directos
        f"¡Qué gusto conocerte{name_part}! Soy María y me especializo en ayudar con la ansiedad. Este es tu espacio seguro para compartir lo que sientes. ¿Cómo has estado últimamente?",
        
        f"¡Hola{name_part}, bienvenido! Soy María, y estoy aquí para acompañarte en el manejo de la ansiedad. Me alegra que hayas decidido buscar apoyo. ¿Qué te gustaría conversar hoy?",
        
        f"¡Hola{name_part}! Soy María, tu compañera en este proceso de bienestar emocional. Mi objetivo es ayudarte con herramientas para la ansiedad. ¿Cómo te sientes en este momento?",
        
        # Saludos más empáticos
        f"¡Hola{name_part}! Me llamo María y soy tu asistente especializada en ansiedad. Reconozco tu valentía al estar aquí. ¿Qué es lo que más te inquieta hoy?",
        
        f"¡Qué bueno tenerte aquí{name_part}! Soy María, y mi pasión es ayudar a las personas a manejar la ansiedad. Este es un espacio sin juicios. ¿Qué me quieres contar?",
        
        f"¡Hola{name_part}! Soy María, y estoy especializada en acompañar a personas como tú en el manejo de la ansiedad. Dar este paso ya es muy valioso. ¿Por dónde empezamos?",
        
        # Saludos enfocados en el presente
        f"¡Hola{name_part}! Soy María, tu guía en técnicas para manejar la ansiedad. Me alegra que estés aquí en este momento. ¿Cómo llegaste hasta esta conversación?",
        
        f"¡Bienvenido{name_part}! Soy María, especialista en herramientas para la ansiedad. Este momento que compartes conmigo es importante. ¿Qué te motivó a buscar apoyo hoy?",
        
        # Saludos más conversacionales
        f"¡Hola{name_part}! Soy María, y me dedico a ayudar con la ansiedad de manera práctica y empática. Me da mucho gusto conocerte. ¿Qué tal ha sido tu día?",
        
        f"¡Qué alegría saludarte{name_part}! Soy María, tu asistente para el bienestar emocional y manejo de ansiedad. Estoy aquí para escucharte con atención. ¿Qué necesitas hoy?",
        
        f"¡Hola{name_part}! Soy María, especializada en acompañamiento para la ansiedad. Es un honor que confíes en mí para este momento. ¿Cómo puedo ayudarte hoy?",
        
        # Saludos centrados en fortalezas
        f"¡Hola{name_part}! Soy María, y trabajo con personas valientes como tú que buscan manejar mejor su ansiedad. Ya diste un gran paso al estar aquí. ¿Qué quieres explorar?",
        
        f"¡Bienvenido{name_part}! Soy María, tu aliada en el camino hacia el bienestar emocional. Buscar ayuda muestra mucha sabiduría. ¿Cómo te está afectando la ansiedad últimamente?",
        
        # Saludos con enfoque en herramientas
        f"¡Hola{name_part}! Soy María, especialista en herramientas prácticas para la ansiedad. Juntos podemos encontrar estrategias que te funcionen. ¿Qué situaciones te generan más ansiedad?",
        
        f"¡Qué gusto verte{name_part}! Soy María, y mi especialidad es enseñar técnicas efectivas para manejar la ansiedad. Estás en el lugar correcto. ¿Cuándo empezaste a notar la ansiedad?"
    ]
    
    # Seleccionar aleatoriamente una opción
    selected_greeting = random.choice(welcome_options)
    
    logging.info(f"Saludo seleccionado (opción {welcome_options.index(selected_greeting) + 1}/{len(welcome_options)}): {selected_greeting[:50]}...")
    
    return selected_greeting

def clean_text_for_tts(text: str) -> str:
    """
    Limpia el texto para una mejor pronunciación del TTS.
    
    Args:
        text: El texto original
        
    Returns:
        El texto limpio optimizado para TTS
    """
    # Convertir números a texto
    cleaned_text = convert_numbers_to_text(text)
    
    # Limpiar puntuaciones problemáticas
    cleaned_text = re.sub(r'\.{2,}', '.', cleaned_text)  # Múltiples puntos a uno solo
    cleaned_text = re.sub(r'—', ',', cleaned_text)  # Guiones largos a comas
    cleaned_text = re.sub(r'–', ',', cleaned_text)  # Guiones medios a comas
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)  # Múltiples espacios a uno solo
    cleaned_text = cleaned_text.strip()
    
    return cleaned_text

if __name__ == "__main__":
    logging.info("Configurando WorkerOptions y ejecutando la aplicación CLI...")
    
    logging.info(f"Configuración de LiveKit cargada. URL: {settings.livekit_url[:20]}... (verificación crítica ya hecha por AppSettings)") #

    opts = WorkerOptions(
        entrypoint_fnc=job_entrypoint,
        worker_type=WorkerType.ROOM,
        port=settings.livekit_agent_port # Usar settings #
    )

    try:
        logging.info("Iniciando cli.run_app(opts)...")
        cli.run_app(opts)
    except ValueError as e_settings: # Capturar el ValueError de AppSettings
        logging.critical(f"Error de configuración: {e_settings}")
    except KeyboardInterrupt:
        logging.info("Proceso interrumpido por el usuario (Ctrl+C) durante cli.run_app. Finalizando...")
    except Exception as e:
        logging.critical(f"Error crítico irrecuperable al ejecutar cli.run_app: {e}", exc_info=True)
    finally:
        logging.info("Proceso principal del worker (cli.run_app) finalizado.")