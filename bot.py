#!/usr/bin/env python3
"""MenúYa HQ en Railway — bot de Discord para dirigir la empresa 24/7.

EMPRESA VIVA:
- La VM empuja el ESTADO real del negocio cada 15 min (POST /estado): leads,
  prospectos, ingresos, últimos turnos. Los empleados lo leen en cada orden.
- /jefe: la coordinadora desglosa con el estado real -> departamentos ejecutan ->
  sintetiza. Si hacen falta acciones reales (ej: mandar WhatsApp), las propone
  como ACCION y el jefe las aprueba con botones. La VM las ejecuta.
- /ventas|/diseno|/soporte: hablan con el estado real en contexto.

Env vars: DISCORD_BOT_TOKEN, BOSS_ID, DAHL_API_KEY, DISCORD_WEBHOOK_URL,
           BRIDGE_SECRET (secreto compartido con la VM), PORT (lo pone Railway)
"""
import asyncio
import json
import os
import threading
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord import app_commands

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
BOSS_ID = int(os.environ.get("BOSS_ID", "1426737376822296667"))
DAHL_KEY = os.environ.get("DAHL_API_KEY", "")
DAHL_BASE = "https://inference.dahl.global/v1"
DAHL_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")
PORT = int(os.environ.get("PORT", "8080"))

# ---------------------------------------------------------------- estado vivo
ESTADO = {
    "actualizado": None,
    "texto": "(estado aún no recibido de la VM — se empuja cada 15 min)",
}
ACCIONES = []  # {id, tipo, destino, mensaje, estado: pendiente/aprobada/rechazada/ejecutada/fallida, resultado}
_ACCION_SEQ = 0
BRIEFINGS = []  # últimos informes enviados (para no repetir)
BOT_LOOP = None


def estado_texto():
    return ESTADO["texto"]


CTX = (
    "MenúYa CR: empresa que vende soluciones digitales de pago único a sodas y restaurantes "
    "pequeños de Costa Rica. Suite: menú QR ₡15k, menú+pedidos WhatsApp ₡25k, Google Maps ₡10k, "
    "WA Business ₡12k, web una página ₡20k, catálogo QR ₡15k, cliente frecuente QR ₡18k, "
    "reservaciones ₡15k, tarjetas regalo ₡12k, facturación electrónica ₡20k, reseñas automáticas ₡8k. "
    "Primeros 10 clientes: básico ₡10k / completo ₡20k. Cobro 50% adelanto / 50% entrega por SINPE móvil. "
    "META: ₡200,000 en 30 días (8-oct al 7-nov-2026). Español tico, voz 'nosotros', sin hype. "
    "NO inventas clientes, ventas ni números. Si no hay dato, dilo."
)

DEPTOS = {
    "PROSPECCION": CTX + " Eres la cazadora de clientes: propones negocios nuevos para contactar "
        "(sodas, cafeterías, pizzerías de Costa Rica; varía zonas) con cantón, por qué encaja y primer "
        "mensaje de WhatsApp corto, tico, 'nosotros', SIN precio. Marca con 'por verificar' lo que inventes.",
    "CIERRES": CTX + " Eres la cerradora: conviertes leads calientes en clientes que paguen el 50%. "
        "Mensajes cortos, urgencia honesta, el precio va AL FINAL, terminas con pregunta que invite a "
        "responder. Usas el ESTADO para saber quiénes son los leads calientes y qué se les dijo.",
    "CONTENIDO": CTX + " Eres la community manager de @menuya.cr (IG/FB). Creas posts que venden "
        "soluciones (más pedidos, menos espera). Copy corto + idea visual; la imagen muestra el producto.",
    "FINANZAS": CTX + " Eres la contadora: números exactos del ESTADO. Calculas faltante para ₡200k, "
        "días restantes al 7-nov-2026, meta diaria y clientes necesarios por ticket (₡10k/₡20k/₡25k).",
}
COORD = (CTX + " Eres la COORDINADORA general de MenúYa CR: lees el trabajo de las áreas, detectas lo flojo, "
    "priorizas y entregas resumen ejecutivo con sugerencias concretas. Directa, sin rodeos. "
    "NUNCA digas 'la orden no se ejecutó': tu trabajo es producir el entregable con lo que haya.")

