# Agente María para LiveKit

Agente de voz conversacional llamado María, diseñado para interactuar en sesiones de LiveKit. Este agente utiliza tecnologías de STT, LLM y TTS para proporcionar respuestas y asistencia.

## Características Principales (Ejemplo)

- Transcripción de voz a texto (STT) en tiempo real.
- Procesamiento de lenguaje natural (LLM) para entender y generar respuestas.
- Síntesis de voz (TTS) para las respuestas del agente.
- Capacidad de manejar sesiones de chat y metadatos de participantes.
- (Añadir más características específicas aquí)

## Requisitos Previos

- Python 3.9+
- Una cuenta de LiveKit y las credenciales necesarias.
- Claves API para los servicios utilizados (Deepgram, OpenAI, etc.).

## Instalación

1.  **Clonar el repositorio (si aplica):**
    ```bash
    git clone <URL_DEL_REPOSITORIO>
    cd LiveKit_Agent_MarIA
    ```

2.  **Crear y activar un entorno virtual:**
    ```bash
    python -m venv venv
    # En Windows
    venv\Scripts\activate
    # En macOS/Linux
    source venv/bin/activate
    ```

3.  **Instalar dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurar variables de entorno:**
    Crea un archivo `.env` en la raíz del proyecto y añade las siguientes variables (ejemplos):
    ```env
    LIVEKIT_API_KEY="YOUR_LIVEKIT_API_KEY"
    LIVEKIT_API_SECRET="YOUR_LIVEKIT_API_SECRET"
    LIVEKIT_URL="YOUR_LIVEKIT_URL"

    OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
    DEEPGRAM_API_KEY="YOUR_DEEPGRAM_API_KEY"
    # Añadir otras claves API necesarias (Cartesia, Silero si requieren config específica aquí)

    # Modelo de OpenAI a utilizar (ej. gpt-4o-mini, gpt-4)
    OPENAI_CHAT_MODEL="gpt-4o-mini"

    # URL base de tu backend para guardar mensajes (si es diferente al actual)
    BASE_API_URL="http://localhost:3000" # Ajusta según sea necesario
    ```
    Asegúrate de reemplazar los valores `YOUR_...` con tus credenciales reales. El `BASE_API_URL` es donde el agente intentará guardar los mensajes de la conversación.

## Uso

Para iniciar el agente, ejecuta el script principal:

```bash
python maria_agent.py
```

Esto conectará el agente al servidor de LiveKit especificado en tus variables de entorno y estará listo para unirse a las salas.

(Añadir más detalles sobre cómo interactuar con el agente o configuraciones específicas si es necesario).

## Archivo de Prompt del Sistema

El comportamiento y la personalidad base del agente María se definen en `maria_system_prompt.txt`. Puedes modificar este archivo para ajustar las instrucciones que recibe el LLM. El prompt utiliza plantillas como `{username}` y `{latest_summary}` que se reemplazan dinámicamente.

## Estructura del Proyecto

```
.
├── .gitignore         # Archivos y directorios ignorados por Git
├── maria_agent.py     # Lógica principal del agente
├── maria_system_prompt.txt # Plantilla de prompt para el LLM
├── README.md          # Este archivo
├── requirements.txt   # Dependencias de Python
└── venv/              # Entorno virtual (si se crea con ese nombre)
```