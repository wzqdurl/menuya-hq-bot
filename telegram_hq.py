"""Centro de mando de MenúYa HQ por Telegram.
Comandos del jefe: /start /jefe /ventas /diseno /soporte /ayuda /estado
Aprobación de acciones con botones inline ✅/❌ (misma cola que Discord).
Solo responde al chat del jefe (TELEGRAM_BOSS_CHAT_ID).
"""
import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import bot as hq  # noqa: F401  (lógica central: ejecutar_orden, dahl_chat, cola de acciones...)

log = logging.getLogger("menuya-tg")

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOSS_CHAT = int(os.environ.get("TELEGRAM_BOSS_CHAT_ID", "0"))

_app = None


def _es_jefe(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and BOSS_CHAT and chat.id == BOSS_CHAT


async def _negar(update: Update):
    await update.message.reply_text("⛔ Solo el jefe usa este bot.")


def _trocear(texto: str, limite: int = 4000):
    partes, actual = [], ""
    for linea in texto.splitlines(keepends=True):
        if len(actual) + len(linea) > limite:
            partes.append(actual)
            actual = ""
        actual += linea
    if actual.strip():
        partes.append(actual)
    return partes or ["(vacío)"]


async def tg_send(texto: str, reply_markup=None, chat_id: int = 0):
    """Envío proactivo al jefe (lo usan los endpoints /briefing, /standup, etc.)."""
    global _app
    if _app is None or not BOSS_CHAT:
        log.warning("tg_send sin app o sin BOSS_CHAT")
        return False
    dest = chat_id or BOSS_CHAT
    for parte in _trocear(texto):
        await _app.bot.send_message(chat_id=dest, text=parte,
                                    reply_markup=reply_markup,
                                    parse_mode="HTML", disable_web_page_preview=True)
        reply_markup = None  # botones solo en el primer trozo
    return True


def _botones_accion(accion_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Enviar", callback_data=f"ap:{accion_id}"),
        InlineKeyboardButton("❌ Cancelar", callback_data=f"rj:{accion_id}"),
    ]])


async def _mandar_acciones(update_or_query, acciones):
    """Cola las acciones y las manda con botones ✅/❌. update_or_query: message-like."""
    send = update_or_query.message.reply_text if hasattr(update_or_query, "message") and update_or_query.message else None
    for ac in acciones:
        a = hq.queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
        txt = (f"📲 <b>Acción propuesta</b> — WhatsApp al +{a['destino']}:\n"
               f"<i>{a['mensaje'][:500]}</i>")
        if send:
            await update_or_query.message.reply_text(txt, reply_markup=_botones_accion(a["id"]),
                                                    parse_mode="HTML")
        else:
            await tg_send(txt, reply_markup=_botones_accion(a["id"]))


# ---------------- comandos ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _es_jefe(update):
        await _negar(update)
        return
    await update.message.reply_text(
        "👔 <b>MenúYa HQ — centro de mando</b>\n\n"
        "• /jefe &lt;orden&gt; — la coordinadora la desglosa y el equipo la ejecuta\n"
        "• /ventas, /diseno, /soporte &lt;mensaje&gt; — directo con el departamento\n"
        "• /estado — estado del negocio ahora mismo\n"
        "• /ayuda — ver esto de nuevo\n\n"
        "Todo lo que necesite tu aprobación llega con botones ✅/❌.",
        parse_mode="HTML")


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _es_jefe(update):
        await _negar(update)
        return
    try:
        est = await asyncio.to_thread(hq.estado_texto)
        await update.message.reply_text(f"📡 <b>Estado del negocio</b>\n\n{est[:3500]}",
                                        parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"😕 No pude leer el estado: {e}")


async def cmd_jefe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _es_jefe(update):
        await _negar(update)
        return
    orden = " ".join(context.args).strip()
    if not orden:
        await update.message.reply_text("Escribí la orden: /jefe <i>tu orden</i>", parse_mode="HTML")
        return
    aviso = await update.message.reply_text("Recibido, jefe 👔 La coordinadora reparte la orden…")
    try:
        resultado, acciones = await asyncio.to_thread(hq.ejecutar_orden, orden)
        limpio = resultado
        idx = limpio.upper().find("ACCIONES PROPUESTAS")
        if idx >= 0:
            limpio = limpio[:idx].rstrip()
        # Telegram no usa markdown de Discord: limpiar ** y ##
        for trozo in _trocear(f"✅ <b>Orden ejecutada.</b>\n\n{limpio}"):
            await update.message.reply_text(trozo, parse_mode="HTML")
        if acciones:
            await _mandar_acciones(update, acciones)
        await aviso.delete()
    except Exception as e:
        await update.message.reply_text(f"😕 Falló la orden: {str(e)[:300]}")