PERSONAS = {
    "VENTAS": "Vendedora de MenúYa CR (voz plural 'nosotros', español tico amable). Conoces la suite de pago "
        "único: menú QR ₡15k, menú+pedidos WA ₡25k, Google Maps ₡10k, WA Business ₡12k, web una página ₡20k, "
        "catálogo QR ₡15k, cliente frecuente QR ₡18k, reservaciones ₡15k, tarjetas regalo ₡12k, facturación "
        "electrónica ₡20k, reseñas automáticas ₡8k. Primeros 10 clientes: básico ₡10k / completo ₡20k. "
        "Cobro 50% adelanto / 50% entrega por SINPE móvil. Redactas mensajes de WhatsApp para prospectos y "
        "seguimientos; el precio se da AL FINAL, cuando el prospecto esté enganchado. Nunca inventas "
        "clientes ni cierres.",
    "DISENO": "Diseñadora de MenúYa CR. Armas muestras de menús digitales con la identidad visual real de "
        "cada negocio (nunca genéricas). Referencia: demo en vivo https://menuya-demo.netlify.app "
        "(Soda La Esperanza). Propones estructura, textos y paleta por negocio. Cuando te pasan nombre + "
        "fotos/descripción del local, devuelves el concepto de muestra listo para construir. Español, tono "
        "profesional y cálido.",
    "SOPORTE": "Soporte de MenúYa CR. Respondes dudas de clientes sobre sus menús/pedidos con soluciones "
        "concretas. Conoces los productos y precios de la suite. Si algo se dañó, das pasos para arreglarlo. "
        "Escalas a Durling solo lo que no puedes resolver. Tono paciente, español claro, sin tecnicismos.",
}


def dahl_chat(system: str, user: str, max_tokens: int = 1500) -> str:
    payload = {
        "model": DAHL_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    last_err = None
    for intento in range(3):
        try:
            req = urllib.request.Request(
                DAHL_BASE + "/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {DAHL_KEY}"},
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last_err = e
            print(f"dahl intento {intento + 1} falló: {e} — reintentando", flush=True)
            import time
            time.sleep(5 * (intento + 1))
    raise RuntimeError(f"DAHL no respondió tras 3 intentos: {last_err}")


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.upper())
                   if unicodedata.category(c) != "Mn")


