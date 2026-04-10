# 🤖 CAWL - Agente Local Inteligente

**CAWL** (Control & Action Web Loop) es un sistema de agente autónomo diseñado para ejecutar tareas complejas en tu máquina local utilizando modelos de lenguaje abiertos (como **Qwen 2.5 Coder** vía Ollama).

Implementa una arquitectura profesional de **Planner → Executor** con memoria persistente por proyecto, permitiendo que el agente aprenda del historial de ejecuciones y evite repetir trabajo.

---

## 🎯 Características Principales

- **Completamente Local**: Sin API, sin gastos, sin límites de tokens. Tu código es privado.
- **Arquitectura Planner/Executor**: Las tareas se descomponen automáticamente en pasos ejecutables usando LLM.
- **Memoria Persistente**: Cada proyecto mantiene su propio contexto en `.cawl/memory.json`, evitando contaminación entre proyectos.
- **Herramientas Integradas**: Lee/escribe archivos, busca patrones, ejecuta comandos de terminal.
- **Compatible con Ollama**: Soporta cualquier modelo compatible (Qwen, Llama, Mistral, etc.).
- **Confirmación de Seguridad**: Opción para confirmar comandos antes de ejecutarlos (configurable).

---

## 📋 Filosofía del Diseño

CAWL está pensado para un flujo de trabajo **híbrido**:

1. **Fase Superior (Planner)**: Tú (o una IA superior como Claude/GPT-4) diseñas tareas detalladas en Markdown.
2. **Fase Local (Executor)**: CAWL recibe la tarea, genera un plan, y lo ejecuta paso a paso en tu máquina, decidiendo qué herramientas usar sin preocuparse por costos de API.

**Ventajas**:

- La IA maestra diseña la estrategia (alto costo cognitivo pero barato en tokens).
- CAWL ejecuta sin restricciones de créditos.
- Tu código nunca sale de tu máquina.

---

## 🚀 Instalación

### Requisitos Previos

- **Python 3.10+**
- **Ollama** instalado y ejecutándose localmente
- El modelo `qwen2.5-coder:7b` (u otro compatible)

### Pasos de Instalación

1. **Clona o descarga** este repositorio:

   ```bash
   git clone <repo>
   cd cawl_agent
   ```

2. **Instala globalmente**:

   ```bash
   pip install -e .
   ```

   Esto instala las dependencias (`pyyaml`, `requests`, `colorama`) y registra el comando `cawl` en tu PATH.

3. **Verifica la instalación**:
   ```bash
   cawl status
   ```
   Debería mostrar la conexión a Ollama y el modelo disponible.

---

## ⚙️ Configuración

El archivo de configuración se encuentra en `cawl/config/config.yaml`:

```yaml
executor:
  model: "qwen2.5-coder:7b" # Modelo para ejecutar pasos
  confirm_commands: true # Pedir confirmación antes de comandos

planner:
  model: "qwen2.5-coder:7b" # Modelo para descomponer tareas

paths:
  base: "." # Directorio base del proyecto
  memory: ".cawl" # Carpeta de memoria
```

**Cambiar modelo**: Edita `config.yaml` o establece variables de entorno:

```bash
export CAWL_EXECUTOR_MODEL="llama2"
export CAWL_PLANNER_MODEL="mistral"
```

---

## 📖 Uso Rápido

### 1️⃣ Inicializar un Proyecto

```bash
cd /ruta/a/tu/proyecto
cawl init
```

Crea `.cawl/` con la estructura de memoria local. Cada proyecto tiene su propio contexto aislado.

### 2️⃣ Crear una Tarea

Escribe un archivo `.md` describiendo qué necesitas:

**`tareas/limpiar_logs.md`**:

```markdown
# Objetivo: Limpiar archivos de log antiguos

1. Buscar todos los archivos .log en la carpeta actual.
2. Mover los más antiguos (modificados hace >7 días) a una carpeta `backups/logs/`.
3. Comprimir la carpeta de backups.
4. Mostrar un resumen de qué se movió.
```

### 3️⃣ Ver el Plan Propuesto

Antes de ejecutar, verifica qué hará el agente:

```bash
cawl plan --task tareas/limpiar_logs.md
```

Ejemplo de salida:

```
Plan: 4 pasos
1. list_files - Listar .log en el directorio
2. glob_files - Encontrar logs antiguos
3. run_command - Mover a carpeta backup
4. run_command - Comprimir carpeta
```

