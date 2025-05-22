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
    WorkerType,
)
from livekit.rtc import RemoteParticipant, Room # RoomEvent eliminado de esta línea
# from livekit.protocol import RoomEvent # Eliminar esta línea o asegurarse que no esté activa
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

async def find_target_participant_in_room(room: Room, identity_str: str, timeout: float = 60.0) -> Optional[RemoteParticipant]:
    # Si ya está en la sala:
    for p in room.participants.values():
        if p.identity == identity_str: # Comparar con identity_str
            logging.info(f"Participante objetivo '{identity_str}' encontrado en la sala.")
            return p
    
    # Esperar a que el participante se conecte
    future = asyncio.Future()

    def on_participant_connected_handler(new_p: RemoteParticipant, *args): # La firma puede variar, *args para flexibilidad
        # El SDK livekit-rtc pasa RemoteParticipant directamente para PARTICIPANT_CONNECTED
        logging.debug(f"Participante conectado: {new_p.identity}, buscando: {identity_str}")
        if new_p.identity == identity_str: # Comparar con identity_str
            if not future.done():
                future.set_result(new_p)
            # Ya no necesitamos escuchar este evento una vez encontrado el participante
            room.off("participant_connected", on_participant_connected_handler)

    room.on("participant_connected", on_participant_connected_handler)

    try:
        logging.info(f"Esperando al participante objetivo '{identity_str}' para que se una a la sala (timeout: {timeout}s)...")
        target_participant = await asyncio.wait_for(future, timeout=timeout)
        logging.info(f"Participante objetivo '{identity_str}' se ha unido a la sala.")
        return target_participant
    except asyncio.TimeoutError:
        logging.error(f"Timeout esperando al participante objetivo '{identity_str}'.")
        # Asegurarse de remover el listener si hay timeout
        room.off("participant_connected", on_participant_connected_handler)
        return None
    finally:
        # Remover el listener en caso de que el futuro se resuelva por otra vía o haya error
        # Esto es una salvaguarda, ya que idealmente se remueve al encontrar el participante o en timeout
        room.off("participant_connected", on_participant_connected_handler)

