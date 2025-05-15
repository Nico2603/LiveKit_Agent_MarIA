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
from livekit.plugins import deepgram, openai, silero, cartesia #, tavus <- Comentar tavus
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

        logging.info(f"MariaVoiceAgent (ahora Agent) inicializada para chatSessionId: {self._chat_session_id}, Usuario: {self._username}")

    async def _send_custom_data(self, data_type: str, data_payload: Dict[str, Any]):
        try:
            logging.debug(f"Enviando DataChannel: type={data_type}, payload={data_payload}")
            if hasattr(self, 'session') and self.session and self.session.room and self.session.room.local_participant:
                 await self.session.room.local_participant.publish_data(json.dumps({"type": data_type, "payload": data_payload}))
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

    async def _handle_conversation_item_added(self, event):
        item = event.item
        if item.type == "message" and item.role == "assistant":
            ai_original_response_text = getattr(item, 'text_content', None)
            if not ai_original_response_text:
                return

            ai_message_id = item.id
            logging.info(f"Assistant message added (ID: {ai_message_id}): '{ai_original_response_text}'")

            processed_text_for_tts = ai_original_response_text
            is_closing_message = False
            video_payload = None

            if "[CIERRE_DE_SESION]" in processed_text_for_tts:
                logging.info(f"Se detectó señal [CIERRE_DE_SESION] en mensaje {ai_message_id}")
                processed_text_for_tts = processed_text_for_tts.replace("[CIERRE_DE_SESION]", "").strip()
                is_closing_message = True
                if self._username != "Usuario" and self._username not in processed_text_for_tts :
                     processed_text_for_tts = f"{processed_text_for_tts.rstrip('.')} {self._username}."
                
            video_tag_start = "[SUGERIR_VIDEO:"
            if video_tag_start in processed_text_for_tts:
                try:
                    start_index = processed_text_for_tts.find(video_tag_start)
                    end_index = processed_text_for_tts.find("]", start_index)
                    if start_index != -1 and end_index != -1:
                        video_info_str = processed_text_for_tts[start_index + len(video_tag_start):end_index]
                        parts = [p.strip() for p in video_info_str.split(',')]
                        if len(parts) >= 2:
                            video_title = parts[0]
                            video_url = parts[1]
                            logging.info(f"Se detectó sugerencia de video en mensaje {ai_message_id}: Título='{video_title}', URL='{video_url}'")
                            video_payload = {"title": video_title, "url": video_url}
                            processed_text_for_tts = processed_text_for_tts[:start_index].strip() + " " + processed_text_for_tts[end_index+1:].strip()
                            processed_text_for_tts = processed_text_for_tts.strip()
                except Exception as e:
                    logging.error(f"Error al procesar etiqueta SUGERIR_VIDEO para mensaje {ai_message_id}: {e}", exc_info=True)

            self._ai_message_meta[ai_message_id] = {
                "is_closing": is_closing_message,
                "suggested_video_payload": video_payload,
                "processed_text_for_tts": processed_text_for_tts
            }

            await self._send_custom_data("ai_response_generated", {
                "id": ai_message_id,
                "text": processed_text_for_tts, 
                "suggestedVideo": video_payload, 
                "isClosing": is_closing_message  
            })