### 4️⃣ Ejecutar la Tarea

```bash
cawl run --task tareas/limpiar_logs.md
```

El agente:

1. Descompone la tarea en pasos.
2. Para cada paso, decide qué herramientas usar.
3. Ejecuta (con confirmación si está habilitada).
4. Persiste resultados en memoria para futuras tareas.

### 5️⃣ Modo Interactivo (REPL)

```bash
cawl run
```

Entra en modo interactivo donde puedes escribir comandos:

```
> listar los archivos en src/
> crear un archivo test.py con contenido "print('hello')"
> buscar imports en todos los .py
```

### 6️⃣ Interfaz Gráfica (GUI)

Lanza la interfaz visual con tema oscuro tipo chat:

```bash
cawl ui [--project /ruta/al/proyecto] [--model modelo]
```

**Características de la GUI**:

- 💬 Chat estilo burbuja con conversación bidireccional
- 📁 Árbol de archivos del proyecto en el panel izquierdo
- 🌙 Tema oscuro estilo GitHub Dark
- 🔧 Herramientas integradas (leer, escribir, buscar archivos)
- 💾 Historial de conversación persistente

**Requisitos**: PyQt5 (incluido automáticamente en `pip install -e .`)

### 7️⃣ Ejecución Única (Sin Archivo)

```bash
cawl run -c "crear un archivo llamado resultado.txt con la lista de .py en src/"
```

---

## 🔧 Herramientas Disponibles

El LLM puede usar las siguientes herramientas automáticamente:

| Herramienta   | Descripción                                                      |
| ------------- | ---------------------------------------------------------------- |
| `read_file`   | Lee contenido de archivo. Soporta offset/limit para leer rangos. |
| `write_file`  | Escribe/sobrescribe archivo. Modo 'append' para añadir.          |
| `list_files`  | Lista archivos en directorio (max_depth, show_hidden).           |
| `grep_search` | Busca regex en archivos. Retorna líneas coincidentes.            |
| `glob_files`  | Busca archivos por patrón glob (ej: `**/*.py`).                  |
| `run_command` | Ejecuta comandos de shell (bash, cmd, etc).                      |

**Ejemplo**: El agente puede decidir autónomamente usar `grep_search` cuando necesita buscar texto en archivos, sin que le lo especifiques.

---

## 💾 Estructura del Proyecto

```
cawl_agent/
├── cawl/
│   ├── __init__.py
│   ├── cli/
│   │   └── main.py              # Punto de entrada (comandos cawl)
│   ├── config/
│   │   ├── config.py            # Gestor de configuración
│   │   └── config.yaml          # Configuración por defecto
│   ├── core/
│   │   ├── executor.py          # Ejecuta pasos individuales
│   │   ├── llm_client.py        # Cliente Ollama
│   │   ├── loop.py              # Bucle principal plan→execute
│   │   └── planner.py           # Descompone tareas en pasos
│   ├── memory/
│   │   ├── global_memory.py     # Memoria global
│   │   └── project_memory.py    # Memoria por proyecto
│   ├── tasks/
│   │   ├── parser.py            # Parser de archivos .md
│   │   └── ejemplo.md           # Ejemplo de tarea
│   └── tools/
│       ├── code_tools.py        # Herramientas de código (reservado)
│       ├── file_tools.py        # read_file, write_file, etc.
│       ├── registry.py          # Registro de herramientas
│       ├── system_tools.py      # run_command
│       └── terminal_tools.py    # Terminal tools (reservado)
├── tasks/
│   └── test.md                  # Ejemplos de tareas
├── setup.py                     # Configuración de instalación
└── README.md                    # Este archivo
```

---

## 📚 Ejemplos de Tareas

### Ejemplo 1: Análisis de Código

**`tareas/analizar_proyecto.md`**:

```markdown
# Objetivo: Analizar estructura del proyecto

1. Listar todos los archivos Python (.py) en src/
2. Para cada archivo, contar el número de funciones
3. Buscar imports no estándar (que no sean del stdlib)
4. Generar un reporte en analysis_report.md
```

### Ejemplo 2: Automatizar Backup

**`tareas/backup_diario.md`**:

```markdown
# Objetivo: Crear backup de archivos importantes

1. Buscar todos los .xlsx y .docx modificados hoy
2. Copiarlos a backups/YYYY-MM-DD/
3. Comprimir la carpeta
4. Registrar timestamps en logs/backup.log
```

### Ejemplo 3: Limpieza

**`tareas/limpieza_proyecto.md`**:

```markdown
# Objetivo: Limpiar proyecto

1. Eliminar todas las carpetas **pycache**
2. Eliminar archivos \*.pyc
3. Listar archivos temporales (_.tmp, _.bak)
4. Mostrar espacio liberado
```

---

## 🧠 Memoria y Contexto

CAWL mantiene memoria local del proyecto automáticamente:

- Cada ejecución se persiste en `.cawl/memory.json`
- Al planificar nuevas tareas, el LLM tiene contexto de trabajos previos
- Evita repetir pasos que ya se completaron
- El historial es **local al proyecto**, no se contamina entre proyectos

Ver historial reciente:

```bash
cat .cawl/memory.json
```

---

## 🛡️ Seguridad y Confirmaciones

Por defecto, `confirm_commands` está habilitado. Esto significa:

1. Cuando el agente decide ejecutar un comando de terminal, lo propone.
2. Tú confirmas (y/n) antes de que se ejecute.
3. Puedes ver exactamente qué ordenes se están ejecutando.

Para desactivar (en entornos confiables):

```yaml
executor:
  confirm_commands: false
```

---

## 🔗 Integración con IAs Superiores

### Flujo Recomendado

1. **En Claude/GPT-4**:

   ```
   "Crea un plan detallado en Markdown para [TAREA] con pasos específicos y verificables."
   ```

   Copias el resultado.

2. **En tu máquina**:

   ```bash
   cat > tareas/mi_tarea.md << 'EOF'
   [pega el plan de Claude]
   EOF

   cawl run --task tareas/mi_tarea.md
   ```

3. **CAWL ejecuta** automáticamente sin necesidad de más intervención.

---

## 📝 Troubleshooting

### Error: "Connection refused" a Ollama

**Solución**: Asegúrate de que Ollama está ejecutándose:

```bash
ollama serve
# En otra terminal:
cawl status
```

### Error: "Model not found"

**Solución**: Descarga el modelo:

```bash
ollama pull qwen2.5-coder:7b
```

### El agente no utiliza las herramientas correctas

 **Solución**: Verifica que el system prompt tenga las descripciones. En `cawl/cli/main.py` se construye dinámicamente. Si cambias herramientas, reinicia.

### Error: "cawl: command not found"

Si después de `pip install -e .` obtienes este error, el directorio Scripts de Python no está en tu PATH.

**Solución paso a paso:**

1. **Encuentra la ruta de Scripts:**

   ```bash
   python -c "import sys; import os; print(os.path.join(sys.prefix, 'Scripts'))"
   ```

   Esto te dará algo como: `C:\Users\TuUsuario\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\LocalCache\local-packages\Python310\Scripts`

2. **Agrega al PATH del sistema:**
   - Presiona `Win + R`, escribe `sysdm.cpl` y presiona Enter
   - Ve a la pestaña "Opciones avanzadas" → "Variables de entorno"
   - En "Variables del sistema", selecciona "Path" y haz clic en "Editar"
   - Haz clic en "Nuevo" y pega la ruta del paso 1
   - Haz clic en "Aceptar" en todas las ventanas

3. **Reinicia la terminal:**
   - Cierra completamente bash/cmd
   - Abre una nueva terminal
   - Prueba: `cawl status`

**Alternativa temporal (por sesión):**

```bash
export PATH="$PATH:$(python -c "import sys; import os; print(os.path.join(sys.prefix, 'Scripts'))")"
cawl status
```

**Verificación:**

```bash
cawl status
# Debería mostrar: Ollama: Connected, Model: qwen2.5-coder:7b, Available: Yes
```

---

## 🎓 Próximos Pasos

- [ ] Agregar soporte para multi-threading en ejecuciones largas
- [ ] Interfaz web para monitorear ejecuciones
- [ ] Persistencia de artefactos (archivos generados)
- [ ] Plugin system para herramientas custom
- [ ] Integración con Git para auto-commit

---

## 📄 Licencia

MIT - Úsalo libremente.

---

## 🤝 Contribuciones

Si encuentras issues o tienes mejoras, abre un PR o issue en el repositorio.
