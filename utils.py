import os
import json
from pathlib import Path
from typing import Dict, Any, List, Iterator
import pandas as pd
import re


def normalizar_id(self, valor) -> str:
    if pd.isna(valor):
        raise ValueError("Se encontró un ID vacío o NaN")

    try:
        numero = float(valor)

        if numero.is_integer():
            return str(int(numero))

        return str(valor).strip()

    except (ValueError, TypeError):
        return str(valor).strip()


def limpiar_respuestas(texto: str) -> str:
    # Quita espacios y saltos de línea al inicio/final del texto completo.
    # Después separa el texto cada vez que encuentra uno o más saltos de línea.
    partes = re.split(r"\n+", texto.strip())
    # Aquí se guardan solo las partes que sí tienen texto útil.
    respuestas_limpias = []
    # Recorre cada fragmento separado por saltos de línea.
    for parte in partes:
        # Quita espacios al inicio y al final de cada fragmento.
        parte = parte.strip()
        # Si el fragmento quedó vacío, lo salta.
        # Esto evita que fragmentos sin texto útil terminen como: huele a medicina |  | producto de limpieza
        if not parte:
            continue
        # Reemplaza dobles espacios, tabs o por un solo espacio.
        parte = re.sub(r"\s+", " ", parte)
        # Guarda el fragmento ya limpio.
        respuestas_limpias.append(parte)
    # Une los fragmentos de una misma respuesta usando " | ".
    return " | ".join(respuestas_limpias)


def json_a_texto(libro: Dict[Any, Any] | List[Dict[str, Any]] | str) -> str:
    """
    Convierte un libro de códigos en una representación de texto plano.

    Soporta:
    - dict plano: {1: "Bosque", 2: "Mar"}
    - dict jerárquico
    - listas con estructuras anidadas

    La salida se usa para construir prompts legibles para el LLM.
    """

    def limpiar_eti(txt: str) -> str:
        """
        Elimina cualquier texto entre paréntesis.
        Ejemplo:
        "Bebidas (NETO)" -> "Bebidas"
        """
        return re.sub(r"\([^)]*\)", "", str(txt)).strip()

    def es_dict_codigos(nodo: Any) -> bool:
        """
        Detecta si el nodo es un diccionario terminal de códigos, por ejemplo:
        {1: "Bosque", 2: "Mar"}
        o
        {"1": "Bosque", "2": "Mar"}

        Regresa True solo si:
        - es dict
        - no está vacío
        - todas las llaves se pueden convertir a int
        - todos los valores son texto o números simples
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

    # Aquí se van acumulando las líneas de salida
    lines: List[str] = []

    def recorrer(nodo: Any, ruta: List[str]):
        """
        Recorre recursivamente cualquier estructura del libro de códigos.

        'ruta' guarda el camino jerárquico actual, por ejemplo:
        ["Bebidas", "Jugos"]
        """

        # Caso 1: ya estamos en un diccionario final de códigos -> etiqueta
        if es_dict_codigos(nodo):
            prefijo = " | ".join(ruta)

            for code, label in nodo.items():
                code_int = int(code)
                label_str = str(label)

                if prefijo:
                    lines.append(f"{prefijo} : CODIGO = {code_int}, ETIQUETA = {label_str}")
                else:
                    lines.append(f"CODIGO = {code_int}, ETIQUETA = {label_str}")
            return

        # Caso 2: diccionario jerárquico, seguimos bajando por cada llave
        if isinstance(nodo, dict):
            for k, v in nodo.items():
                recorrer(v, ruta + [limpiar_eti(k)])
            return

        # Caso 3: lista de nodos, recorrer cada elemento
        if isinstance(nodo, list):
            for item in nodo:
                recorrer(item, ruta)
            return

        # Caso raro: valor suelto que no encaja en los casos anteriores
        if ruta:
            lines.append(f"{' | '.join(ruta)} : {nodo}")
        else:
            lines.append(str(nodo))

    # Inicia el recorrido desde la raíz
    recorrer(libro, [])

    # Une todas las líneas en un solo texto
    return "\n".join(lines)


def chunk(lst: List[Any], n: int) -> Iterator[List[Any]]:
    """
    Divide una lista en lotes de tamaño n.

    Ejemplo:
    [1,2,3,4,5], n=2 -> [1,2], [3,4], [5]
    """
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def escribir_json(path: Path | str, obj: Any):
    """
    Escribe un objeto Python como JSON en disco.

    - Crea la carpeta si no existe
    - Usa indentación para que el archivo quede legible
    - Conserva caracteres Unicode
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# Expresiones regulares para detectar encabezados jerárquicos
# en la segunda columna del Excel.