def parse_participant_metadata(metadata_str: Optional[str]) -> Dict[str, Optional[str]]:
    """Parsea la metadata del participante y devuelve un diccionario con los campos relevantes."""
    if not metadata_str:
        return {
            "userId": None,
            "username": None,
            "chatSessionId": None,
        }
    try:
        data = json.loads(metadata_str)
        return {
            "userId": data.get("userId"),
            "username": data.get("username"),
            "chatSessionId": data.get("chatSessionId"),
        }
    except json.JSONDecodeError:
        logging.warning(f"Error al decodificar metadata del participante: {metadata_str}")
        return {
            "userId": None,
            "username": None,
            "chatSessionId": None,
        }

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
) -> Optional[Any]: # Optional[tavus.AvatarSession]: <- Cambiar tipo de retorno
    """Configura e inicia el avatar de Tavus si las credenciales están presentes."""
    if not (tavus_api_key and tavus_replica_id):
        logging.warning("Faltan TAVUS_API_KEY o TAVUS_STOCK_REPLICA_ID. El avatar de Tavus no se iniciará.")
        return None
    
    logging.info(f"Configurando Tavus AvatarSession con Replica ID: {tavus_replica_id} y Persona ID: {tavus_persona_id if tavus_persona_id else 'Default'}")
    # tavus_avatar = tavus.AvatarSession( # <- Comentar creación
    #     persona_id=tavus_persona_id,
    #     replica_id=tavus_replica_id,
    #     api_key=tavus_api_key,
    # )
    # try:
    #     await tavus_avatar.start(agent_session_instance, room=room)
    #     logging.info("Tavus AvatarSession iniciada y publicando video.")
    #     return tavus_avatar
    # except Exception as e_tavus:
    #     logging.error(f"Error al iniciar Tavus AvatarSession: {e_tavus}", exc_info=True)
    #     return None
    logging.warning("La funcionalidad de Tavus está comentada temporalmente.")
    return None # Retornar None ya que está comentado

async def _create_and_start_maria_agent(
    http_session: aiohttp.ClientSession,
    base_url: str,
    chat_session_id: Optional[str],
    username: str,
    stt_plugin: stt.STT,
    llm_plugin: llm.LLM,
    tts_plugin: tts.TTS,
    vad_plugin: vad.VAD,
    room: 'livekit.Room',
    participant: 'livekit.RemoteParticipant'
) -> Optional[MariaVoiceAgent]:
    """Crea e inicia el MariaVoiceAgent."""
    try:
        logging.info("Creando instancia de MariaVoiceAgent...")
        agent = MariaVoiceAgent(
            http_session=http_session,
            base_url=base_url,
            chat_session_id=chat_session_id,
            username=username,
            stt_plugin=stt_plugin,
            llm_plugin=llm_plugin,
            tts_plugin=tts_plugin,
            vad_plugin=vad_plugin,
        )
        logging.info(f"Agente Maria configurado. Iniciando para sala: {room.name}")
        await agent.start(room, participant)
        logging.info(f"MariaVoiceAgent iniciado y escuchando en la sala: {room.name}")
        return agent
    except Exception as e_agent_start:
        logging.error(f"Error crítico al crear o iniciar MariaVoiceAgent: {e_agent_start}", exc_info=True)
        return None

