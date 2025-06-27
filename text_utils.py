"""
Módulo de utilidades de procesamiento de texto para el agente María.
Incluye funciones para limpieza de texto, conversión de números y generación de mensajes.
"""

import re
import random
import logging

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

def generate_welcome_message(username: str) -> str:
    """
    Genera un mensaje de bienvenida aleatorio de múltiples opciones variadas.
    Todos los mensajes mantienen el tono empático y especializado en ansiedad.
    
    Args:
        username: El nombre del usuario
        
    Returns:
        Un mensaje de bienvenida personalizado
    """
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

def detect_natural_closing_message(text: str, username: str) -> bool:
    """
    Detecta automáticamente si un mensaje es una despedida natural
    basándose en patrones de texto comunes.
    
    Args:
        text: El texto del mensaje a analizar
        username: El nombre del usuario para patrones específicos
        
    Returns:
        True si se detecta como mensaje de cierre natural
    """
    if not text:
        return False
        
    # Convertir a minúsculas para análisis
    lower_text = text.lower().strip()
    
    # Patrones de despedida con el nombre del usuario
    username_patterns = [
        f"gracias por confiar en mí hoy, {username.lower()}",
        f"gracias por compartir conmigo, {username.lower()}",
        f"ha sido un honor acompañarte, {username.lower()}",
        f"ha sido un placer acompañarte, {username.lower()}",
        f"que tengas un día tranquilo, {username.lower()}",
        f"que tengas un buen día, {username.lower()}",
        f"hasta pronto, {username.lower()}",
        f"hasta la próxima, {username.lower()}",
        f"cuídate mucho, {username.lower()}",
        f"cuídate bien, {username.lower()}",
        f"nos vemos pronto, {username.lower()}",
        f"espero verte pronto, {username.lower()}",
        f"que descanses, {username.lower()}",
        f"que te vaya bien, {username.lower()}",
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