async def job_entrypoint(job: JobContext):
    logging.info(f"JOB_ENTRYPOINT_STARTED for room {job.room.name}")
    http_session = None # Inicializar para el bloque finally

    try:
        # ① Conéctate al job
        await job.connect()
        logging.info(f"Conectado como agente: {job.room.local_participant.identity}")

        # Obtener la identidad del participante objetivo.
        # DEBERÁS REEMPLAZAR ESTO CON LA LÓGICA REAL PARA OBTENER `identity_str`
        # si no es a través de una variable de entorno.
        identity_str = os.getenv("LIVEKIT_TARGET_PARTICIPANT_IDENTITY")
        if not identity_str:
            logging.error("CRÍTICO: La identidad del participante objetivo (identity_str) no está definida. "
                          "Esta identidad es necesaria para encontrar al usuario en la sala. "
                          "Configura la variable de entorno LIVEKIT_TARGET_PARTICIPANT_IDENTITY. Abortando job.")
            return

        logging.info(f"Buscando participante objetivo con identidad: '{identity_str}' en la sala '{job.room.name}'.")

        # ② Busca al participante de usuario
        target_remote_participant = await find_target_participant_in_room(
            job.room,
            identity_str,
        )
        if not target_remote_participant:
            logging.error(f"No se encontró el participante de usuario con identidad '{identity_str}' en la sala '{job.room.name}'. Abortando job.")
            return

        logging.info(f"Participante de usuario '{target_remote_participant.identity}' encontrado en la sala '{job.room.name}'.")

        # ③ Extrae la metadata del usuario desde el participante
        metadata_str = target_remote_participant.metadata
        if not metadata_str:
            logging.error(f"El participante '{target_remote_participant.identity}' no tiene metadata. Abortando job.")
            return

        logging.debug(f"Metadata JSON recibida del participante '{target_remote_participant.identity}': {metadata_str}")
        
        parsed_metadata = parse_participant_metadata(metadata_str) # Esta función ya loguea errores internos
        if not parsed_metadata: # Si el parseo falló y devolvió un diccionario vacío o None
            logging.error(f"Fallo al parsear la metadata del participante '{target_remote_participant.identity}'. Abortando job.")
            return

        chat_session_id = parsed_metadata.get("chatSessionId")
        username = parsed_metadata.get("username")
        user_id = parsed_metadata.get("userId") # Asegúrate que este campo exista en tu metadata

        missing_fields = []
        if not chat_session_id: missing_fields.append("'chatSessionId'")
        if not username: missing_fields.append("'username'")
        if not user_id: missing_fields.append("'userId'") # Opcional, si lo necesitas

        if missing_fields:
            logging.error(f"Metadata del participante '{target_remote_participant.identity}' incompleta. "
                          f"Faltan campos o son nulos: {', '.join(missing_fields)}. Abortando job.")
            return
        
        logging.info(f"Metadata extraída para el usuario '{username}' (ID: {user_id}, ChatSessionID: {chat_session_id}).")

        # ④ Configura plugins
        stt_plugin, llm_plugin, vad_plugin, tts_plugin = await _setup_plugins(job)
        if not all([stt_plugin, llm_plugin, vad_plugin, tts_plugin]):
            logging.error("Error configurando uno o más plugins. Abortando job.")
            # No es necesario cerrar la http_session aquí, el finally lo hará.
            return
        logging.info("Todos los plugins han sido configurados exitosamente.")

        # Preparar http_session y base_url
        http_session = aiohttp.ClientSession() # Crear nueva sesión aiohttp
        base_url = os.getenv("NEXT_PUBLIC_APP_API_URL")
        if not base_url:
            logging.error("CRÍTICO: La variable de entorno NEXT_PUBLIC_APP_API_URL no está configurada. "
                          "No se podrán guardar mensajes. Abortando job.")
            # http_session se cerrará en el bloque finally
            return
        
        # ⑤ Instancia y arranca el agente apuntando al RemoteParticipant
        logging.info(f"Instanciando MariaVoiceAgent para el usuario '{username}' (ID: {user_id}) "
                     f"atendiendo al participante '{target_remote_participant.identity}'.")
        agent = MariaVoiceAgent( 
            http_session=http_session,
            base_url=base_url,
            target_participant=target_remote_participant,
            chat_session_id=chat_session_id,
            username=username,
            # userId=user_id, # Si tu constructor de MariaVoiceAgent lo acepta
            stt_plugin=stt_plugin,
            llm_plugin=llm_plugin,
            tts_plugin=tts_plugin,
            vad_plugin=vad_plugin,
        )
        
        logging.info(f"Iniciando MariaVoiceAgent en la sala '{job.room.name}' para el participante '{target_remote_participant.identity}'.")
        await agent.start(job.room, target_remote_participant) # El segundo argumento es el 'participant' que el Agent atiende
        logging.info(f"MariaVoiceAgent iniciado. Escuchando al participante '{target_remote_participant.identity}'.")

        # ⑥ (Opcional) Inicializa Tavus igual, si lo necesitas
        tavus_api_key = os.getenv("TAVUS_API_KEY")
        tavus_replica_id = os.getenv("TAVUS_REPLICA_ID")
        tavus_persona_id = os.getenv("TAVUS_PERSONA_ID")

        if tavus_api_key and tavus_replica_id and tavus_persona_id:
            if hasattr(agent, 'session') and agent.session:
                logging.info("Configurando e iniciando Tavus Avatar...")
                tavus_session = await _setup_and_start_tavus_avatar(
                    agent_session_instance=agent.session,
                    room=job.room, # _setup_and_start_tavus_avatar podría necesitar la room
                    tavus_api_key=tavus_api_key,
                    tavus_replica_id=tavus_replica_id,
                    tavus_persona_id=tavus_persona_id
                )
                if tavus_session:
                    logging.info("Tavus Avatar iniciado exitosamente.")
                else:
                    logging.warning("No se pudo iniciar Tavus Avatar (retornó None).")
            else:
                logging.warning("Tavus Avatar no se puede iniciar porque agent.session no está disponible o no está inicializada.")
        else:
            missing_tavus_vars = []
            if not tavus_api_key: missing_tavus_vars.append("TAVUS_API_KEY")
            if not tavus_replica_id: missing_tavus_vars.append("TAVUS_REPLICA_ID")
            if not tavus_persona_id: missing_tavus_vars.append("TAVUS_PERSONA_ID")
            if missing_tavus_vars:
                 logging.info(f"Tavus Avatar no se configurará porque faltan variables de entorno: {', '.join(missing_tavus_vars)}.")
        
        logging.info(f"Job entrypoint para la sala '{job.room.name}' ha completado la configuración. El agente está en ejecución.")
        # El SDK de LiveKit Agents maneja la espera y el cierre del job.
        # No se necesita `await job.run()` ni `await job.shutdown()` aquí.

    except Exception as e:
        logging.error(f"Error fatal e inesperado en el flujo principal de job_entrypoint para la sala '{job.room.name}': {e}", exc_info=True)
        # El SDK se encargará de la limpieza del job.
    finally:
        logging.info(f"Ejecutando bloque finally para limpieza en job_entrypoint para la sala: {job.room.name}")
        if http_session and not http_session.closed:
            await http_session.close()
        logging.info("Sesión aiohttp cerrada en job_entrypoint.") # <--- INDENTACIÓN CORRECTA
        # No llamar a job.shutdown() aquí. El SDK lo maneja.
        logging.info(f"Job entrypoint para la sala '{job.room.name}' ha finalizado su ejecución (normal o por error).")

