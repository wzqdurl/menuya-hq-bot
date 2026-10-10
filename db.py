"""MenúYa HQ — capa de base de datos compartida (Postgres).

Tanto la VM como Railway leen/escriben aquí. Nada vive solo en memoria
o en archivos locales: la empresa está VIVA en la DB.
"""
import os
import json

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_conn = None

def _connect():
    global _conn
    if _conn is None or _conn.closed:
        import psycopg2
        _conn = psycopg2.connect(DATABASE_URL)
        _conn.autocommit = True
    return _conn

def init_schema():
    """Crea las tablas si no existen. Se llama al arrancar el bot."""
    if not DATABASE_URL:
        print("DB: sin DATABASE_URL, modo memoria local", flush=True)
        return False
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    c = _connect().cursor()
    c.execute(sql)
    c.close()
    print("DB: esquema verificado", flush=True)
    return True

def _q(sql, params=(), fetch=None):
    c = _connect().cursor()
    c.execute(sql, params)
    r = None
    if fetch == "one":
        r = c.fetchone()
    elif fetch == "all":
        r = c.fetchall()
    c.close()
    return r

# ---- prospectos ----
def get_prospectos_nuevos(limit=10):
    rows = _q("SELECT negocio, telefono, zona FROM prospectos WHERE estado='nuevo' ORDER BY id LIMIT %s",
              (limit,), fetch="all") or []
    return [{"negocio": r[0], "telefono": r[1], "zona": r[2]} for r in rows]

def upsert_prospectos(lista):
    for p in lista:
        _q("""INSERT INTO prospectos (negocio, telefono, zona, estado)
              VALUES (%s,%s,%s,'nuevo')
              ON CONFLICT (telefono) DO UPDATE SET negocio=EXCLUDED.negocio, zona=EXCLUDED.zona""",
           (p.get("negocio"), p.get("telefono"), p.get("zona")))

# ---- acciones ----
def crear_accion(tipo, destino, mensaje):
    r = _q("INSERT INTO acciones (tipo, destino, mensaje) VALUES (%s,%s,%s) RETURNING id",
           (tipo, destino, mensaje), fetch="one")
    return r[0]

def get_acciones_pendientes():
    rows = _q("SELECT id, tipo, destino, mensaje FROM acciones WHERE estado='pendiente' ORDER BY id",
              fetch="all") or []
    return [{"id": r[0], "tipo": r[1], "destino": r[2], "mensaje": r[3]} for r in rows]

def get_acciones_aprobadas():
    rows = _q("SELECT id, tipo, destino, mensaje FROM acciones WHERE estado='aprobada' ORDER BY id",
              fetch="all") or []
    # marcar como reclamadas
    ids = [r[0] for r in rows]
    if ids:
        _q("UPDATE acciones SET estado='reclamada', actualizada=NOW() WHERE id = ANY(%s)", (ids,))
    return [{"id": r[0], "tipo": r[1], "destino": r[2], "mensaje": r[3]} for r in rows]

def set_accion_estado(aid, estado, resultado=""):
    _q("UPDATE acciones SET estado=%s, resultado=%s, actualizada=NOW() WHERE id=%s",
       (estado, resultado[:500], aid))

def count_acciones_hoy():
    r = _q("SELECT COUNT(*) FROM acciones WHERE creada::date = CURRENT_DATE", fetch="one")
    return r[0] if r else 0

def count_pendientes():
    r = _q("SELECT COUNT(*) FROM acciones WHERE estado='pendiente'", fetch="one")
    return r[0] if r else 0

# ---- actividad ----
def log(tipo, actor, detalle=""):
    _q("INSERT INTO actividad (tipo, actor, detalle) VALUES (%s,%s,%s)",
       (tipo, actor, detalle[:500]))

def get_actividad(limit=50):
    rows = _q("SELECT to_char(at,'YYYY-MM-DD\"T\"HH24:MI:SS'), tipo, actor, detalle FROM actividad ORDER BY id DESC LIMIT %s",
              (limit,), fetch="all") or []
    return [{"at": r[0], "tipo": r[1], "actor": r[2], "detalle": r[3] or ""} for r in rows]

# ---- estado / hechos ----
def set_estado(clave, valor):
    _q("INSERT INTO estado (clave, valor, actualizado) VALUES (%s,%s,NOW()) "
       "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, actualizado=NOW()",
       (clave, valor))

def get_estado(clave, default=""):
    r = _q("SELECT valor FROM estado WHERE clave=%s", (clave,), fetch="one")
    return r[0] if r else default

def set_hecho(clave, valor, fuente=""):
    _q("INSERT INTO hechos (clave, valor, fuente) VALUES (%s,%s,%s) "
       "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, fuente=EXCLUDED.fuente, actualizado=NOW()",
       (clave, valor, fuente))

def upsert_agente_vivo(nombre, data):
    import json
    _q("""INSERT INTO agentes_vivo (nombre, data, actualizado)
          VALUES (%s, %s::jsonb, NOW())
          ON CONFLICT (nombre) DO UPDATE SET data=EXCLUDED.data, actualizado=NOW()""",
       (nombre, json.dumps(data)))

def get_agentes_vivo():
    rows = _q("SELECT nombre, data, actualizado FROM agentes_vivo ORDER BY nombre", fetch="all")
    return [{"nombre": r[0], "data": r[1], "actualizado": r[2].isoformat() if r[2] else None} for r in (rows or [])]