def ejecutar_orden(orden: str):
    """Devuelve (resultado_final, lista_de_acciones)."""
    hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
    est = estado_texto()
    desglose = dahl_chat(
        COORD + f"\n\nFECHA ACTUAL: {hoy}\nESTADO REAL DEL NEGOCIO:\n{est}",
        f"El jefe (Durling) dio esta ORDEN: '{orden}'. Desglósala en instrucciones concretas y cortas "
        "para los empleados que hagan falta de esta lista: PROSPECCION, CIERRES, CONTENIDO, FINANZAS. "
        "Usa el ESTADO REAL: si un lead ya fue contactado, no pidas contactarlo de nuevo; propone el "
        "siguiente paso real. Formato por empleado: 'PROSPECCION: <instrucciones>' o 'PROSPECCION: NADA'.",
        max_tokens=800,
    )
    partes = []
    matched_any = False
    for nombre, persona in DEPTOS.items():
        instr = ""
        for line in desglose.splitlines():
            head = line.split(":", 1)[0] if ":" in line else ""
            if _norm(nombre) in _norm(head):
                instr = line.split(":", 1)[1].strip()
                break
        if not instr or "NADA" in _norm(instr):
            continue
        matched_any = True
        parte = dahl_chat(
            persona + f"\n\nFECHA ACTUAL: {hoy}\nESTADO REAL DEL NEGOCIO:\n{est}",
            f"Instrucciones de la coordinadora: {instr}\n\nEjecútalas con el ESTADO REAL y entrega "
            "solo tu parte, completa y lista para usar. Concreta: nombres, números, mensajes listos.",
            max_tokens=1500)
        partes.append(f"### {nombre}\n{parte}")
    if not matched_any:
        # fallback: todos trabajan la orden directo
        for nombre, persona in DEPTOS.items():
            parte = dahl_chat(
                persona + f"\n\nFECHA ACTUAL: {hoy}\nESTADO REAL DEL NEGOCIO:\n{est}",
                f"Orden del jefe: '{orden}'. Si te compete, ejecuta tu parte concreta con el ESTADO REAL. "
                "Si no te compete, responde exactamente: NADA QUE HACER.",
                max_tokens=1200)
            if "NADA QUE HACER" not in _norm(parte):
                partes.append(f"### {nombre}\n{parte}")
    trabajo = "\n\n".join(partes) if partes else "(sin aportes de departamentos)"
    final = dahl_chat(
        COORD + f"\n\nFECHA ACTUAL: {hoy}\nESTADO REAL DEL NEGOCIO:\n{est}",
        f"Orden del jefe: '{orden}'.\n\nDesglose:\n{desglose}\n\nTrabajo de empleados:\n{trabajo}\n\n"
        "Entrega el RESULTADO FINAL: qué se hizo, el entregable concreto (mensajes listos, listas, "
        "números) y qué sigue. Si la orden requiere ACCIONES REALES (ej: mandar un WhatsApp a un lead), "
        "al final agrega una sección 'ACCIONES PROPUESTAS' con líneas exactas así:\n"
        "ACCION: whatsapp | <numero con código país, ej 50687045770> | <mensaje completo>\n"
        "Solo propone acciones útiles y concretas. Directa, sin rodeos.",
        max_tokens=2000,
    )
    acciones = parse_acciones(final)
    return final, acciones


