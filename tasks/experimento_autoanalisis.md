# 🧪 Experimento: Auto-Análisis de CAWL

## Objetivo
CAWL debe analizarse a sí mismo como proyecto Python, generar un reporte
de salud del código y escribir el resultado en `cawl_health_report.md`.

---

## Pasos

1. Listar todos los archivos `.py` dentro de la carpeta `cawl/` del proyecto.

2. Contar cuántas funciones (`def `) y clases (`class `) hay en total
   en todos esos archivos usando grep_search.

3. Buscar todos los comentarios `# TODO` y `# FIXME` en el código.

4. Buscar si hay algún `print(` que debería ser un `status.emit()`
   (señal de que hay prints sin migrar al sistema de status).

5. Listar los imports externos usados en `cawl/core/`
   (líneas que empiezan con `import ` o `from ` que no sean `from cawl`).

6. Verificar que el archivo `cawl/core/status.py` existe y leer sus primeras 10 líneas.

7. Con toda la información recopilada, escribir un archivo `cawl_health_report.md`
   en la raíz del proyecto con el siguiente formato:

```markdown
# CAWL Health Report

## Resumen
- Total archivos .py analizados: X
- Total funciones: X
- Total clases: X

## TODOs y FIXMEs
(lista aquí los encontrados, o "ninguno" si no hay)

## Prints sin migrar a status.emit()
(lista aquí los archivos y líneas, o "ninguno")

## Dependencias externas en core/
(lista de imports externos únicos)

## Estado del StatusEmitter
(primeras líneas del archivo status.py)

## Conclusión
(párrafo breve evaluando la salud del proyecto)
```