def _cmd_depto(nombre: str, display: str):
    async def _cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _es_jefe(update):
            await _negar(update)
            return
        mensaje = " ".join(context.args).strip()
        if not mensaje:
            await update.message.reply_text(f"Escribí el mensaje: /{nombre} <i>tu mensaje</i>",
                                            parse_mode="HTML")
            return
        try:
            resp = await asyncio.to_thread(
                hq.dahl_chat,
                hq.PERSONAS[display] + f"\n\nESTADO REAL DEL NEGOCIO:\n{hq.estado_texto()}",
                mensaje)
            for trozo in _trocear(f"<b>{display} dice:</b>\n{resp}"):
                await update.message.reply_text(trozo, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"😕 {display} no respondió: {str(e)[:200]}")
    _cmd.__name__ = f"cmd_{nombre}"
    return _cmd


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _es_jefe(update):
        await q.answer("⛔ Solo el jefe aprueba.", show_alert=True)
        return
    await q.answer()
    try:
        accion, sid = q.data.split(":", 1)
        aid = int(sid)
    except ValueError:
        return
    a = next((x for x in hq.ACCIONES if x["id"] == aid), None)
    if not a:
        await q.edit_message_text("Esa acción ya no existe.")
        return
    if accion == "ap":
        a["estado"] = "aprobada"
        hq.guardar_acciones()
        await q.edit_message_text(
            f"✅ Aprobado — se enviará por WhatsApp al +{a['destino']}.", parse_mode="HTML")
        log.info("acción %s aprobada por Telegram", aid)
    else:
        a["estado"] = "rechazada"
        hq.guardar_acciones()
        await q.edit_message_text("❌ Acción cancelada.")
        log.info("acción %s rechazada por Telegram", aid)


# ---------------- envío proactivo (lo llaman los endpoints) ----------------

async def enviar_briefing_tg(texto: str, acciones):
    limpio = "\n".join(l for l in texto.splitlines()
                       if not l.strip().upper().startswith("ACCION:")).rstrip()
    await tg_send(f"📋 <b>Informe de la coordinadora</b>\n\n{limpio[:3500]}")
    if acciones:
        await tg_send(f"👆 {len(acciones)} acción(es) propuesta(s) abajo.")
        for ac in acciones:
            a = hq.queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
            await tg_send(f"📲 <b>Acción propuesta</b> — WhatsApp al +{a['destino']}:\n"
                          f"<i>{a['mensaje'][:500]}</i>",
                          reply_markup=_botones_accion(a["id"]))
    return True


async def enviar_standup_tg(nombre: str, display: str, texto: str):
    if "NADA NUEVO" in hq._norm(texto):
        return False
    acciones = hq.parse_acciones(texto)
    limpio = "\n".join(l for l in texto.splitlines()
                       if not l.strip().upper().startswith("ACCION:")).rstrip()
    hq.BRIEFINGS.append(f"[{display}] " + limpio[:400])
    msg = f"👷 <b>{display} reporta</b>\n\n{limpio[:3000]}"
    if acciones:
        msg += f"\n\n👆 {len(acciones)} acción(es) propuesta(s)."
    await tg_send(msg)
    for ac in acciones:
        a = hq.queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
        await tg_send(f"📲 <b>Acción propuesta</b> — WhatsApp al +{a['destino']}:\n"
                      f"<i>{a['mensaje'][:500]}</i>",
                      reply_markup=_botones_accion(a["id"]))
    return True


async def enviar_orquestacion_tg(resultados):
    if not resultados:
        return False
    lineas, todas = [], []
    for dept, tarea, resultado, acciones in resultados:
        display = hq.DEPTOS[dept]["display"]
        lineas.append(f"🎯 <b>Ordené a {display}</b>: {tarea[:120]}")
        limpio = "\n".join(l for l in resultado.splitlines()
                           if not l.strip().upper().startswith("ACCION:")).rstrip()
        lineas.append(limpio[:900])
        todas.extend(acciones)
        lineas.append("")
    msg = "🤖 <b>Gerente autónomo — órdenes ejecutadas</b>\n\n" + "\n".join(lineas)
    if todas:
        msg += f"\n👆 {len(todas)} acción(es) propuesta(s) abajo."
    await tg_send(msg[:3800])
    for ac in todas:
        a = hq.queue_accion(ac["tipo"], ac["destino"], ac["mensaje"])
        await tg_send(f"📲 <b>Acción propuesta</b> — WhatsApp al +{a['destino']}:\n"
                      f"<i>{a['mensaje'][:500]}</i>",
                      reply_markup=_botones_accion(a["id"]))
    return True


async def enviar_expansion_tg(texto: str):
    if "PLANTILLA COMPLETA" in hq._norm(texto):
        return False
    await tg_send(f"🌱 <b>Revisión de expansión</b>\n\n{texto[:3500]}")
    return True


async def enviar_panel_tg(texto: str):
    await tg_send(f"📊 <b>Panel diario</b>\n\n{texto[:3500]}")
    return True


def build_app():
    global _app
    if not TG_TOKEN:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN")
    if not BOSS_CHAT:
        raise SystemExit("Falta TELEGRAM_BOSS_CHAT_ID")
    _app = Application.builder().token(TG_TOKEN).build()
    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    _app.add_handler(CommandHandler("estado", cmd_estado))
    _app.add_handler(CommandHandler("jefe", cmd_jefe))
    _app.add_handler(CommandHandler("ventas", _cmd_depto("ventas", "VENTAS")))
    _app.add_handler(CommandHandler("diseno", _cmd_depto("diseno", "DISENO")))
    _app.add_handler(CommandHandler("soporte", _cmd_depto("soporte", "SOPORTE")))
    _app.add_handler(CallbackQueryHandler(on_callback))
    return _app