def post_webhook(title: str, body: str):
    if not WEBHOOK:
        return
    text = f"🏢 **{title}**\n\n{body[:3500]}"
    payload = {"content": text, "username": "MenúYa HQ"}
    req = urllib.request.Request(WEBHOOK, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        print(f"webhook falló: {e}", flush=True)


# ------------------------------------------------------- puente HTTP con la VM
class BridgeHandler(BaseHTTPRequestHandler):
    def _auth(self):
        return self.headers.get("X-Bridge-Secret", "") == BRIDGE_SECRET and BRIDGE_SECRET

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._auth():
            self._json({"error": "no autorizado"}, 403)
            return
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/estado":
            ESTADO["texto"] = data.get("texto", "")
            ESTADO["actualizado"] = datetime.now().isoformat(timespec="minutes")
            print(f"puente: estado actualizado ({len(ESTADO['texto'])} chars)", flush=True)
            self._json({"ok": True})
        elif self.path == "/acciones/resultado":
            aid = data.get("id")
            for a in ACCIONES:
                if a["id"] == aid:
                    a["estado"] = "ejecutada" if data.get("ok") else "fallida"
                    a["resultado"] = data.get("resultado", "")
                    print(f"puente: acción {aid} -> {a['estado']}", flush=True)
                    break
            self._json({"ok": True})
        elif self.path == "/briefing":
            try:
                texto = generar_briefing()
            except Exception as e:
                print(f"briefing falló: {e}", flush=True)
                self._json({"ok": False, "error": str(e)[:200]})
                return
            if "NADA NUEVO" in texto.upper():
                print("briefing: nada nuevo, silencio", flush=True)
                self._json({"ok": True, "enviado": False})
                return
            acciones = parse_acciones(texto)
            if BOT_LOOP is None:
                print("briefing: bot aún no listo", flush=True)
                self._json({"ok": False, "error": "bot no listo"})
                return
            fut = asyncio.run_coroutine_threadsafe(enviar_briefing_dm(texto, acciones), BOT_LOOP)
            try:
                fut.result(timeout=120)
                self._json({"ok": True, "enviado": True, "acciones": len(acciones)})
            except Exception as e:
                print(f"briefing DM falló: {e}", flush=True)
                self._json({"ok": False, "error": str(e)[:200]})
        else:
            self._json({"error": "ruta desconocida"}, 404)

    def do_GET(self):
        if not self._auth():
            self._json({"error": "no autorizado"}, 403)
            return
        if self.path == "/acciones":
            pend = [a for a in ACCIONES if a["estado"] == "aprobada"]
            for a in pend:
                a["estado"] = "reclamada"
            self._json({"acciones": [
                {"id": a["id"], "tipo": a["tipo"], "destino": a["destino"], "mensaje": a["mensaje"]}
                for a in pend]})
        elif self.path == "/salud":
            self._json({"ok": True, "estado_actualizado": ESTADO["actualizado"],
                        "acciones": len(ACCIONES)})
        else:
            self._json({"error": "ruta desconocida"}, 404)

    def log_message(self, *args):
        pass


def start_bridge():
    srv = HTTPServer(("0.0.0.0", PORT), BridgeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"puente HTTP en puerto {PORT}", flush=True)


# ------------------------------------------------------------------- discord
class HQBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        for g in self.guilds:
            try:
                await self.tree.sync(guild=g)
            except Exception:
                pass
        print("HQ: comandos sincronizados", flush=True)


bot = HQBot()


@bot.event
async def on_guild_join(guild):
    try:
        await bot.tree.sync(guild=guild)
    except Exception:
        pass
    print(f"HQ: unido a {guild.name}", flush=True)


@bot.event
async def on_ready():
    global BOT_LOOP
    BOT_LOOP = asyncio.get_running_loop()
    print(f"HQ: conectado como {bot.user}", flush=True)


def is_boss(interaction: discord.Interaction) -> bool:
    return interaction.user.id == BOSS_ID


async def deny(interaction: discord.Interaction):
    await interaction.response.send_message("⛔ Solo el jefe puede usar este comando.",
                                            ephemeral=True)


class AccionView(discord.ui.View):
    def __init__(self, accion):
        super().__init__(timeout=600)
        self.accion = accion

    @discord.ui.button(label="✅ Enviar", style=discord.ButtonStyle.green)
    async def enviar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_boss(interaction):
            await interaction.response.send_message("⛔ Solo el jefe aprueba.", ephemeral=True)
            return
        self.accion["estado"] = "aprobada"
        button.disabled = True
        self.children[1].disabled = True
        await interaction.response.edit_message(
            content=f"✅ Aprobado — se enviará por WhatsApp al {self.accion['destino']}.",
            view=self)
        print(f"acción {self.accion['id']} aprobada", flush=True)

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.red)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_boss(interaction):
            await interaction.response.send_message("⛔ Solo el jefe aprueba.", ephemeral=True)
            return
        self.accion["estado"] = "rechazada"
        button.disabled = True
        self.children[0].disabled = True
        await interaction.response.edit_message(content="❌ Acción cancelada.", view=self)


def queue_accion(tipo, destino, mensaje):
    global _ACCION_SEQ
    _ACCION_SEQ += 1
    a = {"id": _ACCION_SEQ, "tipo": tipo, "destino": destino, "mensaje": mensaje,
         "estado": "pendiente", "resultado": ""}
    ACCIONES.append(a)
    return a


def parse_acciones(texto):
    accs = []
    for line in texto.splitlines():
        s = line.strip()
        if s.upper().startswith("ACCION:"):
            try:
                _, resto = s.split(":", 1)
                _, numero, mensaje = [x.strip() for x in resto.split("|", 2)]
                numero = "".join(c for c in numero if c.isdigit())
                if numero and mensaje:
                    accs.append({"tipo": "whatsapp", "destino": numero, "mensaje": mensaje})
            except ValueError:
                continue
    return accs


