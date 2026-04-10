# CAWL Health Report

## Resumen
- Total archivos .py analizados: 24
- Total funciones: 50
- Total clases: 13

## TODOs y FIXMEs
- ninguno

## Prints sin migrar a status.emit()
- cawl/cli/main.py:236
- cawl/cli/main.py:240
- cawl/cli/main.py:241
- cawl/cli/main.py:243
- cawl/cli/main.py:246
- cawl/cli/main.py:249

## Dependencias externas en core/
- json
- re
- cawl.tools.registry
- cawl.core.llm_client
- cawl.core.status
- cawl.config.config

## Estado del StatusEmitter
- "Status emitter — canal de eventos en tiempo real para el agente.\nPermite que cualquier módulo (executor, planner, tools) emita mensajes\nde progreso que la terminal o la UI pueden suscribirse a escuchar."

## Conclusión
El proyecto CAWL tiene un buen estado general con 24 archivos .py, 50 funciones y 13 clases. No se encontraron TODOs ni FIXMEs en el código. Sin embargo, hay 5 prints que deberían ser migrados a status.emit(). Además, el archivo cawl/core/status.py existe y contiene información relevante.