"""
Módulo de detección de emociones para adaptar la voz de María.
Analiza el sentimiento y emociones del usuario para ajustar los parámetros de voz.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum

class EmotionType(Enum):
    """Tipos de emociones que puede detectar el sistema."""
    ANSIEDAD = "ansiedad"
    TRISTEZA = "tristeza" 
    MIEDO = "miedo"
    ESTRES = "estres"
    FRUSTRACION = "frustracion"
    CONFUSION = "confusion"
    ESPERANZA = "esperanza"
    CALMA = "calma"
    NEUTRAL = "neutral"
    URGENCIA = "urgencia"
    DESESPERACION = "desesperacion"

class EmotionIntensity(Enum):
    """Niveles de intensidad emocional."""
    BAJA = "baja"
    MEDIA = "media"  
    ALTA = "alta"
    CRITICA = "critica"

class VoiceProfile:
    """Perfil de voz adaptativo según la emoción detectada."""
    
    def __init__(self, speed: float, emotion: List[str], voice_description: str):
        self.speed = speed  # Rango: -1.0 a 1.0 
        self.emotion = emotion  # Lista de emociones de Cartesia
        self.voice_description = voice_description
    
    def __repr__(self):
        return f"VoiceProfile(speed={self.speed}, emotion={self.emotion}, desc='{self.voice_description}')"

class EmotionDetector:
    """
    Detector de emociones basado en patrones de texto y palabras clave.
    Analiza el texto del usuario para determinar su estado emocional.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Patrones de palabras clave para diferentes emociones
        self.emotion_patterns = {
            EmotionType.ANSIEDAD: [
                # Palabras directas
                r'\b(ansiedad|ansioso|ansiosa|nervios|nervioso|nerviosa)\b',
                r'\b(preocup\w+|inquiet\w+|intranquil\w+)\b',
                r'\b(agitad\w+|alteradw+|desasoseg\w+)\b',
                # Frases y expresiones
                r'\b(no puedo parar de pensar|mi mente no para|no puedo relajarme)\b',
                r'\b(me siento agobiad\w+|me ahogo|no puedo respirar bien)\b',
                r'\b(tengo miedo de que|y si pasa|qué tal si)\b',
                r'\b(me da pánico|me da terror|me aterra)\b'
            ],
            
            EmotionType.TRISTEZA: [
                r'\b(triste|tristeza|melancolía|melancólic\w+)\b',
                r'\b(deprimid\w+|bajoneado|decaíd\w+)\b', 
                r'\b(llor\w+|ganas de llorar|quiero llorar)\b',
                r'\b(sin ganas|sin energía|sin ánimo)\b',
                r'\b(me siento vacío|me siento vacía|todo me da igual)\b'
            ],
            
            EmotionType.MIEDO: [
                r'\b(miedo|temor|terror|pánico|pavor)\b',
                r'\b(asustado|asustada|aterrorizado|aterrorizada)\b',
                r'\b(fobia|me da miedo|tengo miedo)\b',
                r'\b(me aterra|me horroriza|me espanta)\b'
            ],
            
            EmotionType.ESTRES: [
                r'\b(estrés|estresado|estresada|estresante)\b',
                r'\b(agobio|agobiad\w+|abrumad\w+)\b',
                r'\b(presión|presionad\w+|saturad\w+)\b',
                r'\b(no doy más|no puedo más|estoy al límite)\b',
                r'\b(sobrecargad\w+|desbordad\w+)\b'
            ],
            
            EmotionType.FRUSTRACION: [
                r'\b(frustrad\w+|frustrante|frustración)\b',
                r'\b(harto|harta|cansad\w+ de|fed up)\b',
                r'\b(impotencia|rabia|ira|molest\w+)\b',
                r'\b(no aguanto|no soporto|me irrita)\b'
            ],
            
            EmotionType.CONFUSION: [
                r'\b(confundid\w+|confusión|desoriented\w+)\b',
                r'\b(no entiendo|no sé qué|no sé cómo)\b',
                r'\b(perdid\w+|desubicad\w+|sin rumbo)\b',
                r'\b(no sé qué hacer|no sé por dónde empezar)\b'
            ],
            
            EmotionType.URGENCIA: [
                r'\b(urgente|rápido|ya|ahora mismo|inmediatamente)\b',
                r'\b(necesito ya|tengo que|debo urgente)\b',
                r'\b(no puedo esperar|es urgente|por favor rápido)\b'
            ],
            
            EmotionType.DESESPERACION: [
                r'\b(desesperación|desesperada|desesperado)\b',
                r'\b(sin esperanza|sin salida|no hay solución)\b',
                r'\b(no puedo más|ya no aguanto|estoy perdida|estoy perdido)\b',
                r'\b(quiero desaparecer|no vale la pena|todo está mal)\b'
            ],
            
            EmotionType.ESPERANZA: [
                r'\b(esperanza|esperanzad\w+|optimista)\b',
                r'\b(mejorando|mejor|progreso|avance)\b',
                r'\b(creo que puedo|siento que|tengo fe)\b'
            ],
            
            EmotionType.CALMA: [
                r'\b(calm\w+|tranquil\w+|relax\w+|sereno)\b',
                r'\b(en paz|equilibrio|estable)\b',
                r'\b(me siento bien|está todo bien|todo ok)\b'
            ]
        }
        
        # Intensificadores que aumentan la intensidad emocional
        self.intensifiers = [
            r'\b(muy|mucho|muchísimo|extremadamente|súper|ultra)\b',
            r'\b(demasiado|bastante|realmente|verdaderamente)\b',
            r'\b(increíblemente|terriblemente|horriblemente)\b',
            r'\b(totalmente|completamente|absolutamente)\b'
        ]
        
        # Palabras de crisis que indican alta intensidad
        self.crisis_indicators = [
            r'\b(crisis|emergencia|urgente|crítico|grave)\b',
            r'\b(no puedo más|al límite|breaking point|colapso)\b',
            r'\b(ayuda|socorro|SOS|auxilio)\b'
        ]

    def detect_emotions(self, text: str) -> Dict[EmotionType, EmotionIntensity]:
        """
        Detecta emociones en el texto del usuario.
        
        Args:
            text: Texto a analizar
            
        Returns:
            Diccionario con emociones detectadas y sus intensidades
        """
        if not text or not text.strip():
            return {EmotionType.NEUTRAL: EmotionIntensity.BAJA}
        
        text_lower = text.lower()
        detected_emotions = {}
        
        # Detectar cada tipo de emoción
        for emotion_type, patterns in self.emotion_patterns.items():
            intensity = self._calculate_intensity(text_lower, patterns)
            if intensity:
                detected_emotions[emotion_type] = intensity
                
        # Si no se detectó ninguna emoción específica, asignar neutral
        if not detected_emotions:
            detected_emotions[EmotionType.NEUTRAL] = EmotionIntensity.BAJA
            
        self.logger.info(f"Emociones detectadas en '{text[:50]}...': {detected_emotions}")
        return detected_emotions
    
    def _calculate_intensity(self, text: str, patterns: List[str]) -> Optional[EmotionIntensity]:
        """Calcula la intensidad de una emoción específica."""
        matches = 0
        has_intensifier = False
        has_crisis_indicator = False
        
        # Contar coincidencias de patrones emocionales
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                matches += 1
        
        if matches == 0:
            return None
            
        # Verificar intensificadores
        for intensifier in self.intensifiers:
            if re.search(intensifier, text, re.IGNORECASE):
                has_intensifier = True
                break
                
        # Verificar indicadores de crisis
        for crisis in self.crisis_indicators:
            if re.search(crisis, text, re.IGNORECASE):
                has_crisis_indicator = True
                break
        
        # Determinar intensidad basada en factores
        if has_crisis_indicator or matches >= 3:
            return EmotionIntensity.CRITICA
        elif has_intensifier or matches >= 2:
            return EmotionIntensity.ALTA
        elif matches >= 1:
            return EmotionIntensity.MEDIA
        else:
            return EmotionIntensity.BAJA

    def get_adaptive_voice_profile(self, detected_emotions: Dict[EmotionType, EmotionIntensity]) -> VoiceProfile:
        """
        Genera un perfil de voz adaptativo basado en las emociones detectadas.
        
        Args:
            detected_emotions: Emociones detectadas con sus intensidades
            
        Returns:
            Perfil de voz con parámetros ajustados
        """
        # Configuración base más calmada y pausada
        base_speed = -0.3  # Más lenta que el default (0) para ser más calmada
        base_emotions = []
        
        # Determinar emoción dominante (la de mayor intensidad)
        dominant_emotion = None
        max_intensity_value = 0
        
        intensity_values = {
            EmotionIntensity.BAJA: 1,
            EmotionIntensity.MEDIA: 2, 
            EmotionIntensity.ALTA: 3,
            EmotionIntensity.CRITICA: 4
        }
        
        for emotion, intensity in detected_emotions.items():
            intensity_val = intensity_values.get(intensity, 0)
            if intensity_val > max_intensity_value:
                max_intensity_value = intensity_val
                dominant_emotion = emotion
        
        # Ajustar parámetros según la emoción dominante
        if dominant_emotion == EmotionType.ANSIEDAD:
            if max_intensity_value >= 3:  # Alta o crítica
                return VoiceProfile(
                    speed=-0.5,  # Muy pausada para calmar
                    emotion=["positivity:high", "sadness:low"],  # Muy empática y gentil
                    voice_description="Voz muy empática y calmante para ansiedad intensa"
                )
            else:
                return VoiceProfile(
                    speed=-0.3,  
                    emotion=["positivity:low", "sadness:low"],  # Cálida y comprensiva
                    voice_description="Voz empática y serena para ansiedad moderada"
                )
                
        elif dominant_emotion == EmotionType.TRISTEZA:
            return VoiceProfile(
                speed=-0.4,  # Pausada y comprensiva
                emotion=["positivity:low", "sadness:high"],  # Comprensiva pero esperanzadora
                voice_description="Voz cálida y comprensiva para tristeza"
            )
            
        elif dominant_emotion == EmotionType.MIEDO:
            return VoiceProfile(
                speed=-0.5,  # Muy pausada para tranquilizar
                emotion=["positivity:high"],  # Positiva y protectora
                voice_description="Voz protectora y tranquilizadora para miedo"
            )
            
        elif dominant_emotion == EmotionType.ESTRES:
            return VoiceProfile(
                speed=-0.4,  # Pausada para reducir la sensación de prisa
                emotion=["positivity:low"],  # Ligeramente positiva sin ser abrumadora
                voice_description="Voz serena y equilibrada para estrés"
            )
            
        elif dominant_emotion == EmotionType.FRUSTRACION:
            return VoiceProfile(
                speed=-0.3,
                emotion=["positivity:low", "sadness:low"],  # Validante y comprensiva
                voice_description="Voz validante y paciente para frustración"
            )
            
        elif dominant_emotion == EmotionType.DESESPERACION:
            return VoiceProfile(
                speed=-0.6,  # Muy pausada y cuidadosa
                emotion=["positivity:high", "sadness:high"],  # Muy empática pero esperanzadora
                voice_description="Voz muy empática y esperanzadora para desesperación"
            )
            
        elif dominant_emotion == EmotionType.URGENCIA:
            return VoiceProfile(
                speed=-0.2,  # Menos pausada pero aún calmada
                emotion=["positivity:low"],  # Equilibrada y eficiente
                voice_description="Voz equilibrada pero atenta para urgencia"
            )
            
        elif dominant_emotion == EmotionType.CONFUSION:
            return VoiceProfile(
                speed=-0.4,  # Pausada para claridad
                emotion=["positivity:low"],  # Clarificadora y paciente
                voice_description="Voz clara y paciente para confusión"
            )
            
        elif dominant_emotion == EmotionType.ESPERANZA:
            return VoiceProfile(
                speed=-0.2,  # Ligeramente pausada pero energizada
                emotion=["positivity:high"],  # Positiva y alentadora
                voice_description="Voz alentadora y esperanzadora"
            )
            
        elif dominant_emotion == EmotionType.CALMA:
            return VoiceProfile(
                speed=-0.1,  # Naturalmente pausada
                emotion=["positivity:low"],  # Neutral y estable
                voice_description="Voz natural y estable para calma"
            )
            
        else:  # NEUTRAL o default
            return VoiceProfile(
                speed=-0.3,  # Pausada por defecto para ser más calmada
                emotion=[],  # Sin modificaciones emocionales especiales
                voice_description="Voz empática y calmada por defecto"
            )
    
    def get_context_summary(self, detected_emotions: Dict[EmotionType, EmotionIntensity]) -> str:
        """
        Genera un resumen del contexto emocional para logging.
        
        Args:
            detected_emotions: Emociones detectadas
            
        Returns:
            Resumen textual del estado emocional
        """
        if not detected_emotions:
            return "Estado emocional neutral"
            
        summaries = []
        for emotion, intensity in detected_emotions.items():
            emotion_name = emotion.value.replace('_', ' ').title()
            intensity_name = intensity.value
            summaries.append(f"{emotion_name} ({intensity_name})")
            
        return f"Estado emocional detectado: {', '.join(summaries)}" 