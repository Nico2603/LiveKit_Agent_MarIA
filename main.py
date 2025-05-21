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
    llm, 
    tts, 
    vad, 
    AgentSession,
    Agent,
    WorkerType
)
from livekit.rtc import RoomEvent, RemoteParticipant, Room # Añadir RoomEvent, RemoteParticipant, Room
# from livekit.agents.tts import TTSPlaybackStarted, TTSPlaybackFinished # Eliminar esta importación
from livekit.plugins import deepgram, openai, silero, cartesia, tavus # MODIFIED: Descomentado tavus
# from livekit import RoomEvent # <- Comentar esta línea
# from livekit.protocol import DataPacketKind # <- Comentar esta línea también

# Eliminar la importación incorrecta de cli que causaba ImportError
# from livekit.agents.cli.cli import cli 

# Cargar variables de entorno
load_dotenv()

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constantes
DEFAULT_TASK_TIMEOUT = 30.0  # Segundos para timeout de tareas como TTS

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

# --- Configuración del cliente OpenAI para resúmenes --- ELIMINADO
# (Sección eliminada ya que los resúmenes se manejan en otro backend)

class MariaVoiceAgent(Agent):
    def __init__(self, 
                 http_session: aiohttp.ClientSession,
                 base_url: str,
                 target_participant: RemoteParticipant,
                 chat_session_id: Optional[str] = None,
                 username: str = "Usuario", 
                 stt_plugin: Optional[stt.STT] = None,
                 llm_plugin: Optional[llm.LLM] = None,
                 tts_plugin: Optional[tts.TTS] = None,
                 vad_plugin: Optional[vad.VAD] = None,
                 **kwargs):
        
        system_prompt = MARIA_SYSTEM_PROMPT_TEMPLATE.format(
            username=username, 
            user_greeting=""
        )
        system_prompt = system_prompt.replace("{latest_summary}", "No hay información previa relevante.").strip()

        super().__init__(instructions=system_prompt, 
                         stt=stt_plugin,
                         llm=llm_plugin,
                         tts=tts_plugin,
                         vad=vad_plugin,
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
        try:
            logging.debug(f"Enviando DataChannel: type={data_type}, payload={data_payload}")
            if hasattr(self, 'session') and self.session and self.session.room and self.session.room.local_participant:
                 await self.session.room.local_participant.publish_data(json.dumps({"type": data_type, "payload": data_payload}))
                 if data_type == "initial_greeting_message": # Este caso parece obsoleto o para otro propósito
                     logging.debug("► Mensaje 'initial_greeting_message' enviado vía DataChannel")
            else:
                 logging.warning("No se pudo enviar custom data: self.session no está disponible o inicializado.")
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
        if not self._chat_session_id:
            logging.warning("chat_session_id no está disponible, no se puede guardar el mensaje.")
            return
        
        if not message_id: # Generar ID si no se provee (ej. para mensajes de usuario)
            message_id = f"{sender}-{uuid.uuid4()}"

        payload = {
            "id": message_id, # Incluir el ID del mensaje
            "chatSessionId": self._chat_session_id,
            "sender": sender, 
            "content": content,
        }
        try:
            log_content = "[CONTENIDO SENSIBLE OMITIDO]" if is_sensitive else content[:100] + ("..." if len(content) > 100 else "")
            logging.info(f"Guardando mensaje: ID={message_id}, chatSessionId={self._chat_session_id}, sender={sender}, content='{log_content}'")
            async with self._http_session.post(f"{self._base_url}/api/messages", json=payload) as resp:
                if resp.status == 201:
                    logging.info(f"Mensaje (ID: {message_id}) guardado exitosamente para chatSessionId: {self._chat_session_id}")
                else:
                    error_text = await resp.text()
                    logging.error(f"Error al guardar mensaje (ID: {message_id}) ({resp.status}): {error_text}")
        except Exception as e:
            logging.error(f"Excepción al guardar mensaje (ID: {message_id}): {e}", exc_info=True)

    async def _send_user_transcript_and_save(self, user_text: str):
        """Guarda el mensaje del usuario y lo envía al frontend."""
        logging.info(f"Usuario ({self._username}) transcribió/envió: '{user_text}'")
        await self._save_message(user_text, "user")
        await self._send_custom_data("user_transcription_result", {"transcript": user_text})

    def _process_closing_message(self, text: str) -> Tuple[str, bool]:
        is_closing_message = False
        if "[CIERRE_DE_SESION]" in text:
            logging.info(f"Se detectó señal [CIERRE_DE_SESION]")
            text = text.replace("[CIERRE_DE_SESION]", "").strip()
            is_closing_message = True
            if self._username != "Usuario" and self._username not in text:
                text = f"{text.rstrip('.')} {self._username}."
        return text, is_closing_message

    def _process_video_suggestion(self, text: str) -> Tuple[str, Optional[Dict[str, str]]]:
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

    async def _handle_conversation_item_added(self, event):
        item = event.item
        if item.type == "message" and item.role == "assistant":
            ai_original_response_text = getattr(item, 'text_content', None)
            if not ai_original_response_text:
                return

            ai_message_id = item.id
            logging.info(f"Assistant message added (ID: {ai_message_id}): '{ai_original_response_text}'")

            processed_text_for_tts, is_closing_message = self._process_closing_message(ai_original_response_text)
            processed_text_for_tts, video_payload = self._process_video_suggestion(processed_text_for_tts)

            await self._save_message(ai_original_response_text, "assistant", message_id=ai_message_id)

            # Almacenar metadatos para los manejadores de eventos TTS
            self._ai_message_meta[ai_message_id] = {
                "is_closing_message": is_closing_message,
            }

            # Emitir ai_response_generated
            # (El texto original se usa para mostrar en el chat, ya que es lo que se guarda)
            await self._send_custom_data("ai_response_generated", {
                "id": ai_message_id,
                "text": ai_original_response_text,
                "suggestedVideo": video_payload if video_payload else {}
            })
            
            # Metadatos para pasar a self.session.speak() si llamamos explícitamente
            # Esto ayuda a que event.metadata en los handlers TTS esté poblado.
            metadata_for_speak_call = {
                "messageId": ai_message_id, # Aunque event.item_id es la fuente primaria, es bueno tenerlo aquí
                "is_closing_message": is_closing_message 
            }

            if self._initial_greeting_text is None:
                logging.info(f"Estableciendo mensaje de saludo inicial (ID: {ai_message_id}): '{processed_text_for_tts}'")
                self._initial_greeting_text = processed_text_for_tts
                # El SDK/AgentSession se encargará de reproducir este saludo inicial.
                # Los manejadores on_tts_playback_started/finished se activarán.
            else:
                logging.info(f"Reproduciendo TTS para mensaje de IA (ID: {ai_message_id}): '{processed_text_for_tts[:100]}...'")
                # Para mensajes no iniciales, llamamos a speak explícitamente con metadatos.
                await self.session.speak(processed_text_for_tts, metadata=metadata_for_speak_call)
                # Los eventos tts_started y tts_ended ahora se manejan en los callbacks on_tts_playback_...

    async def on_tts_playback_started(self, event): # Eliminar tipo de event
        """Callback cuando el TTS comienza a reproducirse."""
        ai_message_id = getattr(event, 'item_id', None) # Usar getattr para acceso seguro
        if ai_message_id:
            logging.debug(f"TTS Playback Started for item_id: {ai_message_id}, metadata from event: {getattr(event, 'metadata', None)}")
            await self._send_custom_data("tts_started", {"messageId": ai_message_id})
        else:
            logging.warning("on_tts_playback_started: event.item_id is missing.")

    async def on_tts_playback_finished(self, event): # Eliminar tipo de event
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
        return {"userId": None, "username": None, "chatSessionId": None, "tavusReplicaId": None, "tavusPersonaId": None, "targetParticipantIdentity": None}

    try:
        metadata = json.loads(metadata_str)
        # Extraer valores y asegurar que son del tipo esperado o None
        user_id = metadata.get("userId")
        username = metadata.get("username")
        chat_session_id = metadata.get("chatSessionId")
        tavus_replica_id = metadata.get("tavusReplicaId")
        tavus_persona_id = metadata.get("tavusPersonaId")
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
        if tavus_persona_id is not None and not isinstance(tavus_persona_id, str):
            logging.warning(f"tavusPersonaId esperado como string, se recibió {type(tavus_persona_id)}. Se usará None.")
            tavus_persona_id = None
        if target_participant_identity is not None and not isinstance(target_participant_identity, str):
            logging.warning(f"targetParticipantIdentity esperado como string, se recibió {type(target_participant_identity)}. Se usará None.")
            target_participant_identity = None
            
        return {
            "userId": user_id,
            "username": username,
            "chatSessionId": chat_session_id,
            "tavusReplicaId": tavus_replica_id,
            "tavusPersonaId": tavus_persona_id,
            "targetParticipantIdentity": target_participant_identity,
        }
    except json.JSONDecodeError:
        logging.error(f"Error al decodificar metadatos JSON del participante: {metadata_str}")
        return {"userId": None, "username": None, "chatSessionId": None, "tavusReplicaId": None, "tavusPersonaId": None, "targetParticipantIdentity": None}
    except Exception as e:
        logging.error(f"Error inesperado al parsear metadatos del participante: {e}", exc_info=True)
        return {"userId": None, "username": None, "chatSessionId": None, "tavusReplicaId": None, "tavusPersonaId": None, "targetParticipantIdentity": None}

async def _setup_plugins(job: JobContext) -> Tuple[Optional[stt.STT], Optional[llm.LLM], Optional[vad.VAD], Optional[tts.TTS]]:
    """Configura y devuelve los plugins STT, LLM, VAD y TTS."""
    try:
        logging.info("Configurando plugins del agente...")
        stt_plugin = deepgram.STT(model="nova-2", language="es", interim_results=False)
        logging.debug(f"STT plugin (Deepgram Nova-2 es) configurado.")

        llm_plugin = openai.LLM(model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"))
        logging.debug(f"LLM plugin (OpenAI {os.getenv('OPENAI_CHAT_MODEL', 'gpt-4o-mini')}) configurado.")

        vad_plugin = silero.VAD.load(
            pre_speech_pad_ms=100, 
            post_speech_pad_ms=500, 
            positive_speech_threshold=0.5, 
            min_speech_duration_ms=250, 
            min_silence_duration_ms=700
        )
        logging.debug(f"VAD plugin (Silero) configurado.")

        tts_cartesia_plugin = cartesia.TTS(
            api_key=os.getenv("CARTESIA_API_KEY"),
            model=os.getenv("CARTESIA_MODEL", "sonic-spanish"),
            voice_id=os.getenv("CARTESIA_VOICE_ID", "5c5ad5e7-1020-476b-8b91-fdcbe9cc313c"),
            language=os.getenv("CARTESIA_LANGUAGE", "es"),
            speed=float(os.getenv("CARTESIA_SPEED", "1.0")),
            emotion=os.getenv("CARTESIA_EMOTION", "neutral").split(","),
        )
        logging.debug(f"TTS plugin (Cartesia {os.getenv('CARTESIA_MODEL', 'sonic-spanish')}) configurado con voice_id: {tts_cartesia_plugin.voice_id}")
        
        logging.info("Todos los plugins configurados exitosamente.")
        return stt_plugin, llm_plugin, vad_plugin, tts_cartesia_plugin
    except Exception as e_plugins:
        logging.error(f"Error crítico al configurar uno o más plugins esenciales: {e_plugins}", exc_info=True)
        return None, None, None, None

async def _setup_and_start_tavus_avatar(
    agent_session_instance: AgentSession,
    room: 'livekit.Room',
    tavus_api_key: Optional[str],
    tavus_replica_id: Optional[str],
    tavus_persona_id: Optional[str]
) -> Optional[tavus.AvatarSession]: # MODIFIED: Tipo de retorno restaurado
    """Configura e inicia el avatar de Tavus si las credenciales están presentes."""
    if not (tavus_api_key and tavus_replica_id):
        # Asegurarse que TAVUS_STOCK_REPLICA_ID sea la variable de entorno correcta o el valor esperado
        logging.warning("Faltan TAVUS_API_KEY o tavus_replica_id (TAVUS_STOCK_REPLICA_ID). El avatar de Tavus no se iniciará.")
        return None
    
    logging.info(f"Configurando Tavus AvatarSession con Replica ID: {tavus_replica_id} y Persona ID: {tavus_persona_id if tavus_persona_id else 'Default'}")
    tavus_avatar = tavus.AvatarSession(
        persona_id=tavus_persona_id,
        replica_id=tavus_replica_id,
        api_key=tavus_api_key,
    )
    try:
        await tavus_avatar.start(agent_session=agent_session_instance, room=room)
        logging.info("Tavus AvatarSession iniciada y publicando video.")
        return tavus_avatar
    except Exception as e_tavus:
        logging.error(f"Error al iniciar Tavus AvatarSession: {e_tavus}", exc_info=True)
        return None

async def find_target_participant_in_room(room: Room, identity: str, timeout: float = 60.0) -> Optional[RemoteParticipant]:
    # Si ya está en la sala:
    for p in room.participants.values():
        if isinstance(p, RemoteParticipant) and p.identity == identity:
            logging.info(f"Participante objetivo '{identity}' encontrado directamente en la sala.")
            return p
    
    # Si no, esperamos el evento de conexión
    logging.info(f"Participante objetivo '{identity}' no encontrado. Esperando conexión con timeout de {timeout}s...")
    fut = asyncio.get_event_loop().create_future()

    def on_participant_connected_handler(new_p: RemoteParticipant, *args): # La firma puede variar, *args para flexibilidad
        # El SDK livekit-rtc pasa RemoteParticipant directamente para PARTICIPANT_CONNECTED
        logging.debug(f"Evento RoomEvent.PARTICIPANT_CONNECTED recibido: identity='{new_p.identity}'")
        if new_p.identity == identity and not fut.done():
            logging.info(f"Participante objetivo '{identity}' conectado a la sala.")
            fut.set_result(new_p)
            # No desregistrar aquí para permitir que el finally lo haga y evitar errores si el futuro ya está resuelto.

    room.on(RoomEvent.PARTICIPANT_CONNECTED, on_participant_connected_handler)
    
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        logging.error(f"Timeout esperando al participante objetivo '{identity}' después de {timeout} segundos.")
        return None
    finally:
        # Siempre desregistrar el listener para evitar fugas o llamadas múltiples.
        room.off(RoomEvent.PARTICIPANT_CONNECTED, on_participant_connected_handler)
        logging.debug(f"Listener para PARTICIPANT_CONNECTED (buscando '{identity}') desregistrado.")

async def job_entrypoint(job: JobContext):
    """Punto de entrada para el trabajo del agente LiveKit."""
    logging.info(f"JOB_ENTRYPOINT_STARTED for room {job.room.name}")
    
    await job.connect() # Conectar al job
    logging.info(f"Conectado como {job.participant.identity}")
    logging.debug(f"Metadatos del participante conectado (job.participant.metadata): {job.participant.metadata}")

    logging.info(f"Iniciando trabajo de agente para la sala: {job.room.name}")

    http_session: Optional[aiohttp.ClientSession] = None
    agent: Optional[MariaVoiceAgent] = None # Explicitly declare agent type
    agent_session: Optional[AgentSession] = None
    tavus_avatar_session: Optional[tavus.AvatarSession] = None # MODIFIED: Añadida declaración para Tavus session
    chat_session_id: Optional[str] = None # Inicializar chat_session_id
    target_participant_identity = None # Inicializar target_participant_identity

    try:
        # Intentar obtener la cadena de metadatos del job.
        # Usamos job.participant.metadata ya que job.connect() lo habrá poblado.
        participant_metadata_str = job.participant.metadata # Anteriormente getattr(job, 'metadata', None)

        if not participant_metadata_str:
            logging.error("No se pudieron obtener los metadatos del participante (job.participant.metadata está vacío o es None). "
                          "Estos metadatos son necesarios para extraer chatSessionId, username, etc. No se puede continuar.")
            await job.shutdown() # Asegurar shutdown antes de salir
            return

        logging.debug(f"Metadata string obtenida del job: {participant_metadata_str}")
        parsed_user_info = parse_participant_metadata(participant_metadata_str)
        user_id = parsed_user_info.get("userId")
        username = parsed_user_info.get("username", "Usuario") 
        chat_session_id = parsed_user_info.get("chatSessionId")
        tavus_replica_id = parsed_user_info.get("tavusReplicaId") # Asegúrate que parse_participant_metadata los devuelve
        tavus_persona_id = parsed_user_info.get("tavusPersonaId") # Asegúrate que parse_participant_metadata los devuelve
        
        # Se necesitaría la identidad del participante objetivo para encontrar el objeto RemoteParticipant.
        # Asumimos que está en los metadatos parseados, por ejemplo, como 'participantIdentity'.
        target_participant_identity = parsed_user_info.get("targetParticipantIdentity")

        if not chat_session_id:
            logging.error("chatSessionId no encontrado en los metadatos del job. No se puede iniciar el agente.")
            await job.shutdown() # Asegurar shutdown antes de salir
            return

        if not target_participant_identity:
            logging.error("targetParticipantIdentity no encontrado en los metadatos del job. No se puede iniciar el agente para un participante específico.")
            # Decidir si continuar sin un participante objetivo o salir. Por ahora, salimos.
            await job.shutdown() # Asegurar shutdown antes de salir
            return

        logging.info(f"Metadata parseada del job: userId='{user_id}', username='{username}', chatSessionId='{chat_session_id}', targetParticipantIdentity='{target_participant_identity}'")

        # Usar variables de entorno para la URL base de la API
        base_url = os.getenv("NEXT_PUBLIC_API_URL")
        if not base_url:
            logging.error("NEXT_PUBLIC_API_URL no está configurada en las variables de entorno.")
            await job.shutdown() # Asegurar shutdown antes de salir
            return
        
        http_session = aiohttp.ClientSession() # Crear la sesión aquí

        stt_plugin, llm_plugin, vad_plugin, tts_plugin = await _setup_plugins(job)
        if not all([stt_plugin, llm_plugin, vad_plugin, tts_plugin]):
            logging.error("No se pudieron configurar todos los plugins necesarios. Terminando el trabajo.")
            if http_session and not http_session.closed: await http_session.close()
            await job.shutdown() # Asegurar shutdown antes de salir
            return

        # NUEVO: Encontrar el RemoteParticipant objetivo
        target_remote_participant = await find_target_participant_in_room(job.room, target_participant_identity)

        if not target_remote_participant:
            # El logging de error ya está dentro de find_target_participant_in_room si usa el timeout
            logging.error(f"Participante objetivo '{target_participant_identity}' no encontrado. Terminando job.")
            if http_session and not http_session.closed: await http_session.close()
            await job.shutdown() # Asegurar shutdown antes de salir
            return
        
        logging.info(f"Participante objetivo '{target_remote_participant.identity}' encontrado/asignado.")

        # Crear la instancia de MariaVoiceAgent
        agent = MariaVoiceAgent( 
            http_session=http_session,
            base_url=base_url,
            target_participant=target_remote_participant, # Pasar el RemoteParticipant encontrado
            chat_session_id=chat_session_id,
            username=username,
            stt_plugin=stt_plugin,
            llm_plugin=llm_plugin,
            tts_plugin=tts_plugin,
            vad_plugin=vad_plugin,
        )
        
        # Iniciar el agente. Ahora usamos job.participant como el segundo argumento.
        logging.info(f"Agente Maria configurado. Iniciando para sala: {job.room.name}, como participante: {job.participant.identity}")
        await agent.start(job.room, job.participant) # Usar job.participant
        logging.info(f"MariaVoiceAgent iniciado y escuchando en la sala: {job.room.name}")

        # La creación de AgentSession se maneja internamente por el SDK después de job.connect()
        # y agent.start(). No es necesario crearla manualmente aquí.
        # La variable agent_session puede ser eliminada o su uso reconsiderado si es estrictamente necesaria
        # para _setup_and_start_tavus_avatar.
        # Por ahora, se asume que Tavus se puede iniciar con job.agent_session o una referencia similar
        # o que _setup_and_start_tavus_avatar se adaptará.

        # MODIFIED: Configurar e iniciar Tavus Avatar si las credenciales están presentes
        tavus_api_key = os.getenv("TAVUS_API_KEY")
        
        # Revisar cómo se obtiene agent_session para Tavus. 
        # Si job.connect() y agent.start() configuran job.agent_session, usar eso.
        # Si agent.session es la referencia correcta, usarla.
        # Este es un punto crítico para la integración de Tavus.
        # Por ahora, se asume que el agente mismo maneja su AgentSession o que el SDK la provee vía job.
        # La firma de _setup_and_start_tavus_avatar espera una AgentSession.
        # El SDK debería proveer job.agent_session después de job.connect() y agent.start().

        if hasattr(job, 'agent_session') and job.agent_session: # Verificar si el SDK la popula
            tavus_avatar_session = await _setup_and_start_tavus_avatar(
                agent_session_instance=job.agent_session, # Usar job.agent_session
                room=job.room,
                tavus_api_key=tavus_api_key,
                tavus_replica_id=tavus_replica_id,
                tavus_persona_id=tavus_persona_id
            )
        # else if agent.session: # Alternativa si el agente la expone
        #     tavus_avatar_session = await _setup_and_start_tavus_avatar(
        #         agent_session_instance=agent.session,
        #         room=job.room,
        #         tavus_api_key=tavus_api_key,
        #         tavus_replica_id=tavus_replica_id,
        #         tavus_persona_id=tavus_persona_id
        #     )
        else:
            logging.warning("AgentSession no está disponible a través de job.agent_session (o agent.session), no se puede iniciar Tavus Avatar.")

        # El agente está corriendo. El job_entrypoint esperará implícitamente aquí
        logging.info("Job entrypoint alcanzó el final del bloque try principal. El agente debería estar corriendo o intentando correr.")

    except Exception as e_job_main:
        # Esta excepción capturaría errores inesperados no manejados en las sub-funciones
        logging.error(f"Error inesperado en el flujo principal de job_entrypoint: {e_job_main}", exc_info=True)
        
    finally:
        logging.info(f"Iniciando bloque finally para limpieza en job_entrypoint para sala: {job.room.name}")
        
        if job.connected: # Solo llamar a shutdown si job está conectado
            try:
                logging.info("Ejecutando job.shutdown()...")
                await job.shutdown()
                logging.info("job.shutdown() completado.")
            except Exception as e_shutdown:
                logging.error(f"Error durante job.shutdown(): {e_shutdown}", exc_info=True)

        # MODIFIED: Descomentado y actualizado bloque de detención de Tavus
        if tavus_avatar_session:
            try:
                logging.info("Deteniendo Tavus AvatarSession...")
                await tavus_avatar_session.stop()
                logging.info("Tavus AvatarSession detenida.")
            except Exception as e_tavus_stop:
                logging.error(f"Error al detener Tavus AvatarSession: {e_tavus_stop}", exc_info=True)

        # Detener el agente de voz si está activo
        if agent: # agent puede ser None si falla antes de su inicialización
            try:
                logging.info("Deteniendo MariaVoiceAgent...")
                await agent.stop() 
                logging.info("MariaVoiceAgent detenido.")
            except Exception as e_agent_stop:
                logging.error(f"Error al detener MariaVoiceAgent: {e_agent_stop}", exc_info=True)

        # Marcar sesión como finalizada y solicitar resumen (si chat_session_id existe)
        if chat_session_id and http_session and not http_session.closed:
            try:
                logging.info(f"Marcando sesión {chat_session_id} como finalizada en la API.")
                async with http_session.put(f"{base_url}/api/sessions/{chat_session_id}") as resp:
                    if resp.status == 200:
                        logging.info(f"Sesión {chat_session_id} marcada como finalizada exitosamente.")
                    else:
                        error_text = await resp.text()
                        logging.error(f"Error al marcar sesión {chat_session_id} como finalizada ({resp.status}): {error_text}")
            except aiohttp.ClientError as e_conn:
                 logging.error(f"Error de cliente HTTP al finalizar/resumir sesión para {chat_session_id}: {e_conn}", exc_info=True)
            except Exception as e_session_finalize:
                logging.error(f"Excepción durante la finalización/resumen de sesión para {chat_session_id}: {e_session_finalize}", exc_info=True)
        
        # Cerrar la sesión aiohttp si fue creada
        if http_session and not http_session.closed:
            try:
                logging.info("Cerrando ClientSession de aiohttp...")
                await http_session.close()
                logging.info("ClientSession de aiohttp cerrada.")
            except Exception as e_close_session:
                logging.error(f"Error al cerrar ClientSession de aiohttp: {e_close_session}", exc_info=True)
        
        logging.info(f"Limpieza finalizada en job_entrypoint para la sala: {job.room.name}")

if __name__ == "__main__":
    opts = WorkerOptions(
        entrypoint_fnc=job_entrypoint,
        worker_type=WorkerType.ROOM,
        port=0  # Deshabilita el health-check HTTP y el servidor de tracing
    )
    cli.run_app(opts)