async def job_entrypoint(job: JobContext):
    """
    Job entrypoint
    """
    _initial_ctx_token.set(Context())
    logging.info(f"Iniciando trabajo de agente para la sala: {job.room.name}")

    agent = AIAgent(job_ctx=job)
    # Set up the plugins

    # --- Configuración Inicial y Obtención de Metadata ---
    nextjs_api_base_url = os.getenv("NEXTJS_API_BASE_URL", "http://localhost:3000")
    tavus_api_key = os.getenv("TAVUS_API_KEY")
    tavus_persona_id = os.getenv("TAVUS_PERSONA_ID")
    tavus_replica_id = os.getenv("TAVUS_STOCK_REPLICA_ID")

    chat_session_id: Optional[str] = None
    username: str = "Usuario"
    
    if job.participant and job.participant.metadata:
        participant_metadata = parse_participant_metadata(job.participant.metadata)
        logging.debug(f"Metadata de participante parseada: {participant_metadata}")
        user_id_for_api = participant_metadata.get("userId")
        
        username_from_meta = participant_metadata.get("username")
        if username_from_meta:
            username = username_from_meta
            logging.info(f"Username '{username}' obtenido de metadata.")
        elif job.participant and job.participant.name and job.participant.name != job.participant.identity:
            username = job.participant.name
            logging.info(f"Usando nombre de participante de LiveKit como username: {username}")
        
        session_id_from_meta = participant_metadata.get("chatSessionId")
        if session_id_from_meta:
            chat_session_id = session_id_from_meta
            logging.info(f"ChatSessionId '{chat_session_id}' obtenido de metadata.")
        else:
            logging.warning("chatSessionId no encontrado en metadata. Algunas funciones de guardado podrían fallar.")
    
    if not chat_session_id:
        logging.error("No se pudo obtener chatSessionId. El agente no podrá guardar mensajes ni finalizar la sesión correctamente.")
        # Considerar si el job debe terminar aquí si chat_session_id es crítico.
        # Por ahora, permite continuar, pero las funciones de guardado fallarán.

    # --- Inicialización de Componentes --- 
    agent: Optional[MariaVoiceAgent] = None
    tavus_avatar: Optional[Any] = None # Optional[tavus.AvatarSession] = None <- Cambiar tipo
    http_session: Optional[aiohttp.ClientSession] = None 

    try:
        http_session = aiohttp.ClientSession()

        # 1) Configuración de Plugins STT, LLM, VAD, TTS
        stt_plugin, llm_plugin, vad_plugin, tts_cartesia_plugin = await _setup_plugins(job)
        if not all([stt_plugin, llm_plugin, vad_plugin, tts_cartesia_plugin]):
            logging.error("Fallo en la configuración de plugins esenciales. Terminando el job.")
            # No es necesario un raise aquí si la lógica de limpieza en finally es robusta
            # y el job terminará naturalmente al salir de este try.
            return # Terminar el job si los plugins fallan

        # AgentSession se usa para Tavus, pero no directamente para el TTS de MariaVoiceAgent
        agent_session_instance = AgentSession( 
            llm=llm_plugin,
            stt=stt_plugin,
            vad=vad_plugin, 
            tts=None # TTS es manejado explícitamente por MariaVoiceAgent y Tavus (si usa el TTS de AgentSession)
        )
        logging.debug("AgentSession para Tavus (si aplica) configurada.")
            
        # 2) Configuración e inicio de Tavus Avatar
        tavus_avatar = await _setup_and_start_tavus_avatar(
            agent_session_instance, 
            job.room, 
            tavus_api_key, 
            tavus_replica_id, 
            tavus_persona_id
        )
        # Si Tavus falla, el agente de voz puede continuar.

        # 3) Creación e inicio de MariaVoiceAgent
        agent = await _create_and_start_maria_agent(
            http_session=http_session,
            base_url=nextjs_api_base_url,
            chat_session_id=chat_session_id,
            username=username,
            stt_plugin=stt_plugin,
            llm_plugin=llm_plugin,
            tts_plugin=tts_cartesia_plugin,
            vad_plugin=vad_plugin,
            room=job.room,
            participant=job.participant
        )
        if not agent:
            logging.error("Fallo al crear o iniciar MariaVoiceAgent. Terminando el job.")
            return # Terminar el job si el agente principal falla

        # El agente está corriendo. El job_entrypoint esperará implícitamente aquí
        # debido a las tareas asíncronas del agente (ej. listeners, bucles internos).
        # Si se necesita esperar explícitamente a que el agente termine o se cancele el job:
        # await job.wait_for_agent_shutdown() # o similar, si LiveKit provee tal mecanismo
        # Por ahora, se asume que el job se mantiene vivo mientras el agente lo esté.
        logging.info("Job entrypoint alcanzado el final del bloque try principal. El agente debería estar corriendo.")

    except Exception as e_job_main:
        # Esta excepción capturaría errores inesperados no manejados en las sub-funciones
        logging.error(f"Error inesperado en el flujo principal de job_entrypoint: {e_job_main}", exc_info=True)
        
    finally:
        logging.info(f"Iniciando bloque finally para limpieza en job_entrypoint para sala: {job.room.name}")
        
        # Detener el avatar de Tavus si está activo
        # if tavus_avatar: # <- Comentar esta sección también si es necesario
        #     try:
        #         logging.info("Deteniendo Tavus AvatarSession...")
        #         # await tavus_avatar.stop() # <- Comentar stop
        #         logging.info("Tavus AvatarSession detenida (funcionalidad comentada).")
        #     except Exception as e_tavus_stop:
        #         logging.error(f"Error al detener Tavus AvatarSession (funcionalidad comentada): {e_tavus_stop}", exc_info=True)

        # Detener el agente de voz si está activo
        if agent:
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
                async with http_session.put(f"{nextjs_api_base_url}/api/sessions/{chat_session_id}") as resp:
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