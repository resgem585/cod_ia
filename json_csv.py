import json
import csv
import os
from typing import Any, Dict, Tuple


def cargar_json(ruta):
    """
    Lee un archivo JSON y lo regresa como objeto Python.
    """
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def extraer_catalogo_etiquetas(catalogo_json: Any) -> Dict[int, str]:
    """
    Recorre recursivamente cualquier estructura de catálogo y construye:
        {codigo: etiqueta}

    Soporta:
    - dict plano: {"1": "Bosque", "2": "Mar"}
    - estructuras jerárquicas:
      SUPER-NETO -> NETO -> SUB-NETO -> SUB-SUB-NETO -> {codigo: etiqueta}

    Resultado:
    Siempre regresa un diccionario plano listo para lookup rápido.
    """
    resultado: Dict[int, str] = {}

    def es_dict_codigos(nodo: Any) -> bool:
        """
        Detecta si un nodo ya es un diccionario final tipo:
        {1: "Texto"} o {"1": "Texto"}
        """
        if not isinstance(nodo, dict) or not nodo:
            return False

        for k, v in nodo.items():
            try:
                int(k)
            except (ValueError, TypeError):
                return False

            if not isinstance(v, (str, int, float)):
                return False

        return True

    def recorrer(nodo: Any):
        """
        Recorre cualquier estructura dict/lista hasta encontrar códigos finales.
        """

        # Caso base: diccionario de códigos
        if es_dict_codigos(nodo):
            for code, label in nodo.items():
                try:
                    resultado[int(code)] = str(label)
                except (ValueError, TypeError):
                    pass
            return

        # Caso: dict anidado
        if isinstance(nodo, dict):
            for _, v in nodo.items():
                recorrer(v)
            return

        # Caso: lista
        if isinstance(nodo, list):
            for item in nodo:
                recorrer(item)
            return

    recorrer(catalogo_json)

    return resultado


def normalizar_id(valor):
    try:
        return str(int(float(valor)))
    except (ValueError, TypeError):
        return str(valor).strip()


def normalizar_codigo_confianza(item: Any, identificador: str) -> Tuple[int, int]:
    """
    Normaliza diferentes formatos de entrada a una tupla (codigo, confianza).

    Acepta:
    - [codigo, confianza]
    - (codigo, confianza)
    - {"codigo": x, "confianza": y}

    Valida:
    - que ambos sean enteros
    - que la confianza esté entre 0 y 100
    """

    # Detectar formato lista/tupla
    if isinstance(item, (list, tuple)) and len(item) == 2:
        codigo, confianza = item[0], item[1]

    # Detectar formato diccionario
    elif isinstance(item, dict):
        if "codigo" not in item or "confianza" not in item:
            raise ValueError(
                f"Estructura inválida en identificador {identificador}: {item!r}"
            )

        codigo = item["codigo"]
        confianza = item["confianza"]

    else:
        raise ValueError(
            f"Estructura inválida en identificador {identificador}: {item!r}"
        )

    # Convertir a enteros
    try:
        codigo = int(codigo)
        confianza = int(confianza)
    except (ValueError, TypeError):
        raise ValueError(
            f"Código/confianza inválidos en identificador {identificador}: {item!r}"
        )

    # Normalizar confianza entre 0 y 100
    confianza = max(0, min(100, confianza))

    return codigo, confianza


