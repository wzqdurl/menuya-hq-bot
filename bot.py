#!/usr/bin/env python3
"""MenúYa HQ en Railway — bot de Discord para dirigir la empresa 24/7.

Comandos (solo el jefe):
  /jefe <orden>      -> la coordinadora desglosa la orden a los 4 departamentos y sintetiza
  /ventas <mensaje>  -> directo con VENTAS (persona DAHL)
  /diseno <mensaje>  -> directo con DISEÑO (persona DAHL)
  /soporte <mensaje> -> directo con SOPORTE (persona DAHL)
  /ayuda             -> lista de comandos

Env vars: DISCORD_BOT_TOKEN (requerido), BOSS_ID, DAHL_API_KEY, DISCORD_WEBHOOK_URL
"""
import asyncio
import json
import os
import urllib.request

import discord
from discord import app_commands

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
BOSS_ID = int(os.environ.get("BOSS_ID", "1426737376822296667"))
DAHL_KEY = os.environ.get("DAHL_API_KEY", "")
DAHL_BASE = "https://inference.dahl.global/v1"
DAHL_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

CTX = (
    "MenúYa CR: empresa que vende soluciones digitales de pago único a sodas y restaurantes "
    "pequeños de Costa Rica. Suite: menú QR ₡15k, menú+pedidos WhatsApp ₡25k, Google Maps ₡10k, "
    "WA Business ₡12k, web una página ₡20k, catálogo QR ₡15k, cliente frecuente QR ₡18k, "
    "reservaciones ₡15k, tarjetas regalo ₡12k, facturación electrónica ₡20k, reseñas automáticas ₡8k. "
    "Primeros 10 clientes: básico ₡10k / completo ₡20k. Cobro 50% adelanto / 50% entrega por SINPE móvil. "
    "META: ₡200,000 en 30 días (8-oct al 7-nov-2026). Español tico, voz 'nosotros', sin hype."
)

DEPTOS = {
    "PROSPECCION": CTX + " Eres la cazadora de clientes: propones negocios nuevos para contactar "
        "(sodas, cafeterías, pizzerías de Costa Rica; varía zonas) con cantón, por qué encaja y primer "
        "mensaje de WhatsApp corto, tico, 'nosotros', SIN precio.",
    "CIERRES": CTX + " Eres la cerradora: conviertes leads calientes en clientes que paguen el 50%. "
        "Mensajes cortos, urgencia honesta, el precio va AL FINAL, terminas con pregunta que invite a "
        "responder. Leads: Las Delicias del Puerto (pidió propuesta, no responde), "
        "Cafetería Más Q'Rollos Heredia (dijo 'sí nos interesa', dejó en visto).",
    "CONTENIDO": CTX + " Eres la community manager de @menuya.cr (IG/FB). Creas posts que venden "
        "soluciones (más pedidos, menos espera). Copy corto + idea visual; la imagen muestra el producto.",
    "FINANZAS": CTX + " Eres la contadora: números exactos. Ingresos registrados: ₡0 salvo dato nuevo. "
        "Calculas faltante para ₡200k, días restantes al 7-nov-2026, meta diaria y clientes necesarios "
        "por ticket (₡10k/₡20k/₡25k).",
}
COORD = (CTX + " Eres la COORDINADORA general de MenúYa CR: lees el trabajo de las áreas, detectas lo flojo, "
    "priorizas y entregas resumen ejecutivo con sugerencias concretas. Directa, sin rodeos.")

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


def ejecutar_orden(orden: str) -> str:
    """Coordinadora desglosa -> departamentos ejecutan -> coordinadora sintetiza."""
    desglose = dahl_chat(
        COORD,
        f"El jefe (Durling) dio esta ORDEN: '{orden}'. Desglósala en instrucciones concretas y cortas "
        "para los empleados que hagan falta de esta lista: PROSPECCION, CIERRES, CONTENIDO, FINANZAS. "
        "Formato por empleado: 'PROSPECCION: <instrucciones>' o 'PROSPECCION: NADA' si no hace falta.",
        max_tokens=800,
    )
    partes = []
    for nombre, persona in DEPTOS.items():
        instr = ""
        for line in desglose.splitlines():
            if line.strip().upper().startswith(nombre):
                instr = line.split(":", 1)[1].strip() if ":" in line else ""
                break
        if not instr or "NADA" in instr.upper():
            continue
        parte = dahl_chat(persona, f"Instrucciones de la coordinadora: {instr}\n\nEjecútalas y entrega "
                          "solo tu parte, completa y lista para usar.", max_tokens=1500)
        partes.append(f"### {nombre}\n{parte}")
    trabajo = "\n\n".join(partes) if partes else "(Ningún departamento tenía trabajo para esta orden.)"
    final = dahl_chat(
        COORD,
        f"Orden del jefe: '{orden}'.\n\nDesglose que diste:\n{desglose}\n\nLo que ejecutó cada empleado:\n"
        f"{trabajo}\n\nEntrega el RESULTADO FINAL: qué se hizo, el entregable concreto y qué sigue. "
        "Directa, sin rodeos.",
        max_tokens=2000,
    )
    return final


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
    print(f"HQ: conectado como {bot.user}", flush=True)


def is_boss(interaction: discord.Interaction) -> bool:
    return interaction.user.id == BOSS_ID


async def deny(interaction: discord.Interaction):
    await interaction.response.send_message("⛔ Solo el jefe puede usar este comando.",
                                            ephemeral=True)


@bot.tree.command(name="jefe", description="Dar una orden a la coordinadora (la reparte al equipo)")
@app_commands.describe(orden="La orden para la empresa")
async def jefe(interaction: discord.Interaction, orden: str):
    if not is_boss(interaction):
        await deny(interaction)
        return
    await interaction.response.defer()
    await interaction.followup.send(
        "Recibido, jefe 👔 La coordinadora reparte la orden… te aviso aquí mismo cuando esté.")
    try:
        resultado = await asyncio.to_thread(ejecutar_orden, orden)
        post_webhook("📋 Orden del jefe ejecutada", f"_Orden: {orden}_\n\n{resultado}")
        await interaction.followup.send(f"✅ **Orden ejecutada.**\n\n{resultado[:1800]}")
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
            resp = await asyncio.to_thread(dahl_chat, PERSONAS[display], mensaje)
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
        "• `/jefe <orden>` — la coordinadora lo desglosa y manda a prospección/cierres/contenido/finanzas\n"
        "• `/ventas <mensaje>` — directo con VENTAS\n"
        "• `/diseno <mensaje>` — directo con DISEÑO\n"
        "• `/soporte <mensaje>` — directo con SOPORTE\n"
        "Los 3 turnos diarios siguen reportando solos en tu canal.",
        ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Falta DISCORD_BOT_TOKEN")
    bot.run(TOKEN)