def generar_briefing():
    """La coordinadora decide si hay algo que valga la pena contarle al jefe."""
    hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
    est = estado_texto()
    hist = "\n---\n".join(BRIEFINGS[-3:]) or "(primer informe)"
    texto = dahl_chat(
        COORD + f"\n\nFECHA ACTUAL: {hoy}\nESTADO REAL DEL NEGOCIO:\n{est}",
        "Sos la coordinadora y le vas a escribir un informe CORTO al jefe (Durling) por DM. "
        "Máximo 1200 caracteres. Tono directo, tico, sin rodeos.\n"
        "Contenido: 1) qué cambió o qué necesita decisión YA, 2) una sugerencia concreta para avanzar "
        "a la meta de ₡200,000, 3) si proponés acciones reales (ej: mandar WhatsApp a un lead), "
        "terminalas con líneas exactas así:\n"
        "ACCION: whatsapp | <numero con código país> | <mensaje completo>\n"
        "REGLA DE ORO: si desde el último informe no hay nada nuevo ni accionable, respondé "
        "exactamente: NADA NUEVO (sin nada más).\n\n"
        f"ÚLTIMOS INFORMES (no repitas):\n{hist}",
        max_tokens=1200)
    return texto


async def enviar_briefing_dm(texto, acciones):
    user = await bot.fetch_user(BOSS_ID)
    limpio = texto
    idx = limpio.upper().find("ACCION:")
    if idx >= 0:
        # cortar desde la primera línea ACCION
        lineas = limpio.splitlines()
        limpio = "\n".join(l for l in lineas if not l.strip().upper().startswith("ACCION:")).rstrip()
    BRIEFINGS.append(limpio[:800])
    view = BriefingView(acciones) if acciones else None
    msg = f"📋 **Informe de la coordinadora**\n\n{limpio[:1800]}"
    if acciones:
        msg += f"\n\n👆 Hay {len(acciones)} acción(es) propuesta(s) abajo."
    await user.send(msg, view=view)
    # si no hay botones, igual mandar las acciones como propuestas aprobables
    for ac in acciones:
        a = queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
        await user.send(
            f"📲 **Acción propuesta** — WhatsApp al `+{a['destino']}`:\n> {a['mensaje'][:500]}",
            view=AccionView(a))
    print(f"briefing enviado al jefe ({len(acciones)} acciones)", flush=True)


class BriefingView(discord.ui.View):
    def __init__(self, acciones):
        super().__init__(timeout=86400)
        self.acciones = acciones

    @discord.ui.button(label="✅ Ejecutar plan", style=discord.ButtonStyle.green)
    async def ejecutar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_boss(interaction):
            await interaction.response.send_message("⛔ Solo el jefe.", ephemeral=True)
            return
        n = 0
        for ac in self.acciones:
            a = queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
            a["estado"] = "aprobada"
            n += 1
        button.disabled = True
        self.children[1].disabled = True
        await interaction.response.edit_message(
            content=f"✅ Plan en marcha — {n} acción(es) aprobadas, se ejecutan solas.", view=self)

    @discord.ui.button(label="✏️ Ordenar algo", style=discord.ButtonStyle.blurple)
    async def ordenar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_boss(interaction):
            await interaction.response.send_message("⛔ Solo el jefe.", ephemeral=True)
            return
        await interaction.response.send_modal(OrdenModal())


