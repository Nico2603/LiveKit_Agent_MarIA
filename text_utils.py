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
    Función desactivada - ya no se detectan despedidas automáticas por palabras clave.
    La sesión ahora finaliza únicamente por tiempo límite de 30 minutos.
    
    Args:
        text: El texto del mensaje a analizar (no usado)
        username: El nombre del usuario (no usado)
        
    Returns:
        Siempre False - detección automática desactivada
    """
    logging.info("Detección automática de despedidas desactivada - solo finalización por timeout de 30 minutos")
    return False 