# La función main() como la tenías antes de la refactorización de job_entrypoint no es necesaria
# si volvemos a la forma directa de cli.run_app(opts).
# Mantenemos la estructura if __name__ == "__main__" para ejecutar el worker.

# async def main():
#    logging.info("Configurando WorkerOptions para LiveKit Agent...")
#    
#    livekit_url = os.getenv("LIVEKIT_URL")
#    livekit_api_key = os.getenv("LIVEKIT_API_KEY")
#    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")
#
#    if not all([livekit_url, livekit_api_key, livekit_api_secret]):
#        logging.critical("CRÍTICO: Las variables de entorno LIVEKIT_URL, LIVEKIT_API_KEY, y LIVEKIT_API_SECRET son obligatorias y no están todas configuradas. El worker no puede iniciarse.")
#        return
#
#    worker_options = WorkerOptions(
#        # request_timeout=30, # Eliminado según la indicación
#    )
#    
#    # Registrar el entrypoint del job. El nombre "default_agent" es un ejemplo.
#    cli.register_agent(worker_options=worker_options, job_request_cb=job_entrypoint) 
#    
#    logging.info(f"Iniciando el worker de LiveKit Agents. Conectando a: {livekit_url}")
#    # El CLI usará las variables de entorno para la conexión si no se pasan argumentos.
#    await cli.run() # Esto es bloqueante y maneja el ciclo de vida del worker.


if __name__ == "__main__":
    logging.info("Configurando WorkerOptions y ejecutando la aplicación CLI...")
    # Asegúrate que LIVEKIT_URL, LIVEKIT_API_KEY, y LIVEKIT_API_SECRET están disponibles como variables de entorno
    # o pasadas como argumentos de línea de comandos, ya que cli.run_app las usará internamente.
    livekit_url = os.getenv("LIVEKIT_URL")
    livekit_api_key = os.getenv("LIVEKIT_API_KEY")
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not all([livekit_url, livekit_api_key, livekit_api_secret]):
        logging.critical("CRÍTICO: Las variables de entorno LIVEKIT_URL, LIVEKIT_API_KEY, y LIVEKIT_API_SECRET deben estar configuradas para que el worker pueda conectarse. Terminando.")
        # No es necesario salir explícitamente aquí si cli.run_app maneja esto, pero es una buena práctica verificar.
    else:
        logging.info(f"Variables de LiveKit encontradas. URL: {livekit_url[:20]}... Worker se conectará usando estas credenciales o los argumentos CLI.")

    opts = WorkerOptions(
        entrypoint_fnc=job_entrypoint, # Corregido entrypoint_fnc aquí
        worker_type=WorkerType.ROOM,
        port=int(os.getenv("LIVEKIT_AGENT_PORT", 0)) # Usar variable de entorno para el puerto, default 0 (deshabilitado)
    )

    # Ya no se usa asyncio.run(main()) directamente, sino cli.run_app(opts)
    # que maneja su propio bucle de eventos.
    try:
        logging.info("Iniciando cli.run_app(opts)...")
        cli.run_app(opts)
        # cli.run_app es bloqueante y maneja el ciclo de vida del worker.
    except KeyboardInterrupt:
        logging.info("Proceso interrumpido por el usuario (Ctrl+C) durante cli.run_app. Finalizando...")
    except Exception as e:
        logging.critical(f"Error crítico irrecuperable al ejecutar cli.run_app: {e}", exc_info=True)
    finally:
        logging.info("Proceso principal del worker (cli.run_app) finalizado.")