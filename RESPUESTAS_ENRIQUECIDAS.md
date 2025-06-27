# Sistema de Respuestas Enriquecidas para María

El agente María ahora soporta respuestas enriquecidas que incluyen elementos interactivos más allá del texto y TTS. Este documento describe todas las etiquetas disponibles y cómo usarlas.

## Etiquetas Disponibles

### 1. Imágenes
Muestra imágenes con título y descripción opcional.

**Formato:**
```
[IMAGEN: título, url, alt?, descripción?]
```

**Ejemplo:**
```
Te recomiendo esta técnica de respiración:

[IMAGEN: Técnica de respiración 4-7-8, https://ejemplo.com/respiracion.jpg, Diagrama de respiración, Esta imagen muestra los pasos para la técnica 4-7-8]

La técnica consiste en...
```

**Parámetros:**
- `título` (requerido): Título que se mostrará
- `url` (requerido): URL de la imagen (debe empezar con http)
- `alt` (opcional): Texto alternativo para accesibilidad (por defecto usa el título)
- `descripción` (opcional): Descripción adicional que aparece debajo

### 2. Enlaces
Crea botones de enlaces a recursos externos.

**Formato:**
```
[ENLACE: título, url, descripción?, tipo?]
```

**Ejemplo:**
```
Aquí tienes algunos recursos adicionales:

[ENLACE: Guía completa sobre ansiedad, https://example.com/guia-ansiedad, Una guía detallada sobre manejo de la ansiedad, guide]

[ENLACE: Artículo científico, https://example.com/articulo, Investigación reciente sobre técnicas de relajación, article]
```

**Parámetros:**
- `título` (requerido): Texto del botón
- `url` (requerido): URL del enlace (debe empezar con http)
- `descripción` (opcional): Descripción del enlace
- `tipo` (opcional): Tipo de enlace que afecta el color y icono
  - `article`: Artículos (azul, icono de documento)
  - `resource`: Recursos (verde, icono de estrella)
  - `guide`: Guías (morado, icono de bombilla)
  - `external`: Enlaces externos (gris, icono de enlace externo) - **por defecto**

### 3. Botones Interactivos
Crea botones que pueden ejecutar acciones específicas.

**Formato:**
```
[BOTON: título, acción, estilo?, icono?]
```

**Ejemplo:**
```
¿Te gustaría probar alguna de estas técnicas?

[BOTON: Iniciar ejercicio de respiración, start_breathing_exercise, primary, play]

[BOTON: Programar recordatorio, schedule_reminder, info, check]

[BOTON: Obtener más información, show_info, secondary, info]
```

**Parámetros:**
- `título` (requerido): Texto del botón
- `acción` (requerido): Identificador de la acción a ejecutar
- `estilo` (opcional): Estilo visual del botón
  - `primary`: Azul (por defecto)
  - `secondary`: Gris
  - `success`: Verde
  - `warning`: Amarillo
  - `info`: Cian
- `icono` (opcional): Icono a mostrar
  - `play`: Icono de reproducir
  - `check`: Icono de verificación
  - `info`: Icono de información
  - `activity`: Icono de actividad

### 4. Tarjetas Informativas
Muestra información estructurada en tarjetas con listas opcionales.

**Formato:**
```
[TARJETA: título, contenido, tipo?, item1|item2|item3...]
```

**Ejemplo:**
```
Aquí tienes algunos consejos para manejar la ansiedad:

[TARJETA: Técnica de Respiración Profunda, Esta técnica te ayuda a calmarte rápidamente cuando sientes ansiedad, technique, Inhala por 4 segundos|Mantén la respiración por 7 segundos|Exhala por 8 segundos|Repite 4 veces]

[TARJETA: Consejo Importante, Recuerda que es normal sentir ansiedad ocasionalmente, tip, Acepta tus emociones|No juzgues tus sentimientos|Busca apoyo cuando lo necesites]
```

**Parámetros:**
- `título` (requerido): Título de la tarjeta
- `contenido` (requerido): Contenido principal de la tarjeta
- `tipo` (opcional): Tipo de tarjeta que afecta el color y icono
  - `tip`: Consejos (amarillo, bombilla)
  - `technique`: Técnicas (azul, actividad)
  - `exercise`: Ejercicios (verde, play)
  - `info`: Información (cian, info) - **por defecto**
  - `warning`: Advertencias (naranja, triángulo)
- `items` (opcional): Lista de elementos separados por `|`

### 5. Videos (Compatibilidad)
Mantiene soporte para la etiqueta de videos existente.

**Formato:**
```
[SUGERIR_VIDEO: título, url]
```

**Ejemplo:**
```
Te recomiendo este video sobre técnicas de relajación:

[SUGERIR_VIDEO: Meditación guiada para la ansiedad, https://youtube.com/watch?v=ejemplo]
```

## Ejemplos Completos

### Respuesta con múltiples elementos:
```
Entiendo que estás sintiendo ansiedad. Te voy a compartir algunas técnicas que pueden ayudarte:

[TARJETA: Técnica de los 5 sentidos, Esta técnica te ayuda a conectarte con el presente, technique, Identifica 5 cosas que puedes ver|Identifica 4 cosas que puedes tocar|Identifica 3 cosas que puedes oír|Identifica 2 cosas que puedes oler|Identifica 1 cosa que puedes saborear]

[IMAGEN: Técnica de respiración 4-7-8, https://ejemplo.com/respiracion.jpg, Técnica de respiración, Esta imagen muestra el patrón de respiración recomendado]

¿Te gustaría probar la técnica de respiración ahora?

[BOTON: Iniciar ejercicio guiado, start_breathing_exercise, success, play]

[BOTON: Ver más técnicas, show_more_techniques, info, info]

También puedes consultar estos recursos adicionales:

[ENLACE: Guía completa sobre ansiedad, https://ejemplo.com/guia, Una guía detallada sobre el manejo de la ansiedad, guide]

[SUGERIR_VIDEO: Meditación para la ansiedad, https://youtube.com/watch?v=ejemplo]
```

### Respuesta con advertencia:
```
Es importante recordar que si sientes pensamientos de autolesión, debes buscar ayuda profesional inmediatamente.

[TARJETA: Busca ayuda profesional, Si tienes pensamientos de autolesión o suicidio, no estás solo y hay ayuda disponible, warning, Línea Nacional: 106|Policía: 123|Emergencias: 911|Bomberos: 119]

[BOTON: Contactar línea de crisis, contact_crisis_line, warning, info]

[ENLACE: Recursos de salud mental, https://ejemplo.com/recursos, Directorio de profesionales de salud mental, resource]
```

## Notas Importantes

1. **Orden de procesamiento**: Las etiquetas se procesan en el orden que aparecen en el texto
2. **URLs válidas**: Todas las URLs deben empezar con `http` o `https`
3. **Separación por comas**: Los parámetros se separan por comas, los items de listas por `|`
4. **Parámetros opcionales**: Se pueden omitir parámetros opcionales, pero mantener las comas si hay parámetros posteriores
5. **Compatibilidad**: El sistema mantiene compatibilidad con `suggestedVideo` existente
6. **Límites**: No hay límite en la cantidad de elementos enriquecidos por respuesta

## Mejores Prácticas

- **Combina elementos**: Usa diferentes tipos de contenido para crear respuestas más útiles
- **Sé específico**: Usa títulos descriptivos y acciones claras
- **Mantén la cohesión**: Asegúrate de que el contenido enriquecido complemente el texto
- **Considera el contexto**: Usa el tipo de elemento más apropiado para cada situación
- **Accesibilidad**: Siempre incluye texto alternativo para imágenes 