RE_SUPER_NETO = re.compile(r"\(SUPER[- ]NETO\)", re.IGNORECASE)
RE_NETO = re.compile(r"\(NETO\)", re.IGNORECASE)
RE_SUB_NETO = re.compile(r"\(SUB[- ]NETO\)", re.IGNORECASE)
RE_SUB_SUB_NETO = re.compile(r"\(SUB[- ]SUB[- ]NETO\)", re.IGNORECASE)


def generar_codigos_json(
        xlsx_path: Path,
        hoja_cods: str
) -> Dict[Any, Any]:
    """
    Construye una estructura jerárquica a partir del Excel.

    Estructura esperada:
    SUPER-NETO -> NETO -> SUB-NETO -> SUB-SUB-NETO -> {codigo: etiqueta}

    Si no hay jerarquía en la hoja, regresa un dict plano:
    {
        1: "Texto 1",
        2: "Texto 2"
    }

    Nota:
    Cuando se serializa a JSON, las llaves numéricas terminan como string.
    """

    # Lee la hoja completa como objetos genéricos y reemplaza NaN por ""
    df = pd.read_excel(xlsx_path, sheet_name=hoja_cods, dtype="object").fillna("")

    # Se asume:
    # - primera columna = código
    # - segunda columna = texto/etiqueta
    col_codigos = df.iloc[:, 0]
    col_textos = df.iloc[:, 1]

    # ------------------------------------------------
    # 1) Detectar si la hoja contiene jerarquía
    # ------------------------------------------------
    hay_jerarquia = False

    for texto in col_textos.astype(str).str.strip():
        if (
                RE_SUPER_NETO.search(texto)
                or RE_NETO.search(texto)
                or RE_SUB_NETO.search(texto)
                or RE_SUB_SUB_NETO.search(texto)
        ):
            hay_jerarquia = True
            break

    # =========================
    # CASO SIMPLE: sin jerarquía
    # =========================
    if not hay_jerarquia:
        salida_simple: Dict[int, str] = {}

        for cod_celda, texto in zip(col_codigos, col_textos):
            cod_celda = str(cod_celda).strip()
            texto = str(texto).strip()

            # Saltar filas vacías
            if not cod_celda or not texto:
                continue

            # Convertir el código a entero
            try:
                code_int = int(float(cod_celda))
            except ValueError:
                continue

            salida_simple[code_int] = texto

        return salida_simple

    # =========================
    # CASO JERÁRQUICO
    # =========================

    # Diccionario final de salida
    dict_salida: Dict[str, Any] = {}

    # Variables que guardan el contexto jerárquico actual
    super_neto = ""
    neto = ""
    sub_neto = ""
    sub_sub_neto = ""

    for cod_celda, texto in zip(col_codigos, col_textos):
        cod_celda = str(cod_celda).strip()
        texto = str(texto).strip()

        # Ignorar fila totalmente vacía
        if texto == "" and cod_celda == "":
            continue

        # -------------------------
        # SUPER-NETO
        # -------------------------
        if RE_SUPER_NETO.search(texto):
            super_neto = texto
            neto = ""
            sub_neto = ""
            sub_sub_neto = ""

            dict_salida.setdefault(super_neto, {})
            continue

        # -------------------------
        # NETO
        # -------------------------
        if RE_NETO.search(texto):
            # Si aparece un NETO sin SUPER-NETO previo,
            # se crea una raíz artificial.
            if not super_neto:
                super_neto = "ROOT"
                dict_salida.setdefault(super_neto, {})

            neto = texto
            sub_neto = ""
            sub_sub_neto = ""

            dict_salida[super_neto].setdefault(neto, {})
            continue

        # -------------------------
        # SUB-NETO
        # -------------------------
        if RE_SUB_NETO.search(texto):
            if not super_neto:
                super_neto = "ROOT"
                dict_salida.setdefault(super_neto, {})

            # Si no hay NETO activo, esta fila no encaja bien en la jerarquía
            if not neto:
                continue

            sub_neto = texto
            sub_sub_neto = ""

            neto_val = dict_salida[super_neto].get(neto)

            if not isinstance(neto_val, dict):
                dict_salida[super_neto][neto] = {}

            dict_salida[super_neto][neto].setdefault(sub_neto, {})
            continue

        # -------------------------
        # SUB-SUB-NETO
        # -------------------------
        if RE_SUB_SUB_NETO.search(texto):
            if not super_neto:
                super_neto = "ROOT"
                dict_salida.setdefault(super_neto, {})

            # Necesita tener NETO y SUB-NETO activos
            if not neto or not sub_neto:
                continue

            sub_sub_neto = texto

            sub_neto_val = dict_salida[super_neto][neto].get(sub_neto)

            if not isinstance(sub_neto_val, dict):
                dict_salida[super_neto][neto][sub_neto] = {}

            dict_salida[super_neto][neto][sub_neto].setdefault(sub_sub_neto, {})
            continue

        # -------------------------
        # ITEMS REALES: código + etiqueta
        # -------------------------
        if cod_celda and texto:
            try:
                code_int = int(float(cod_celda))
            except ValueError:
                continue

            # Si nunca apareció un SUPER-NETO, se cuelga de ROOT
            if not super_neto:
                super_neto = "ROOT"
                dict_salida.setdefault(super_neto, {})

            llave_raiz = dict_salida[super_neto]

            # Caso: NETO -> {codigo: etiqueta}
            if neto and not sub_neto and not sub_sub_neto:
                if not isinstance(llave_raiz.get(neto), dict):
                    llave_raiz[neto] = {}

                llave_raiz[neto][code_int] = texto

            # Caso: NETO -> SUB-NETO -> {codigo: etiqueta}
            elif neto and sub_neto and not sub_sub_neto:
                if not isinstance(llave_raiz.get(neto), dict):
                    llave_raiz[neto] = {}

                if not isinstance(llave_raiz[neto].get(sub_neto), dict):
                    llave_raiz[neto][sub_neto] = {}

                llave_raiz[neto][sub_neto][code_int] = texto

            # Caso: NETO -> SUB-NETO -> SUB-SUB-NETO -> {codigo: etiqueta}
            elif neto and sub_neto and sub_sub_neto:
                if not isinstance(llave_raiz.get(neto), dict):
                    llave_raiz[neto] = {}

                if not isinstance(llave_raiz[neto].get(sub_neto), dict):
                    llave_raiz[neto][sub_neto] = {}

                if not isinstance(llave_raiz[neto][sub_neto].get(sub_sub_neto), dict):
                    llave_raiz[neto][sub_neto][sub_sub_neto] = {}

                llave_raiz[neto][sub_neto][sub_sub_neto][code_int] = texto

            # Si no cayó en ningún caso válido, la fila está mal posicionada
            else:
                raise ValueError(
                    f"Fila con código {cod_celda} y texto '{texto}' "
                    f"no encaja en la jerarquía actual."
                )

    return dict_salida


def extraer_codigos_validos(libro_codigos) -> set[int]:
    """
    Recorre el libro de códigos y extrae todos los códigos numéricos válidos.
    Funciona con libros simples y jerárquicos.
    """
    codigos_validos = set()

    def recorrer(nodo):
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                try:
                    codigo = int(float(clave))
                    codigos_validos.add(codigo)
                except (ValueError, TypeError):
                    pass

                recorrer(valor)

        elif isinstance(nodo, list):
            for elemento in nodo:
                recorrer(elemento)

    recorrer(libro_codigos)

    return codigos_validos

# =========================
# CONFIGURACION
# =========================

# xlsx_path = "Codigos-Patras-R1.xlsx"
# hoja_cods = "Q3"
# json_path = f"salida/Codigos-Patras-{hoja_cods}.json"
#
# =========================
# EJECUCION
# =========================
#
# data = generar_codigos_json(xlsx_path, hoja_cods)
# write_json(json_path, data)
#
# print(f"JSON generado en: {json_path}")
