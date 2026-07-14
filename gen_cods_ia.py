from pathlib import Path
from proc_evm.bdd_sav import BaseDatos
from cod_ia import Codi_IA

MODELOS = ["gpt-5.4-nano"]
razonamiento = "low"
# gpt5 - 800 registros - 20 pesos. 40 r/$
# tres modelos 600 registros - 14 pesos      43 r/&
# gpt-5.4-nano low - 800 registros 2 pesos
# gpt-5-nano medium - 800 regustros 4 pesos
# gpt-5-nano medium - 800 regustros 8 pesos


print(f"[INFO] Modelos a ejecutar: {MODELOS} Razonamiento: {razonamiento}")


def ignorar_1(verba):
    if verba == "-1":
        return True
    return False


for modelo in MODELOS:
    bd = BaseDatos("Hamm-AB-CR.sav")

    print(f"\n=== Ejecutando con modelo: {modelo} ===")
    for cods_prompt in ["json"]:
        max_registros = 0
        var_verba = "p3"

        ruta_salida = Path(f"salida/Hamm-{var_verba}-{max_registros}-{modelo}-{razonamiento}_{cods_prompt}.json")
        ruta_debug = Path(f"debug/Hamm-{var_verba}-{max_registros}-{modelo}-{razonamiento}_{cods_prompt}")

        if ruta_salida.exists():
            print(f"[INFO] El archivo {ruta_salida} ya existe. Se omite la codificación.")
        else:
            print("[INFO] Iniciando la codificación...")

            codif = Codi_IA(
                bd,
                Path("Codigos-Hamm-R5.xlsx"),
                "POS",
                var_verba,
                "SbjNum",
                modelo,
                f"prompts/system_{cods_prompt}.txt",
                f"prompts/user_{cods_prompt}.txt",
                ruta_salida,
                razonamiento,
                max_registros,
                cods_prompt,
                50,
                ruta_debug,
                ignorar_1,
                1,
                10,
                False,

            )
            codif.codificar_ia()
