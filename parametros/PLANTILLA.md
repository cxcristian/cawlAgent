# PLANTILLA DE PARÁMETROS — CAWL

> **PARA LA IA QUE GENERA ESTOS PARÁMETROS** (Claude, GPT-4, etc.):
> Estos parámetros se pasan a CAWL junto con la tarea para reducir
> alucinar del modelo de 7B. Sé conciso, concreto y específico.
> El 7B sigue reglas literales — si dices "no toques X", no lo tocará.

## Reglas para definir parámetros

1. **Tech stack explícito.** Lenguaje, framework, base de datos, versión de Python.
2. **Archivos existentes que NO deben modificarse.** Lista clara.
3. **Convenciones de código.** Naming, estilo, imports, tipo de comillas.
4. **Restricciones de seguridad.** No hardcodear credenciales, validar inputs, etc.
5. **Paths relativos al proyecto.** CAWL resuelve desde la raíz del proyecto.

---

## Formato

```markdown
# Parámetros del Proyecto

## Tech Stack
- [Lenguaje y versión]
- [Framework]
- [Base de datos]
- [Herramientas adicionales]

## Archivos a NO modificar
- [ruta/archivo.py] — razón
- [ruta/otro.py] — razón

## Convenciones de código
- [Estilo de nombrado]
- [Imports]
- [Comentarios]

## Restricciones
- [Regla de seguridad 1]
- [Regla de estilo 2]
```

---

## Ejemplo

```markdown
# Parámetros del Proyecto Clínica

## Tech Stack
- Python 3.10
- Flask 3.0
- SQLite
- SQLAlchemy ORM

## Archivos a NO modificar
- config.py — contiene credenciales de producción
- migrations/ — generados por Alembic automáticamente

## Convenciones de código
- snake_case para funciones y variables
- Imports ordenados: stdlib, third-party, local
- Docstrings en todas las funciones públicas
- Comillas dobles para strings

## Restricciones
- NUNCA hardcodear contraseñas o API keys
- Validar todos los inputs del usuario
- Usar SQLAlchemy, NO SQL crudo
- No eliminar archivos existentes sin confirmación
```
