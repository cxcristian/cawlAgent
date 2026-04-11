# PLANTILLA DE TAREA — CAWL

> **PARA LA IA QUE GENERA ESTA TAREA** (Claude, GPT-4, etc.):
> Este archivo será ejecutado por CAWL, un agente local con un modelo de 7B.
> El 7B es capaz de seguir instrucciones concretas pero tiende a alucinar si
> la tarea es ambigua, abstracta o demasiado grande. Sigue estas reglas al
> diseñar la tarea:

## Reglas para escribir tareas que CAWL pueda ejecutar

1. **Un archivo o acción por paso.** No pidas "crea el modelo y la API" en un solo paso. Sepáralo.
2. **Especifica paths absolutos o relativos claros.** Ejemplo: `src/models/patient.py`, NO "el archivo de modelos".
3. **Cada paso debe ser verificable.** El resultado debe ser un archivo escrito, una línea encontrada, un comando ejecutado.
4. **No asumas archivos que no existen.** Si necesitas que CAWL lea un archivo, asegúrate de que ya fue creado en un paso anterior.
5. **Proporciona el contenido completo cuando se escriba código.** No uses placeholders como "implementar luego".
6. **Evita instrucciones abstractas.** NO: "mejora la arquitectura". SÍ: "agrega validación de email en patient.py línea 15".
7. **Menciona la herramienta esperada en cada paso** (opcional pero recomendado): `[write_file]`, `[grep_search]`, `[read_file]`.

---

## Formato de la tarea

```markdown
# [Nombre de la tarea]

## Contexto
[Breve descripción del proyecto, tech stack, y qué se quiere lograr]

## Pasos

1. [Descripción concreta del paso 1]
2. [Descripción concreta del paso 2]
3. [Descripción concreta del paso 3]
...
N. [Último paso verificable]
```

---

## Ejemplo BUENO ✅

```markdown
# Crear modelo Patient para clínica

## Contexto
Proyecto Flask en C:\Users\Usuario\proyectos\clinica\. Python 3.10, SQLite.

## Pasos

1. Crear el archivo `src/models/patient.py` con una clase Patient que tenga:
   - id (Integer, primary key)
   - nombre (String 100, nullable=False)
   - email (String 100, unique)
   - telefono (String 20)
   - fecha_registro (DateTime, default=now)

2. Crear el archivo `src/models/__init__.py` que exporte la clase Patient.

3. Verificar que ambos archivos existen listándolos con list_files en src/models/.
```

## Ejemplo MALO ❌

```markdown
# Mejorar el sistema de pacientes

## Pasos

1. Crea los modelos necesarios para la clínica.
2. Implementa las APIs correspondientes.
3. Haz que funcione bien.
```

(Problemas: ambiguo, no especifica archivos, no verificable, asume conocimiento)
```
