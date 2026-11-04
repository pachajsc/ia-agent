import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape
from docx import Document
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

FUENTES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fuentes")
COLOR_TINTA = colors.HexColor("#16181D")
COLOR_SECUNDARIO = colors.HexColor("#555B66")
COLOR_ACENTO = colors.HexColor("#0B5D5E")
COLOR_LINEA = colors.HexColor("#C9CED6")

def ejecutar_agente(nombre_agente, prompt_instruccion, archivo_salida):
    """Ejecuta Claude Code como el agente indicado y exige que genere su archivo de salida.

    Claude devuelve exit 0 aunque no haya podido escribir, por lo que el código
    de salida no basta: el éxito se comprueba sobre el propio archivo.
    """
    print(f"🤖 [Iniciando] Agente: {nombre_agente}...")
    entorno = os.environ.copy()
    entorno["AGENTE_ACTUAL"] = nombre_agente
    fecha_previa = os.path.getmtime(archivo_salida) if os.path.exists(archivo_salida) else None

    # El prompt va por stdin porque --allowedTools consumiría un argumento posterior.
    # Sin terminal nadie puede aprobar permisos: la escritura se autoriza solo en outputs/.
    resultado = subprocess.run(
        ["claude", "-p", "--allowedTools", "Read", "Edit(outputs/**)"],
        input=prompt_instruccion,
        env=entorno,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    respuesta = f"{resultado.stdout}\n{resultado.stderr}".strip()

    if resultado.returncode != 0:
        raise RuntimeError(f"El agente {nombre_agente} falló:\n{respuesta}")
    if (
        not os.path.exists(archivo_salida)
        or os.path.getsize(archivo_salida) == 0
        or os.path.getmtime(archivo_salida) == fecha_previa
    ):
        raise RuntimeError(f"El agente {nombre_agente} no generó {archivo_salida}. Respondió:\n{respuesta}")
    if archivo_salida.endswith(".json"):
        try:
            with open(archivo_salida, encoding="utf-8") as f:
                json.load(f)
        except ValueError as e:
            raise RuntimeError(f"El agente {nombre_agente} generó un JSON inválido en {archivo_salida}: {e}")

    print(f"✅ [Completado] Agente: {nombre_agente}")
    return resultado.stdout

def extraer_y_guardar_temporal(docx_path, txt_temporal_path):
    """Extrae el texto del .docx y lo guarda en un .txt intermedio para que Claude lo lea limpiamente."""
    if not os.path.exists(docx_path):
        print(f"❌ Error: No se encontró el archivo de entrada {docx_path}")
        sys.exit(1)
    doc = Document(docx_path)
    texto_completo = []
    for para in doc.paragraphs:
        if para.text.strip():
            texto_completo.append(para.text)
            
    os.makedirs(os.path.dirname(txt_temporal_path), exist_ok=True)
    with open(txt_temporal_path, "w", encoding="utf-8") as f:
        f.write("\n".join(texto_completo))

def registrar_fuentes():
    """Incrusta IBM Plex Sans: el PDF se ve igual en cualquier equipo y su texto sigue siendo extraíble."""
    pdfmetrics.registerFont(TTFont("Plex", os.path.join(FUENTES_DIR, "IBMPlexSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Plex-SemiBold", os.path.join(FUENTES_DIR, "IBMPlexSans-SemiBold.ttf")))
    registerFontFamily("Plex", normal="Plex", bold="Plex-SemiBold", italic="Plex", boldItalic="Plex-SemiBold")

def texto_en_linea(texto):
    """Escapa el texto para el parser de ReportLab y convierte **negrita** de Markdown."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(texto))

def es_sitio_web(dato):
    return re.fullmatch(r"[\w.-]+\.[a-z]{2,}(/\S*)?", dato) is not None

def enlazar_contacto(dato):
    """Hace clicables el correo y los sitios web, sin cambiar el texto visible."""
    if "@" in dato:
        return f'<a href="mailto:{dato}">{escape(dato)}</a>'
    if es_sitio_web(dato):
        return f'<a href="https://{dato}">{escape(dato)}</a>'
    return escape(dato)

def bloque_contacto(datos, estilo):
    """Agrupa los datos de contacto en dos líneas: la persona primero y sus sitios web después."""
    personales = [d for d in datos if not es_sitio_web(d)]
    sitios = [d for d in datos if es_sitio_web(d)]
    lineas = [" · ".join(enlazar_contacto(d) for d in grupo) for grupo in (personales, sitios) if grupo]
    return Paragraph("<br/>".join(lineas), estilo)

def cabecera_de_puesto(cargo, fecha, ancho_total, estilo_cargo, estilo_fecha):
    """Cargo a la izquierda y fechas a la derecha. Es una tabla sin bordes: en el PDF queda como texto en orden de lectura."""
    ancho_fecha = 130
    tabla = Table(
        [[Paragraph(cargo, estilo_cargo), Paragraph(fecha, estilo_fecha)]],
        colWidths=[ancho_total - ancho_fecha, ancho_fecha],
        spaceBefore=11,
    )
    tabla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (1, 0), (1, 0), 0.6),  # Alinea la línea base de las fechas con la del cargo
    ]))
    tabla.keepWithNext = True
    return tabla

def markdown_a_pdf(input_md_path, output_pdf_path):
    """Parsea el archivo Markdown adaptado y genera un PDF de una columna, legible para personas y ATS."""
    print(f"🎨 Compilando diseño visual y generando PDF en {output_pdf_path}...")

    if not os.path.exists(input_md_path) or os.path.getsize(input_md_path) == 0:
        print(f"❌ Error: El archivo {input_md_path} está vacío o no existe. No se puede armar el PDF.")
        return

    registrar_fuentes()

    margen_lateral = 54
    padding_marco = 6  # Margen interno que ReportLab añade a cada marco de página
    ancho_texto = letter[0] - 2 * (margen_lateral + padding_marco)

    base = dict(fontName="Plex", textColor=COLOR_TINTA, fontSize=9.8, leading=14)
    style_nombre = ParagraphStyle("CV_Nombre", **{**base, "fontName": "Plex-SemiBold", "fontSize": 26, "leading": 30}, spaceAfter=2)
    style_titulo = ParagraphStyle("CV_Titulo", **{**base, "textColor": COLOR_ACENTO, "fontSize": 12, "leading": 16}, spaceAfter=7)
    style_contacto = ParagraphStyle("CV_Contacto", **{**base, "textColor": COLOR_SECUNDARIO, "fontSize": 9.2, "leading": 13.5})
    style_seccion = ParagraphStyle("CV_Seccion", **{**base, "fontName": "Plex-SemiBold", "textColor": COLOR_ACENTO, "fontSize": 11.5, "leading": 15}, spaceBefore=17, spaceAfter=3, keepWithNext=True)
    style_cargo = ParagraphStyle("CV_Cargo", **{**base, "fontName": "Plex-SemiBold", "fontSize": 10.5})
    style_fecha = ParagraphStyle("CV_Fecha", **{**base, "textColor": COLOR_SECUNDARIO, "fontSize": 9.2}, alignment=TA_RIGHT)
    style_empresa = ParagraphStyle("CV_Empresa", **{**base, "textColor": COLOR_SECUNDARIO}, spaceAfter=4, keepWithNext=True)
    style_subtitulo = ParagraphStyle("CV_Subtitulo", **{**base, "fontName": "Plex-SemiBold", "fontSize": 10.5}, spaceBefore=9, spaceAfter=3, keepWithNext=True)
    style_body = ParagraphStyle("CV_Body", **base, spaceAfter=4)
    style_bullet = ParagraphStyle(
        "CV_Bullet", **base, leftIndent=11, bulletIndent=1, spaceAfter=2.5,
        bulletFontName="Plex", bulletFontSize=9.8, bulletColor=COLOR_ACENTO,
    )
    style_etiqueta = ParagraphStyle("CV_Etiqueta", **base, spaceAfter=3)

    with open(input_md_path, "r", encoding="utf-8") as f:
        lineas = [linea.strip() for linea in f if linea.strip()]

    story = []
    nombre = ""
    contacto = []
    en_cabecera = True
    inicio_puesto = None

    def cerrar_puesto():
        """Agrupa el puesto en curso para que no se parta entre dos páginas."""
        nonlocal inicio_puesto
        if inicio_puesto is not None:
            story[inicio_puesto:] = [KeepTogether(story[inicio_puesto:])]
            inicio_puesto = None

    i = 0
    while i < len(lineas):
        linea = lineas[i]
        i += 1

        if en_cabecera:
            if linea.startswith("# "):
                nombre = linea[2:]
                story.append(Paragraph(texto_en_linea(nombre), style_nombre))
                continue
            if linea.startswith(("- ", "* ")):
                contacto.append(linea[2:])
                continue
            if not linea.startswith("## "):
                story.append(Paragraph(texto_en_linea(linea), style_titulo))
                continue
            en_cabecera = False
            if contacto:
                story.append(bloque_contacto(contacto, style_contacto))

        if linea.startswith("## "):
            cerrar_puesto()
            story.append(Paragraph(texto_en_linea(linea[3:]), style_seccion))
            regla = HRFlowable(width="100%", thickness=0.6, color=COLOR_LINEA, spaceBefore=0, spaceAfter=6)
            regla.keepWithNext = True
            story.append(regla)
        elif linea.startswith("### "):
            cerrar_puesto()
            titulo = linea[4:]
            if " — " in titulo:
                inicio_puesto = len(story)
                # Puesto: "Cargo — Empresa", seguido opcionalmente de una línea con las fechas
                cargo, empresa = titulo.split(" — ", 1)
                fecha = ""
                if i < len(lineas) and not lineas[i].startswith(("- ", "* ", "#")):
                    fecha = lineas[i]
                    i += 1
                story.append(cabecera_de_puesto(texto_en_linea(cargo), texto_en_linea(fecha), ancho_texto, style_cargo, style_fecha))
                story.append(Paragraph(texto_en_linea(empresa), style_empresa))
            else:
                story.append(Paragraph(texto_en_linea(titulo), style_subtitulo))
        elif linea.startswith(("- ", "* ")):
            contenido = linea[2:]
            if contenido.startswith("**"):
                # "**Etiqueta:** valores": la etiqueta en negrita ya marca el inicio de la línea
                story.append(Paragraph(texto_en_linea(contenido), style_etiqueta))
            else:
                story.append(Paragraph(texto_en_linea(contenido), style_bullet, bulletText="•"))
        else:
            story.append(Paragraph(texto_en_linea(linea), style_body))

    cerrar_puesto()

    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=letter,
        rightMargin=margen_lateral, leftMargin=margen_lateral, topMargin=40, bottomMargin=40,
        title=f"{nombre} — CV" if nombre else "CV",
        author=nombre,
    )
    doc.build(story)
    print(f"🏆 PDF generado con éxito total en: {output_pdf_path}")

def iniciar_optimizacion_cv():
    print("🚀 === INICIANDO OPTIMIZADOR DE CV MULTI-AGENTE (MIA-CV) ===")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if base_dir:
        os.chdir(base_dir)

    # Extraemos el texto de tu Word y lo volcamos en un archivo temporal para Claude
    extraer_y_guardar_temporal("datos/mi_cv_base.docx", "outputs/temp_cv_texto.txt")

    # --- PASO 1 (EN PARALELO): EXTRACTOR Y ANALISTA ---
    # CORRECCIÓN CLAVE: Le indicamos la ruta del archivo en lugar de inyectar el texto plano
    prompt_extractor = """Actúa estrictamente como el Extractor de Perfil según '.claude/agents/extractor.md'. 
En esta ejecución tu entrada es 'outputs/temp_cv_texto.txt', con el contenido real de mi CV original: úsalo en lugar de 'datos/mi_cv_base.md', que es una plantilla sin completar.
Cataloga todas mis competencias, logros y tecnologías de forma detallada y estructurada.
Guarda los resultados obligatoriamente en el archivo 'outputs/perfil_extraido.json'. No hagas nada más."""

    prompt_analista = """Actúa estrictamente como el Analista de Puesto según '.claude/agents/analista_puesto.md'. 
Lee la descripción de la vacante en 'datos/oferta_empleo.txt'. Identifica palabras clave (keywords ATS) y requerimientos del puesto. 
Guarda el reporte obligatoriamente en 'outputs/analisis_vacante.json'. No hagas nada más."""

    with ThreadPoolExecutor(max_workers=2) as pool:
        tareas = [
            pool.submit(ejecutar_agente, "Extractor", prompt_extractor, "outputs/perfil_extraido.json"),
            pool.submit(ejecutar_agente, "AnalistaPuesto", prompt_analista, "outputs/analisis_vacante.json"),
        ]
    for tarea in tareas:
        tarea.result()  # Propaga el error de cualquiera de los dos agentes

    # --- PASO 2 (SECUENCIAL): ADAPTADOR ---
    print("\n🧠 Procesamiento inicial finalizado. Iniciando fase estratégica de adaptación...")
    
    prompt_adaptador = """Actúa estrictamente como el Adaptador Profesional según '.claude/agents/adaptador.md'. 
Lee las capacidades mapeadas en 'outputs/perfil_extraido.json' y compáralas con las necesidades de 'outputs/analisis_vacante.json'. 
Reescribe mi CV adaptando los bullets de experiencia laboral para alinearlos con las palabras clave de la oferta. 
Genera una estructura de CV clara en Markdown usando títulos (#, ##, ###) y viñetas (-).
Escribe todo el resultado final obligatoriamente en el archivo 'outputs/CV_FINAL_ADAPTADO.md'. No inventes información falsa."""

    print(ejecutar_agente("Adaptador", prompt_adaptador, "outputs/CV_FINAL_ADAPTADO.md"))

    # --- PASO 3 (CONVERSIÓN FINAL): MARKDOWN A PDF ---
    markdown_a_pdf("outputs/CV_FINAL_ADAPTADO.md", "outputs/CV_FINAL_ADAPTADO.pdf")
    
    # Limpieza del archivo temporal
    if os.path.exists("outputs/temp_cv_texto.txt"):
        os.remove("outputs/temp_cv_texto.txt")
        
    print("\n🎉 === PROCESO FINALIZADO CON ÉXITO ===")
    print("El CV en formato PDF adaptado a la oferta está listo en: 'outputs/CV_FINAL_ADAPTADO.pdf'")

if __name__ == "__main__":
    try:
        iniciar_optimizacion_cv()
    except RuntimeError as e:
        print(f"❌ [Error] {e}")
        sys.exit(1)
