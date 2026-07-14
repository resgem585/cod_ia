import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from zoneinfo import ZoneInfo
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from proc_evm.bdd_sav import BaseDatos

from utils import json_a_texto, generar_codigos_json, chunk, \
    limpiar_respuestas, escribir_json, extraer_codigos_validos, obtener_errores_validacion_codigos, \
    imprimir_errores_validacion


class Codi_IA:

    def __init__(self,
                 bd: BaseDatos,
                 libro_cods: Path,
                 hoja_cods: str,
                 var_verba: str,
                 id_var: str,
                 modelo: str,
                 system_prompt: str,
                 user_prompt: str,
                 ruta_salida: Path,
                 razonamiento: str = "low",
                 max_registros: int = 0,
                 tipo_cods: str = "texto",
                 batch_size: int = 50,
                 ruta_debug: Path = Path("debug"),
                 ignorar_vals=None,
                 min_codigos: int = 1,
                 max_codigos: int | None = None,
                 modo_prueba: bool = False,
                 llave_api="OPENAI_API_KEY",
                 ):

        load_dotenv()
        self.client = OpenAI(api_key=os.getenv(llave_api), timeout=120.0)
        self.bd = bd
        self.libro_cods = libro_cods
        self.hoja_cods = hoja_cods
        self.var_verba = var_verba
        self.id_var = id_var
        self.modelo = modelo
        self.razonamiento = razonamiento
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.ruta_salida = ruta_salida
        self.max_registros = max_registros

        if tipo_cods not in ["json", "texto"]:
            # if tipo_cods != "json" and tipo_cods != "texto":
            # if not (tipo_cods == "json" or tipo_cods == "texto"):
            raise ValueError("tipo_cods debe ser 'json' o 'texto'")
        self.tipo_cods = tipo_cods
        self.batch_size = batch_size
        self.ruta_debug = ruta_debug
        self.ruta_debug.mkdir(parents=True, exist_ok=True)
        self.ignorar_vals = ignorar_vals or (lambda verba: False)
        self.min_codigos = min_codigos

        self.modo_prueba = modo_prueba

        if min_codigos < 1:
            raise ValueError("min_codigos no puede ser menor que 1")

        if max_codigos is None:
            self.max_codigos = min_codigos
        else:
            self.max_codigos = max_codigos

        if self.max_codigos < self.min_codigos:
            raise ValueError("max_codigos no puede ser menor que min_codigos")

        if self.batch_size < 1:
            raise ValueError("batch_size debe ser mayor o igual a 1")

    def cargar_y_guardar_libro_codigos(self) -> Dict[Any, Any]:

        if self.libro_cods.suffix == ".json":
            lista_codigos_json = json.loads(self.libro_cods.read_text(encoding="utf-8"))

        elif self.libro_cods.suffix == ".xlsx":
            lista_codigos_json = generar_codigos_json(self.libro_cods, self.hoja_cods)
            escribir_json(self.ruta_debug / Path(f"{self.libro_cods.stem}_{self.hoja_cods}.json"), lista_codigos_json)
        else:
            raise ValueError("El archivo de libro de códigos debe ser .json o .xlsx")

        return lista_codigos_json

    def guardar_prompts_debug(self, numero_lote: int, system_prompt: str, user_prompt: str, ) -> None:

        ruta_debug_prompt = self.ruta_debug / f"prompts_lote_{numero_lote:02d}.txt"

        with open(ruta_debug_prompt, "w", encoding="utf-8") as archivo:
            archivo.write("=== SYSTEM PROMPT ===\n")
            archivo.write(system_prompt)
            archivo.write("\n\n=== USER PROMPT ===\n")
            archivo.write(user_prompt)

    def transformar_lista_codigos(self, lista_codigos_json) -> dict | str:

        if self.tipo_cods == "texto":
            return json_a_texto(lista_codigos_json)

        return lista_codigos_json

    def extraer_ids_y_verbas_filtrados(self, registros_select: list) -> tuple[list, list]:
        """
        Extrae las verbas y sus IDs desde el DataFrame.
        Después filtra las respuestas que deben ignorarse usando ignorar_vals.
        Retorna:
        - ids_filtrados
        - verbas_filtradas
        """
        verbas_en_crudo = self.bd.df.loc[registros_select, self.var_verba].astype(str).tolist()
        ids_en_crudo = self.bd.df.loc[registros_select, self.id_var].tolist()

        pares_filtrados = [
            (int(_id), verba_limpia)
            for _id, verba in zip(ids_en_crudo, verbas_en_crudo)
            if not self.ignorar_vals(verba_limpia := limpiar_respuestas(verba))
        ]

        ids_filtrados = [_id for _id, verba in pares_filtrados]
        verbas_filtradas = [verba for _id, verba in pares_filtrados]

        return ids_filtrados, verbas_filtradas

    def seleccionar_registros(self) -> list:
        # Selecciona los indices del DataFrame que se van a procesar.
        todos_registros = self.bd.df.index.tolist()

        if self.max_registros == 0:
            registros_select = todos_registros
            print(f"[INFO] Procesando TODAS las {len(registros_select)} filas válidas (modo completo).")
        else:
            registros_select = todos_registros[:self.max_registros]
            print(
                f"[INFO] Procesando solo {len(registros_select)} de "
                f"{len(todos_registros)} filas válidas (modo limitado)."
            )
        return registros_select

    def asignar_codigos(
            self,
            verbas: List[str],
            ids: List[int],
            lista_codigos: Dict[str, Any] | str,
            lista_codigos_json: Dict[str, Any]
    ) -> dict[int, list[list[int]]]:

        # CARGA DE PROMPTS
        system_template = Path(self.system_prompt).read_text(encoding="utf-8")
        user_template = Path(self.user_prompt).read_text(encoding="utf-8")

        # ESTRUCTURAS DE SALIDA
        resultados_todos_lotes: Dict[int, List[List[int]]] = {}
        bitacora = []

        # CÓDIGOS VÁLIDOS DEL LIBRO ORIGINAL
        codigos_validos = extraer_codigos_validos(lista_codigos_json)
        print(f"[INFO] Códigos válidos cargados: {len(codigos_validos)}")

        # Crear lotes de respuestas e IDs
        lotes_respuestas = chunk(verbas, self.batch_size)
        lotes_ids = chunk(ids, self.batch_size)

        # Preparar libro de códigos para el prompt
        if isinstance(lista_codigos, str):
            codigos_para_prompt = lista_codigos
        else:
            codigos_para_prompt = json.dumps(lista_codigos, ensure_ascii=False)

        # PROCESAR CADA LOTE
        for numero_lote, (ids_lote, respuesta_lote) in enumerate(zip(lotes_ids, lotes_respuestas), start=1):
            # Preparar texto de respuestas para el prompt
            respuestas_txt = "\n".join(
                f"{_id}: {respuesta}" for _id, respuesta in zip(ids_lote, respuesta_lote))

            # INYECTAR DATOS EN EL PROMPT
            user_prompt = user_template.format(
                BOOK_JSON=codigos_para_prompt,
                RESPUESTAS=respuestas_txt,
                MIN_CODIGOS=self.min_codigos,
                MAX_CODIGOS=self.max_codigos,
            )
            system_prompt = system_template

            #  Guardar prompts debug
            self.guardar_prompts_debug(numero_lote, system_prompt, user_prompt)

            respuesta_json = None
            max_intentos_lote = 2

            for intento in range(1, max_intentos_lote + 1):
                try:
                    t0 = time.perf_counter()

                    print(
                        f"Haciendo llamada a la Api {self.modelo}.. "
                        f"Lote:{numero_lote} Intento:{intento}"
                    )

                    respuesta = self.client.responses.create(
                        model=self.modelo,
                        input=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        reasoning={"effort": self.razonamiento},
                        text={
                            "verbosity": "low",
                            "format": {
                                "type": "json_object"
                            }
                        },
                    )

                    tiempo_transcurrido = time.perf_counter() - t0

                    # Guardar respuesta cruda en la carpeta debug
                    respuesta_cruda = respuesta.model_dump()
                    escribir_json(
                        self.ruta_debug / f"respuesta_cruda_lote_{numero_lote:02d}_intento_{intento}.json",
                        respuesta_cruda
                    )

                    # Extraer datos de tokens para bitácora
                    usage = respuesta.usage

                    bitacora.append({
                        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "modelo": self.modelo,
                        "lote": numero_lote,
                        "intento": intento,
                        "respuestas": len(respuesta_lote),
                        "reasoning_effort": respuesta.reasoning.effort,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "reasoning_tokens": usage.output_tokens_details.reasoning_tokens,
                        "total_tokens": usage.total_tokens,
                        "tiempo_s": round(tiempo_transcurrido, 3),
                    })

                    # Convertir salida del modelo a dict de Python
                    respuesta_json = json.loads(respuesta.output_text)

                    # Validar códigos devueltos por el modelo
                    errores = obtener_errores_validacion_codigos(
                        respuesta_json=respuesta_json,
                        codigos_validos=codigos_validos,
                    )

                    if errores:
                        imprimir_errores_validacion(
                            numero_lote=numero_lote,
                            intento=intento,
                            errores=errores,
                        )

                        if intento < max_intentos_lote:
                            print(f"[WARN] Reintentando lote {numero_lote} con razonamiento {self.razonamiento}...")
                            continue

                        raise ValueError(
                            f"El lote {numero_lote} devolvió códigos inexistentes "
                            f"o confianza 0 después de {max_intentos_lote} intentos."
                        )

                    print(
                        f"[OK] Codigos en lote {numero_lote} validados correctamente "
                        f"en intento {intento}. tiempo_s={round(tiempo_transcurrido, 3)}"
                    )

                    break

                except json.JSONDecodeError as e:
                    print(f"\n[ERROR] El lote {numero_lote}, intento {intento}, no devolvió JSON válido.")
                    print(f"[ERROR] Respuesta recibida: {repr(respuesta.output_text)}")

                    if intento < max_intentos_lote:
                        print(f"[WARN] Reintentando lote {numero_lote} con razonamiento {self.razonamiento}...")
                        continue

                    raise ValueError(
                        f"El lote {numero_lote} no devolvió JSON válido después de "
                        f"{max_intentos_lote} intentos."
                    ) from e

                except Exception as e:
                    if intento < max_intentos_lote:
                        print(
                            f"[WARN] Error en lote {numero_lote}, intento {intento}: {e}"
                        )
                        print(f"[WARN] Reintentando lote {numero_lote} con razonamiento {self.razonamiento}...")
                        continue

                    raise

            if respuesta_json is None:
                raise RuntimeError(
                    f"No se pudo obtener respuesta válida para lote {numero_lote}"
                )

            resultados_todos_lotes.update(respuesta_json)

        # LOG FINAL DE TOKENS
        self.guardar_bitacora(bitacora)

        return resultados_todos_lotes

    def guardar_bitacora(self, bitacora: list[dict]):
        df_bitacora = pd.DataFrame(bitacora)
        fila_total = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "modelo": self.modelo,
            "lote": "Total",
            "respuestas": df_bitacora["respuestas"].sum(),
            "reasoning_effort": df_bitacora["reasoning_effort"].iloc[0],
            "input_tokens": df_bitacora["input_tokens"].sum(),
            "output_tokens": df_bitacora["output_tokens"].sum(),
            "reasoning_tokens": df_bitacora["reasoning_tokens"].sum(),
            "total_tokens": df_bitacora["total_tokens"].sum(),
            "tiempo_s": round(df_bitacora["tiempo_s"].sum(), 3),
        }

        df_bitacora = pd.concat([df_bitacora, pd.DataFrame([fila_total])], ignore_index=True)
        df_bitacora.to_csv(self.ruta_debug / "bitacora.csv", index=False, )
        # Guardar en la bitacora el total
        print(
            f"[{self.modelo}] [TOKENS] TOTAL -> "
            f"in={fila_total['input_tokens']} "
            f"out={fila_total['output_tokens']} "
            f"reasoning={fila_total['reasoning_tokens']} "
            f"tot={fila_total['total_tokens']}"
        )

    def codificar_ia(self) -> Dict[str, Any]:

        # CARGAR LIBRO DE CÓDIGOS
        lista_codigos_json = self.cargar_y_guardar_libro_codigos()

        # PREPARAR CÓDIGOS PARA EL PROMPT
        lista_codigos_prompt = self.transformar_lista_codigos(lista_codigos_json)

        # SELECCIONAR REGISTROS
        registros_seleccionados = self.seleccionar_registros()

        # EXTRAER Y FILTRAR VERBAS
        ids_filtrados, verbas_filtradas = self.extraer_ids_y_verbas_filtrados(registros_seleccionados)

        # LIMPIAR VERBAS

        total_t0 = time.perf_counter()
        # ASIGNACIÓN DE CÓDIGOS CON LLM

        if self.modo_prueba:
            codigos_resultado = {identificador: [] for identificador in ids_filtrados}
            print(f"[MODO PRUEBA] Asignando códigos vacíos para {len(verbas_filtradas)} respuestas.")
        # Si no está en modo prueba, se llama a la función real de asignación
        else:
            codigos_resultado = self.asignar_codigos(verbas_filtradas, ids_filtrados, lista_codigos_prompt, lista_codigos_json)

        tiempo_total = time.perf_counter() - total_t0

        # ARMAR SALIDA FINAL
        salida_final = {
            "var_verba": self.var_verba,
            "codigos_confianza": codigos_resultado,
            "verbas": dict(zip(ids_filtrados, verbas_filtradas)),
            "modelo": self.modelo,
            "razonamiento": self.razonamiento,
            "min_codigos": self.min_codigos,
            "max_codigos": self.max_codigos,
            "tiempo": int(round(tiempo_total, 0)),
            "fecha": datetime.now(ZoneInfo("America/Mexico_City")).strftime("%Y-%m-%d %H:%M")
        }

        # GUARDAR JSON FINAL
        ruta = str(self.ruta_salida).format(**vars())
        escribir_json(ruta, salida_final)
        print(f"[OK] Resultados guardados en: {ruta}")

        return salida_final
