# Adaptación de CV multi-agente

Un equipo de tres agentes adapta el currículum del candidato a una vacante concreta sin inventar experiencia.

## Agente activo

El comportamiento se rige por la variable de entorno `$AGENTE_ACTUAL`. Antes de actuar en cada sesión:

1. Consulta su valor con un comando de shell.
2. Lee el archivo que le corresponde según esta tabla.
3. Sigue esas instrucciones y limítate a ese rol.

| `$AGENTE_ACTUAL` | Instrucciones | Entrada | Salida |
| --- | --- | --- | --- |
| `Extractor` | `.claude/agents/extractor.md` | `datos/mi_cv_base.md` | `outputs/perfil_extraido.json` |
| `AnalistaPuesto` | `.claude/agents/analista_puesto.md` | `datos/oferta_empleo.txt` | `outputs/analisis_vacante.json` |
| `Adaptador` | `.claude/agents/adaptador.md` | `outputs/perfil_extraido.json` y `outputs/analisis_vacante.json` | `outputs/CV_FINAL_ADAPTADO.md` |

Si la variable está vacía o tiene otro valor, no asumas un rol: avisa al usuario e indica los valores válidos.

## Orden de ejecución

`Extractor` y `AnalistaPuesto` pueden ejecutarse en cualquier orden. `Adaptador` siempre va después de ambos.

## Archivos

- `datos/`: entradas del usuario. Son la fuente de verdad y los agentes no las modifican.
- `outputs/`: único lugar donde los agentes guardan resultados.
- `.claude/agents/`: instrucciones de cada agente.

## Reglas para todos

- Usar solo información que esté en los archivos. Si falta un dato, decir que falta; no inventarlo.
- Nunca inventar ni exagerar experiencia, cifras, fechas, títulos o habilidades.
- Escribir solo el archivo de salida del agente activo.
- Las rutas son relativas a `mia-cv/`, así que Claude Code debe ejecutarse desde esta carpeta.