class OrdenModal(discord.ui.Modal, title="Orden para la empresa"):
    orden = discord.ui.TextInput(label="¿Qué ordenás?", style=discord.TextStyle.paragraph,
                                 max_length=500, placeholder="Ej: mandale un recordatorio a Delicias del Puerto")

    async def on_submit(self, interaction: discord.Interaction):
        if not is_boss(interaction):
            await interaction.response.send_message("⛔ Solo el jefe.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            resultado, acciones = await asyncio.to_thread(ejecutar_orden, str(self.orden.value))
            post_webhook("📋 Orden del jefe (desde informe)",
                         f"_Orden: {self.orden.value}_\n\n{resultado}")
            limpio = resultado
            idx = limpio.upper().find("ACCIONES PROPUESTAS")
            if idx >= 0:
                limpio = limpio[:idx].rstrip()
            await interaction.followup.send(f"✅ **Orden ejecutada.**\n\n{limpio[:1700]}")
            for ac in acciones:
                a = queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
                await interaction.followup.send(
                    f"📲 **Acción propuesta** — WhatsApp al `+{a['destino']}`:\n> {a['mensaje'][:500]}",
                    view=AccionView(a))
        except Exception as e:
            await interaction.followup.send(f"😕 Falló la orden: {str(e)[:300]}")


@bot.tree.command(name="jefe", description="Dar una orden a la coordinadora (la reparte al equipo)")
@app_commands.describe(orden="La orden para la empresa")
async def jefe(interaction: discord.Interaction, orden: str):
    if not is_boss(interaction):
        await deny(interaction)
        return
    await interaction.response.defer()
    await interaction.followup.send(
        "Recibido, jefe 👔 La coordinadora reparte la orden con el estado real del negocio…")
    try:
        resultado, acciones = await asyncio.to_thread(ejecutar_orden, orden)
        post_webhook("📋 Orden del jefe ejecutada", f"_Orden: {orden}_\n\n{resultado}")
        # quitar la sección ACCIONES del texto mostrado (van por botones)
        limpio = resultado
        idx = limpio.upper().find("ACCIONES PROPUESTAS")
        if idx >= 0:
            limpio = limpio[:idx].rstrip()
        await interaction.followup.send(f"✅ **Orden ejecutada.**\n\n{limpio[:1700]}")
        for ac in acciones:
            a = queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
            preview = a["mensaje"][:500]
            await interaction.followup.send(
                f"📲 **Acción propuesta** — WhatsApp al `+{a['destino']}`:\n> {preview}",
                view=AccionView(a))
    except Exception as e:
        await interaction.followup.send(f"😕 Falló la orden: {str(e)[:300]}")


def _dept_cmd(name: str, display: str, desc: str):
    @bot.tree.command(name=name, description=desc)
    @app_commands.describe(mensaje="Mensaje para el departamento")
    async def _cmd(interaction: discord.Interaction, mensaje: str):
        if not is_boss(interaction):
            await deny(interaction)
            return
        await interaction.response.defer()
        try:
            resp = await asyncio.to_thread(
                dahl_chat,
                PERSONAS[display] + f"\n\nESTADO REAL DEL NEGOCIO:\n{estado_texto()}",
                mensaje)
            await interaction.followup.send(f"**{display} dice:**\n{resp[:1800]}")
        except Exception as e:
            await interaction.followup.send(f"😕 {display} no respondió: {str(e)[:200]}")
    return _cmd


_dept_cmd("ventas", "VENTAS", "Hablar directo con VENTAS")
_dept_cmd("diseno", "DISENO", "Hablar directo con DISEÑO")
_dept_cmd("soporte", "SOPORTE", "Hablar directo con SOPORTE")


@bot.tree.command(name="ayuda", description="Ver los comandos del bot jefe")
async def ayuda(interaction: discord.Interaction):
    if not is_boss(interaction):
        await deny(interaction)
        return
    await interaction.response.send_message(
        "👔 **MenúYa HQ — comandos del jefe**\n"
        "• `/jefe <orden>` — la coordinadora lo desglosa con el estado real del negocio y manda a prospección/cierres/contenido/finanzas. Si hacen falta acciones reales (WhatsApp), te las propone y las aprobas con botones.\n"
        "• `/ventas`, `/diseno`, `/soporte <mensaje>` — directo con cada departamento (conocen el estado real).\n"
        f"📡 Estado del negocio actualizado: {ESTADO['actualizado'] or 'aún no llega de la VM'}",
        ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Falta DISCORD_BOT_TOKEN")
    start_bridge()
    bot.run(TOKEN)
