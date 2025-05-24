import asyncio
import logging
import os
import json # Para parsear metadata
import uuid # Para generar IDs únicos para mensajes de IA
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path # Para leer el archivo de prompt

from dotenv import load_dotenv
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
from livekit.plugins import deepgram, openai, silero, cartesia, tavus

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
    api_base_url: str = Field(..., env='API_BASE_URL')

    # OpenAI
    openai_api_key: str = Field(..., env='OPENAI_API_KEY')
    openai_model: str = Field('gpt-4o-mini', env='OPENAI_MODEL')

    # Cartesia TTS
    cartesia_api_key: str = Field(..., env='CARTESIA_API_KEY')
    cartesia_model: str = Field('sonic-spanish', env='CARTESIA_MODEL')
    cartesia_voice_id: str = Field(..., env='CARTESIA_VOICE_ID')
    cartesia_language: str = Field('es', env='CARTESIA_LANGUAGE')
    cartesia_speed: float = Field(1.0, env='CARTESIA_SPEED')
    cartesia_emotion: Optional[str] = Field(None, env='CARTESIA_EMOTION')

    # Tavus Avatar
    tavus_api_key: Optional[str] = Field(None, env='TAVUS_API_KEY')
    tavus_replica_id: Optional[str] = Field(None, env='TAVUS_REPLICA_ID')

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

# Instancia global de configuración
settings = AppSettings()
# Fin del contenido de config.py

