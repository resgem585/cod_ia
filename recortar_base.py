from proc_evm.bdd_sav import BaseDatos

bd = BaseDatos("patras_rest-grupos-q3.sav")

# Revisar cuántos casos hay antes
print("Antes:", bd.df.shape)

# Borrar filas donde q3 sea NaN, vacío o "-1"
bd.df = bd.df[
    bd.df["q3"].notna() &
    ~bd.df["q3"].astype(str).str.strip().isin(["", "-1", "-1.0"])
].copy()

bd.df.reset_index(drop=True, inplace=True)

# Revisar cuántos casos quedaron
print("Después:", bd.df.shape)

# Dejar solo variables necesarias
bd.incluir_vars(["q3", "SbjNum_grupo", "nse_agru", "ciudad"])

bd.guardar_bdd("patras_rest-grupos-q3_recortada.sav", forzar=True)