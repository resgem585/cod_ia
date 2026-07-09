import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


def cargar_json(path: Path | str) -> Any:
    """
    Carga un archivo JSON desde disco.
    """
    path = Path(path)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalizar_codigo(valor: Any) -> int:
    """
    Convierte un código recibido desde JSON a int.

    Soporta:
    - 102
    - "102"
    - 102.0
    - "102.0"
    """
    try:
        numero = float(valor)

        if numero.is_integer():
            return int(numero)

        raise ValueError(f"Código no entero: {valor}")

    except (ValueError, TypeError):
        raise ValueError(f"Código inválido: {valor}")


def extraer_codigos_libro(libro: Any) -> Set[int]:
    """
    Extrae todos los códigos existentes del libro de códigos en JSON.

    Funciona con libro plano:
    {
        "101": "Etiqueta",
        "102": "Etiqueta"
    }

    Y también con libro jerárquico:
    {
        "OPINIONES POSITIVAS": {
            "SABOR": {
                "101": "Adecuado sabor",
                "102": "Adecuado sabor coco"
            }
        }
    }
    """

    codigos_validos: Set[int] = set()

    def recorrer(nodo: Any):
        if isinstance(nodo, dict):
            for k, v in nodo.items():

                # Caso terminal típico:
                # "101": "Adecuado sabor"
                if isinstance(v, (str, int, float)):
                    try:
                        codigo = normalizar_codigo(k)
                        codigos_validos.add(codigo)
                    except ValueError:
                        # Si la llave no es código, la ignoramos
                        pass

                # Caso jerárquico
                else:
                    recorrer(v)

        elif isinstance(nodo, list):
            for item in nodo:
                recorrer(item)

    recorrer(libro)
    return codigos_validos


def extraer_codigos_salida(json_salida: Dict[str, Any]) -> List[Tuple[str, int]]:
    """
    Extrae los códigos del JSON de salida de IA.

    Estructura esperada:
    {
      "var_verba": "p3",
      "codigos_confianza": {
        "215841451": [
          [102, 95],
          [127, 70]
        ],
        "215841452": [
          [102, 85],
          [999, 70]
        ]
      }
    }

    Regresa:
    [
      ("215841451", 102),
      ("215841451", 127),
      ("215841452", 102),
      ("215841452", 999)
    ]
    """

    if "codigos_confianza" not in json_salida:
        raise KeyError("El JSON de salida no contiene la llave 'codigos_confianza'")

    codigos_confianza = json_salida["codigos_confianza"]

    if not isinstance(codigos_confianza, dict):
        raise TypeError("'codigos_confianza' debe ser un diccionario")

    codigos_extraidos: List[Tuple[str, int]] = []

    for id_respuesta, codigos in codigos_confianza.items():

        if not isinstance(codigos, list):
            raise TypeError(
                f"Los códigos del ID {id_respuesta} deben venir en una lista"
            )

        for item in codigos:

            # Formato esperado: [codigo, confianza]
            if not isinstance(item, list) or len(item) < 1:
                raise ValueError(
                    f"Formato inválido en ID {id_respuesta}: {item}"
                )

            codigo = normalizar_codigo(item[0])
            codigos_extraidos.append((str(id_respuesta), codigo))

    return codigos_extraidos


def validar_codigos_salida(
        salida_ia: Dict[str, Any],
        libro_codigos: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Valida que todos los códigos generados por la IA existan en el libro de códigos.

    - Solo imprime en consola los códigos que NO existen.
    - Regresa una lista con los códigos inválidos.
    - Si lanzar_error=True, detiene el proceso cuando encuentra inválidos.
    """

    codigos_validos = extraer_codigos_libro(libro_codigos)
    codigos_salida = extraer_codigos_salida(salida_ia)

    invalidos: List[Dict[str, Any]] = []

    for id_respuesta, codigo in codigos_salida:
        if codigo not in codigos_validos:
            invalidos.append({
                "id_respuesta": id_respuesta,
                "codigo_invalido": codigo
            })

    if invalidos:
        print("\nCÓDIGOS QUE NO EXISTEN EN EL LIBRO")
        print("-" * 60)

        for item in invalidos:
            print(
                f"ID: {item['id_respuesta']} | "
                f"Código no existe: {item['codigo_invalido']}"
            )

        print("-" * 60)
        print(f"Total códigos inexistentes: {len(invalidos)}")

    return invalidos


if __name__ == "__main__":

    # =========================
    # CONFIGURACIÓN
    # =========================

    json_salida_path = Path("salida/Hamm-p3-800-gpt-5.4-nano_json-1.json")
    json_libro_path = Path("debug/Hamm-p3-800-gpt-5.4-nano_json/Codigos-Hamm-R1_p3.json")

    # =========================
    # EJECUCIÓN
    # =========================

    salida_ia = cargar_json(json_salida_path)
    libro_codigos = cargar_json(json_libro_path)

    validar_codigos_salida(
        salida_ia=salida_ia,
        libro_codigos=libro_codigos,
    )