# Cargar variables de entorno (si .env file es usado por AppSettings, esto podría ser redundante o necesitar ajuste)
# load_dotenv() # AppSettings ya carga desde .env

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
            **kwargs: Argumentos adicionales para la clase base Agent.
        """

        system_prompt = MARIA_SYSTEM_PROMPT_TEMPLATE.format(
            username=username,
            user_greeting="",
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
        self._ai_message_meta: Dict[str, Dict[str, Any]] = {}
        self._initial_greeting_text: Optional[str] = None
        self.target_participant = target_participant

        logging.info(f"MariaVoiceAgent (ahora Agent) inicializada para chatSessionId: {self._chat_session_id}, Usuario: {self._username}, Atendiendo a: {self.target_participant.identity}")

    async def _send_custom_data(self, data_type: str, data_payload: Dict[str, Any]):
        """
        Envía datos personalizados al frontend a través de un DataChannel.

        Args:
            data_type: El tipo de mensaje a enviar (ej. "tts_started", "user_transcription_result").
            data_payload: El contenido del mensaje.
        """
        try:
            logging.debug(f"Enviando DataChannel: type={data_type}, payload={data_payload}")
            if hasattr(self, 'session') and self.session and self.session.room and self.session.room.local_participant:
                 await asyncio.wait_for(
                    self.session.room.local_participant.publish_data(json.dumps({"type": data_type, "payload": data_payload})),
                    timeout=DEFAULT_DATA_PUBLISH_TIMEOUT
                 )
                 if data_type == "initial_greeting_message": # Este caso parece obsoleto o para otro propósito
                     logging.debug("► Mensaje 'initial_greeting_message' enviado vía DataChannel")
            else:
                 logging.warning("No se pudo enviar custom data: self.session no está disponible o inicializado.")
        except asyncio.TimeoutError:
            logging.error(f"Timeout al enviar DataChannel: type={data_type}, payload={data_payload}")
        except Exception as e:
            logging.error(f"Excepción al enviar DataChannel: {e}", exc_info=True)

    async def _handle_frontend_data(self, payload: bytes, participant: 'livekit.RemoteParticipant', **kwargs):
        """Maneja los DataChannels enviados desde el frontend."""
        if participant and hasattr(self, 'session') and self.session.participant and participant.identity == self.session.participant.identity:
             return

        try:
            data_str = payload.decode('utf-8')
            message_data = json.loads(data_str)
            message_type = message_data.get("type")

            logging.debug(f"DataChannel recibido del frontend: Tipo='{message_type}', Participante='{participant.identity if participant else 'N/A'}', Payload='{data_str}'")

            if message_type == "submit_user_text":
                user_text = message_data.get("payload", {}).get("text")
                if user_text and hasattr(self, 'session'):
                    await self._send_user_transcript_and_save(user_text)
                    logging.info(f"Generando respuesta para texto de usuario enviado: '{user_text[:50]}...'")
                    self.session.generate_reply(user_input=user_text)
                elif not hasattr(self, 'session'):
                    logging.warning("_handle_frontend_data: self.session no disponible.")

        except json.JSONDecodeError:
            logging.warning(f"Error al decodificar JSON del DataChannel del frontend: {payload.decode('utf-8', errors='ignore')}")
        except Exception as e:
            logging.error(f"Error al procesar DataChannel del frontend: {e}", exc_info=True)

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
        Procesa el texto de un mensaje para detectar una señal de cierre de sesión.

        Args:
            text: El texto del mensaje.

        Returns:
            Una tupla conteniendo el texto procesado (sin la etiqueta de cierre)
            y un booleano indicando si se detectó la señal de cierre.
        """
        is_closing_message = False
        if "[CIERRE_DE_SESION]" in text:
            logging.info(f"Se detectó señal [CIERRE_DE_SESION]")
            text = text.replace("[CIERRE_DE_SESION]", "").strip()
            is_closing_message = True
            if self._username != "Usuario" and self._username not in text:
                text = f"{text.rstrip('.')} {self._username}."
        return text, is_closing_message

    def _process_video_suggestion(self, text: str) -> Tuple[str, Optional[Dict[str, str]]]:
        """
        Procesa el texto de un mensaje para detectar y extraer una sugerencia de video.

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
                    video_info_str = text[start_index + len(video_tag_start):end_index]
                    parts = [p.strip() for p in video_info_str.split(',')]
                    if len(parts) >= 2:
                        video_title = parts[0]
                        video_url = parts[1]
                        logging.info(f"Se detectó sugerencia de video: Título='{video_title}', URL='{video_url}'")
                        video_payload = {"title": video_title, "url": video_url}
                        processed_text = text[:start_index].strip() + " " + text[end_index+1:].strip()
                        text = processed_text.strip()
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

            processed_text_for_tts, is_closing_message = self._process_closing_message(ai_original_response_text)
            processed_text_for_tts, video_payload = self._process_video_suggestion(processed_text_for_tts)

            await self._save_message(ai_original_response_text, "assistant", message_id=ai_message_id)

            # Almacenar metadatos para los manejadores de eventos TTS
            self._ai_message_meta[ai_message_id] = {
                "is_closing_message": is_closing_message,
            }

            # Emitir ai_response_generated
            await self._send_custom_data("ai_response_generated", {
                "id": ai_message_id,
                "text": ai_original_response_text,
                "suggestedVideo": video_payload if video_payload else {}
            })

            metadata_for_speak_call = {
                "messageId": ai_message_id,
                "is_closing_message": is_closing_message
            }

            if self._initial_greeting_text is None:
                logging.info(f"Estableciendo mensaje de saludo inicial (ID: {ai_message_id}): '{processed_text_for_tts}'")
                self._initial_greeting_text = processed_text_for_tts
            else:
                logging.info(f"Reproduciendo TTS para mensaje de IA (ID: {ai_message_id}): '{processed_text_for_tts[:100]}...'")
                await self.session.speak(processed_text_for_tts, metadata=metadata_for_speak_call)

    async def on_tts_playback_started(self, event: Any):
        """Callback cuando el TTS comienza a reproducirse."""
        ai_message_id = getattr(event, 'item_id', None) # Usar getattr para acceso seguro
        if ai_message_id:
            logging.debug(f"TTS Playback Started for item_id: {ai_message_id}, metadata from event: {getattr(event, 'metadata', None)}")
            await self._send_custom_data("tts_started", {"messageId": ai_message_id})
        else:
            logging.warning("on_tts_playback_started: event.item_id is missing.")

    async def on_tts_playback_finished(self, event: Any):
        """Callback cuando el TTS termina de reproducirse."""
        ai_message_id = getattr(event, 'item_id', None) # Usar getattr para acceso seguro
        if ai_message_id:
            logging.debug(f"TTS Playback Finished for item_id: {ai_message_id}, metadata from event: {getattr(event, 'metadata', None)}")

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
                    logging.warning(f"on_tts_playback_finished: No se encontró metadata para {ai_message_id} en _ai_message_meta.")

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
        return {"userId": None, "username": None, "chatSessionId": None, "tavusReplicaId": None, "targetParticipantIdentity": None}

    try:
        metadata = json.loads(metadata_str)
        # Extraer valores y asegurar que son del tipo esperado o None
        user_id = metadata.get("userId")
        username = metadata.get("username")
        chat_session_id = metadata.get("chatSessionId")
        tavus_replica_id = metadata.get("tavusReplicaId")
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
        if tavus_replica_id is not None and not isinstance(tavus_replica_id, str):
            logging.warning(f"tavusReplicaId esperado como string, se recibió {type(tavus_replica_id)}. Se usará None.")
            tavus_replica_id = None
        if target_participant_identity is not None and not isinstance(target_participant_identity, str):
            logging.warning(f"targetParticipantIdentity esperado como string, se recibió {type(target_participant_identity)}. Se usará None.")
            target_participant_identity = None

        return {
            "userId": user_id,
            "username": username,
            "chatSessionId": chat_session_id,
            "tavusReplicaId": tavus_replica_id,
            "targetParticipantIdentity": target_participant_identity,
        }
    except json.JSONDecodeError:
        logging.error(f"Error al decodificar metadatos JSON del participante: {metadata_str}")
        return {"userId": None, "username": None, "chatSessionId": None, "tavusReplicaId": None, "targetParticipantIdentity": None}
    except Exception as e:
        logging.error(f"Error inesperado al parsear metadatos del participante: {e}", exc_info=True)
        return {"userId": None, "username": None, "chatSessionId": None, "tavusReplicaId": None, "targetParticipantIdentity": None}

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
        logging.info("Configurando plugins del agente...")
        stt_plugin = deepgram.STT(model=settings.deepgram_model, language="es", interim_results=False) #
        logging.debug(f"STT plugin (Deepgram {settings.deepgram_model} es) configurado.") #

        llm_plugin = openai.LLM(model=settings.openai_model) #
        logging.debug(f"LLM plugin (OpenAI {settings.openai_model}) configurado.") #

        vad_plugin = silero.VAD.load(
            prefix_padding_duration=0.1,    # 100ms
            min_silence_duration=0.7,       # 700ms (reemplaza min_silence_duration_ms y post_speech_pad_ms)
            activation_threshold=0.5,       # Mismo valor que positive_speech_threshold
            min_speech_duration=0.25        # 250ms
            # sample_rate y force_cpu usarán los valores por defecto (16000 y True respectivamente)
        )
        logging.debug(f"VAD plugin (Silero) configurado.")

        tts_cartesia_plugin = cartesia.TTS(
            api_key=settings.cartesia_api_key, #
            model=settings.cartesia_model, #
            voice=settings.cartesia_voice_id, # Cambiado de voice_id a voice
            language=settings.cartesia_language, #
            speed=settings.cartesia_speed, #
            emotion=settings.cartesia_emotion, #
        )
        logging.debug(f"TTS plugin (Cartesia {settings.cartesia_model}) configurado correctamente.")

        logging.info("Todos los plugins configurados exitosamente.")
        return stt_plugin, llm_plugin, vad_plugin, tts_cartesia_plugin
    except Exception as e_plugins:
        logging.error(f"Error crítico al configurar uno o más plugins esenciales: {e_plugins}", exc_info=True)
        return None, None, None, None

async def _setup_and_start_tavus_avatar(
    agent_session_instance: AgentSession,
    room: 'livekit.Room',
    app_settings: 'AppSettings'
) -> Optional[tavus.AvatarSession]:
    """Configura e inicia el avatar de Tavus si las credenciales están presentes en app_settings."""
    if not (app_settings.tavus_api_key and app_settings.tavus_replica_id): #
        logging.warning("Faltan TAVUS_API_KEY o TAVUS_REPLICA_ID en la configuración. El avatar de Tavus no se iniciará.") #
        return None

    logging.info(f"Configurando Tavus AvatarSession con Replica ID: {app_settings.tavus_replica_id}") #
    tavus_avatar = tavus.AvatarSession(
        replica_id=app_settings.tavus_replica_id, #
        api_key=app_settings.tavus_api_key, #
    )
    try:
        await tavus_avatar.start(agent_session=agent_session_instance, room=room)
        logging.info("Tavus AvatarSession iniciada y publicando video.")
        return tavus_avatar
    except Exception as e_tavus:
        logging.error(f"Error al iniciar Tavus AvatarSession: {e_tavus}", exc_info=True)
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

    # Parsear metadata del job para obtener chat_session_id, username, etc.
    parsed_metadata = parse_participant_metadata(job.job.metadata)
    chat_session_id = parsed_metadata.get("chatSessionId")
    username = parsed_metadata.get("username", "Usuario") # Default a "Usuario" si no se provee

    # MODIFICACIÓN PARA MODO DEV SIN METADATA FLAG
    # Si no se encontró chatSessionId (lo que ocurre si job.job.metadata es None o no lo contiene),
    # asignamos un valor por defecto. Esto es útil para desarrollo local con `python main.py dev`
    # sin necesidad de pasar el flag --metadata.
    if not chat_session_id:
        default_dev_session_id = "dev_default_chat_session_id_123"
        logging.warning(
            f"chatSessionId no se encontró en la metadata del job (job.job.metadata era '{job.job.metadata}'). "
            f"Asignando valor por defecto para desarrollo: '{default_dev_session_id}'."
        )
        chat_session_id = default_dev_session_id
        # Opcionalmente, también un nombre de usuario por defecto si no vino y se quedó el genérico.
        if username == "Usuario" and not parsed_metadata.get("username"):
             default_dev_username = "DevUser"
             logging.info(f"Asignando nombre de usuario por defecto para desarrollo: '{default_dev_username}'.")
             username = default_dev_username

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

    # Obtener la identidad local
    local_id = job.room.local_participant.identity
    logging.info(f"Agente local identity: {local_id}")

    # Auto-descubrimiento del participante remoto
    participants = list(job.room.remote_participants.values())
    candidates = [p for p in participants if p.identity != local_id]
    target_remote_participant: Optional[RemoteParticipant] = None

    if candidates:
        target_remote_participant = candidates[0]
        logging.info(f"Auto-descubrimiento: elegido participante {target_remote_participant.identity}")
    else:
        logging.info(f"No se encontraron participantes remotos existentes. Esperando al primero en conectarse (distinto de {local_id})...")
        target_remote_participant = await find_first_remote(job.room, local_id)
        if not target_remote_participant:
            logging.error("No llegó ningún usuario remoto; abortando.")
            await job.disconnect() # Desconectar si no hay participante
            return
        logging.info(f"Auto-descubrimiento por espera: elegido participante {target_remote_participant.identity}")

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

        tavus_avatar_session: Optional[tavus.AvatarSession] = None
        # La condición para configurar Tavus ahora usa directamente settings
        tavus_configured = bool(settings.tavus_api_key and settings.tavus_replica_id) #

        if tavus_configured:
            logging.info("Intentando configurar y arrancar el avatar de Tavus...")
            tavus_avatar_session = await _setup_and_start_tavus_avatar(
                agent_session_instance=agent_session,
                room=job.room,
                app_settings=settings # Pasar la instancia de settings #
            )
            if tavus_avatar_session:
                logging.info("Avatar de Tavus configurado y arrancado.")
            else:
                logging.warning("No se pudo arrancar el avatar de Tavus. El audio del agente se usará.")
                tavus_configured = False # Actualizar si Tavus falló
        else:
            logging.info("No se configuraron las variables de entorno para el avatar de Tavus. Saltando.")

        # Configurar RoomInputOptions y RoomOutputOptions como especificaste
        room_input_options = RoomInputOptions(
            text_enabled=False,    # deshabilita el canal de texto "push-to-talk"
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
        )

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
            
            # Mantener el job vivo hasta que la sesión del agente termine
            logging.info("AgentSession.start() completado. Esperando a que el evento 'session_ended' se active...")
            await session_ended_event.wait()
            logging.info("Evento 'session_ended' activado. El job_entrypoint continuará para finalizar.")

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
            # En lugar de ctx.shutdown(), usamos job.disconnect() para cerrar la conexión del job actual.
            # Esto es más limpio y específico para el contexto del job.
            # ctx.shutdown() podría usarse si quisiéramos cerrar todo el worker, no sólo este job.
            logging.info("Desconectando el Job de LiveKit...")
            job.shutdown(reason="Dev mode complete") # Cambio a shutdown
            logging.info("Job desconectado.")

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