def crear_csv(
        json_respuestas_path,
        json_catalogo_path,
        csv_salida_path,
        guardar_cods=True,
        guardar_etis=True,
        guardar_conf=True,
        nombre_columnas="codigo"
):
    """
    Convierte el resultado de codificación JSON en un CSV estructurado.

    Parámetros:
    - json_respuestas_path: salida del LLM con codigos_confianza y verbas
    - json_catalogo_path: catálogo de códigos para mapear códigos a etiquetas
    - csv_salida_path: archivo CSV final
    - guardar_codigos: si True, guarda columnas con códigos
    - guardar_etiquetas: si True, guarda columnas con etiquetas
    - guardar_confianza: si True, guarda columnas con confianza
    - nombre_columnas: prefijo de columnas, ejemplo: "q3"

    Salida:
    identificador | verba | q3_codigo_1 | q3_etiqueta_1 | q3_confianza_1 | ...
    """

    # -------------------------
    # 1) Cargar archivos
    # -------------------------
    respuestas_json = cargar_json(json_respuestas_path)
    catalogo_json = cargar_json(json_catalogo_path)

    # Validar que al menos una salida esté activa
    if not guardar_cods and not guardar_etis and not guardar_conf:
        raise ValueError(
            "Debes activar al menos una opción: "
            "guardar_codigos=True, guardar_etiquetas=True o guardar_confianza=True"
        )

    # Llaves según tu JSON actual
    codigos_confianza = {
        normalizar_id(k): v
        for k, v in respuestas_json["codigos_confianza"].items()
    }
    verbas = {
        normalizar_id(k): v
        for k, v in respuestas_json["verbas"].items()
    }

    # Convertir catálogo a lookup plano: {codigo: etiqueta}
    etiqueta_codigos = extraer_catalogo_etiquetas(catalogo_json)

    # -------------------------
    # 2) Detectar máximo número de códigos por fila
    # -------------------------
    max_codigos = max(
        (len(codigos) for codigos in codigos_confianza.values()),
        default=0
    )

    # -------------------------
    # 3) Construir encabezado dinámico
    # -------------------------
    encabezado = ["identificador", "verba"]

    for i in range(1, max_codigos + 1):

        if guardar_cods:
            encabezado.append(f"{nombre_columnas}_codigo_{i}")

        if guardar_etis:
            encabezado.append(f"{nombre_columnas}_etiqueta_{i}")

        if guardar_conf:
            encabezado.append(f"{nombre_columnas}_confianza_{i}")

    # Crear carpeta de salida si no existe
    os.makedirs(os.path.dirname(csv_salida_path) or ".", exist_ok=True)

    # -------------------------
    # 4) Escribir CSV
    # -------------------------
    with open(csv_salida_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(encabezado)

        for identificador, pares in codigos_confianza.items():

            # Si el identificador no existe en verbas, Python marcará KeyError.
            verba = verbas[identificador]

            valores = []

            # Procesar cada par [codigo, confianza]
            for item in pares:
                codigo_int, confianza = normalizar_codigo_confianza(
                    item,
                    identificador
                )

                if guardar_cods:
                    valores.append(codigo_int)

                if guardar_etis:
                    if codigo_int not in etiqueta_codigos:
                        raise KeyError(
                            f"No se encontró etiqueta para el código {codigo_int} "
                            f"en identificador {identificador}"
                        )

                    valores.append(etiqueta_codigos[codigo_int])

                if guardar_conf:
                    valores.append(confianza)

            # Rellenar con vacíos si esa fila tiene menos códigos que el máximo
            faltantes = max_codigos - len(pares)

            for _ in range(faltantes):

                if guardar_cods:
                    valores.append("")

                if guardar_etis:
                    valores.append("")

                if guardar_conf:
                    valores.append("")

            fila = [identificador, verba] + valores
            writer.writerow(fila)

    print(f"CSV generado correctamente en: {csv_salida_path}")


# =========================
# EJECUCIÓN DIRECTA
# =========================
if __name__ == "__main__":

    # Parámetros de prueba / ejecución directa
    modelo = "gpt-5.4-nano"
    estudio = "Hamm"
    variable = "p3"
    registros = 800

    guardar_codigos = True
    guardar_etiquetas = True
    guardar_confianza = False

    # Ruta debug donde está guardado el catálogo JSON generado desde Excel
    ruta_debug = f"debug/{estudio}-{variable}-{registros}-{modelo}_json"

    # Rutas de entrada
    # json_respuestas = f"salida/{estudio}-{variable}-{registros}-{modelo}_json.json"
    json_respuestas = f"salida/Hamm-p3-800-gpt-5.4-nano_json-1.json"
    json_codigos = f"{ruta_debug}/Codigos-{estudio}-R1_{variable}.json"

    # -------------------------
    # Construir nombre de salida según opciones activas
    # -------------------------
    partes_salida = []

    if guardar_codigos:
        partes_salida.append("codigos")

    if guardar_etiquetas:
        partes_salida.append("etiquetas")

    if guardar_confianza:
        partes_salida.append("confianza")

    if not partes_salida:
        raise ValueError(
            "Debes activar al menos una opción: "
            "guardar_codigos=True, guardar_etiquetas=True o guardar_confianza=True"
        )

    tipo_salida = "_".join(partes_salida)

    # Ruta de salida
    csv_salida = f"csv/{estudio}_{variable}_codif_{tipo_salida}_{registros}.csv"

    # Ejecutar conversión
    crear_csv(
        json_respuestas,
        json_codigos,
        csv_salida,
        guardar_cods=guardar_codigos,
        guardar_etis=guardar_etiquetas,
        guardar_conf=guardar_confianza,
        nombre_columnas=variable
    )
