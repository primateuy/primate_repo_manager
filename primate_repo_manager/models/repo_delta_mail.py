# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E2.3 · el correo del lunes — página 6c del entregable.

PARA QUIÉN ESTÁ ESCRITO. «Para gerencia, se lee en el teléfono», dice el mockup. Eso
manda todo lo demás: los tres números arriba con su movimiento, lo nuevo por gravedad, el
plan que espera una firma, y nada más. La lista completa de hallazgos vive en la
aplicación; un correo que la traiga entera se deja de leer al tercer lunes y con él se
pierden los tres que importaban.

LOS ESTILOS VAN EN LÍNEA, Y NO ES DESPROLIJIDAD. Los clientes de correo no cargan hojas de
estilo externas y muchos descartan hasta el `<style>` del documento. La única forma de que
el lunes se vea como el producto es escribir el color en cada elemento.

Eso deja los tokens **duplicados**: acá y en `tokens.scss`. Como duplicar el sistema de
diseño es exactamente lo que este proyecto no hace, hay un test que lee el `.scss` y exige
que los valores de acá sean los mismos. El día que el diseño cambie un rojo, el test se
pone en rojo — que es lo que debe pasar.

CUANDO LA AUDITORÍA FALLA EL CORREO SE MANDA IGUAL, con la causa. Es la honestidad de
pantalla aplicada al silencio: no mandar nada dejaría creer que no hay novedades, y la
semana que la auditoría no corre es justamente la semana en la que nadie está mirando.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Los tokens del sistema, en su versión para correo. Ver el docstring: el test
# `test_los_tokens_del_correo_son_LOS_MISMOS_del_sistema` los ata a `tokens.scss`.
T = {
	"ink": "#14181F",
	"ink_3": "#8A94A6",
	"border": "#DDE1E7",
	"bg": "#F4F5F7",
	"surface": "#FFFFFF",
	"critical": "#A1201F",
	"high": "#C2410C",
	"medium": "#B7791F",
	"info": "#4A6079",
	"done": "#1F7A4D",
	"error": "#A1201F",
	"accent": "#2F4A6D",
}

COLOR_DE_SEVERIDAD = {
	"critical": T["critical"], "high": T["high"],
	"medium": T["medium"], "low": T["info"], "info": T["info"],
}

FUENTE = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, "
		  "sans-serif")
MONO = "'IBM Plex Mono', SFMono-Regular, Menlo, Consolas, monospace"


class RepoDeltaMail(models.AbstractModel):
	_name = "repo.delta.mail"
	_description = "El correo del delta semanal"

	# ------------------------------------------------------------------
	# Piezas
	# ------------------------------------------------------------------

	@api.model
	def _caja(self, contenido, extra=""):
		return (
			'<div style="background:%s;border:1px solid %s;border-radius:6px;'
			'padding:16px;margin:0 0 12px 0;%s">%s</div>'
			% (T["surface"], T["border"], extra, contenido))

	@api.model
	def _numeros(self, delta_panel):
		"""Los tres números con su movimiento.

		EL COLOR JUZGA EL MOVIMIENTO, NO LA DIRECCIÓN. Más ramas protegidas es mejor; más
		hallazgos abiertos es peor. Es la misma decisión que el panel, y por eso el
		sentido se pregunta acá igual que allá y no se reescribe.
		"""
		celdas = []
		for numero in delta_panel:
			valor = numero.get("valor")
			texto = ("—" if valor is None
					 else "%s%s" % (valor, numero.get("unidad") or ""))
			mov = ""
			if numero.get("delta"):
				mejor = self._es_mejor(numero)
				color = T["done"] if mejor else T["error"]
				flecha = "▲" if numero["delta"] > 0 else "▼"
				unidad = " pts" if numero.get("unidad") == "%" else ""
				mov = ('<div style="color:%s;font-size:12px;font-family:%s">%s %s%s</div>'
					   % (color, MONO, flecha, abs(numero["delta"]), unidad))
			celdas.append(
				'<td style="padding:8px 12px;vertical-align:top">'
				'<div style="color:%s;font-size:12px">%s</div>'
				'<div style="color:%s;font-size:22px;font-weight:600">%s</div>%s</td>'
				% (T["ink_3"], numero.get("titulo", ""), T["ink"], texto, mov))
		return ('<table role="presentation" cellpadding="0" cellspacing="0" '
				'style="width:100%%"><tr>%s</tr></table>' % "".join(celdas))

	@api.model
	def _es_mejor(self, numero):
		"""Más protegidas es mejor; más hallazgos abiertos es peor."""
		mas_es_mejor = numero.get("clave") != "hallazgos"
		return (numero["delta"] > 0) == mas_es_mejor

	@api.model
	def _lo_nuevo(self, filas):
		if not filas:
			return ('<div style="color:%s">No apareció nada nuevo esta semana.</div>'
					% T["ink_3"])
		orden = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
		lineas = []
		for fila in sorted(filas, key=lambda f: orden.get(f["severidad"], 9)):
			color = COLOR_DE_SEVERIDAD.get(fila["severidad"], T["info"])
			nota = ('<div style="color:%s;font-size:12px">%s</div>' % (T["ink_3"], fila["nota"])
					if fila.get("nota") else "")
			lineas.append(
				'<div style="padding:8px 0;border-top:1px solid %s">'
				'<span style="background:%s;color:#FFFFFF;font-size:11px;'
				'padding:2px 6px;border-radius:4px;text-transform:uppercase">%s</span> '
				'<span style="font-family:%s;font-size:12px;color:%s">%s</span> '
				'<span style="color:%s">%s</span>%s</div>'
				% (T["border"], color, fila["severidad_etiqueta"], MONO, T["ink_3"],
				   fila["repositorio"], T["ink"], fila["titulo"], nota))
		return "".join(lineas)

	@api.model
	def _sin_leer(self, corrida):
		"""LA FRASE QUE HACE HONESTO AL RESTO DEL CORREO.

		Sin ella, los tres números de arriba se leen como si hablaran de toda la cuenta.
		Hablan de lo que se pudo mirar, y hay que decir de qué no se está hablando.

		SALE DE LAS FILAS DE LA CORRIDA Y NO DEL DELTA, y la diferencia importa. El
		bloque «sin confirmar» de la pantalla habla de HALLAZGOS que no se pueden dar por
		resueltos, así que sólo lista repositorios que ya tenían alguno. Esta frase habla
		de los NÚMEROS: cualquier repositorio que no se pudo mirar queda fuera de ellos,
		haya tenido hallazgos antes o no.

		Lo encontró el ensayo E2.4: una corrida terminó con un repositorio ilegible y el
		correo salió sin la caja punteada, porque ese repositorio era nuevo y no tenía
		hallazgos anteriores. Los tres números de arriba ya no lo incluían y el correo no
		lo decía.
		"""
		lineas = corrida.line_ids.filtered(lambda l: l.state != "done")
		if not lineas:
			return ""
		nombres = ", ".join(
			'<span style="font-family:%s">%s</span> (%s)' % (
				MONO, linea.repository_id.full_name,
				(linea.error or _("no se llegó a leer")).splitlines()[0][:90])
			for linea in lineas)
		return self._caja(
			'<div style="color:%s;font-size:12px">'
			'<b>Sin leer:</b> %s.<br/><b>Este correo no dice nada sobre ellos.</b>'
			'</div>' % (T["ink_3"], nombres),
			extra="border-style:dashed")

	@api.model
	def _plan_pendiente(self, backend):
		"""El plan que espera una firma. Es lo único accionable del correo."""
		plan = self.env["repo.write.plan"].search([
			("backend_id", "=", backend.id), ("state", "=", "draft"),
			("operation_ids", "!=", False)], order="id desc", limit=1)
		if not plan:
			return ""
		irreversibles = len(plan.operation_ids.filtered("is_irreversible"))
		reversibles = len(plan.operation_ids) - irreversibles
		detalle = _("%(n)s operación(es) en %(r)s repositorio(s).") % {
			"n": len(plan.operation_ids),
			"r": len(set(plan.operation_ids.mapped("repository_id.id")))}
		if irreversibles:
			detalle += " " + _("%(rev)s se pueden deshacer; %(irr)s no.") % {
				"rev": reversibles, "irr": irreversibles}
		return self._caja(
			'<div style="font-weight:600;color:%s">%s</div>'
			'<div style="color:%s;font-size:13px">%s %s</div>'
			% (T["ink"], _("%s espera tu aprobación") % plan.display_name,
			   T["ink"], detalle, _("Nadie lo aplicó todavía.")))

	# ------------------------------------------------------------------
	# El correo entero
	# ------------------------------------------------------------------

	@api.model
	def asunto(self, corrida):
		if corrida.state == "error":
			return _("Repositorios: la auditoría del lunes no pudo terminar")
		criticos = len(corrida.finding_ids.filtered(lambda f: f.severity == "critical"))
		plan = self.env["repo.write.plan"].search_count([
			("backend_id", "=", corrida.backend_id.id), ("state", "=", "draft")])
		partes = []
		if criticos:
			partes.append(_("%s hallazgo(s) crítico(s)") % criticos)
		if plan:
			partes.append(_("un plan esperando"))
		if not partes:
			partes.append(_("sin novedades críticas"))
		return _("Repositorios: %s") % " y ".join(partes)

	@api.model
	def cuerpo(self, corrida):
		"""El HTML del correo, con todo el estilo en línea."""
		Delta = self.env["repo.audit.delta"]
		cabecera = (
			'<div style="font-family:%s;color:%s;background:%s;padding:16px">'
			% (FUENTE, T["ink"], T["bg"]))
		pie = "</div>"

		if corrida.state == "error":
			# EL CORREO DE LA AUDITORÍA QUE NO CORRIÓ. Llega igual, con el rayado y la
			# causa: no mandar nada dejaría creer que no hay novedades.
			leidos = len(corrida.line_ids.filtered(lambda l: l.state == "done"))
			return cabecera + self._caja(
				'<div style="font-weight:600;color:%s">%s</div>'
				'<div style="color:%s;font-size:13px;margin-top:4px">%s</div>'
				'<div style="color:%s;font-size:12px;margin-top:8px">%s</div>'
				% (T["error"], _("La auditoría no pudo terminar"),
				   T["ink"],
				   _("Se detuvo a los %(leidos)s de %(total)s repositorios: %(causa)s")
				   % {"leidos": leidos, "total": len(corrida.line_ids),
					  "causa": (corrida.error_detail or _("sin causa registrada"))[:200]},
				   T["ink_3"],
				   _("Los números que veas en la aplicación son los de la semana "
					 "pasada. Este correo no afirma nada sobre esta semana.")),
				extra="border-left:3px solid %s" % T["error"]) + pie

		datos = Delta.para_pantalla(corrida.id)
		panel = self.env["repo.health.panel"].datos(
			backend_id=corrida.backend_id.id).get("numeros") or []

		partes = [cabecera]
		partes.append(
			'<div style="font-size:12px;color:%s">%s · %s</div>'
			% (T["ink_3"], corrida.backend_id.name, corrida.display_name))
		partes.append(self._caja(self._numeros(panel)))
		if datos["comparable"]:
			partes.append(self._caja(
				'<div style="color:%s;line-height:1.5">%s</div>'
				% (T["ink"], datos["frase"])))
			partes.append(self._caja(
				'<div style="color:%s;font-size:12px;text-transform:uppercase;'
				'letter-spacing:.04em;margin-bottom:4px">%s</div>%s'
				% (T["ink_3"], _("Lo nuevo"), self._lo_nuevo(datos["nuevos"]))))
			partes.append(self._sin_leer(corrida))
		else:
			partes.append(self._caja(
				'<div style="color:%s">%s</div>' % (T["ink_3"], datos["motivo"])))
			partes.append(self._sin_leer(corrida))
		partes.append(self._plan_pendiente(corrida.backend_id))
		partes.append(
			'<div style="color:%s;font-size:11px;margin-top:8px">%s</div>'
			% (T["ink_3"],
			   _("Lo recibís porque estás en la lista de destinatarios de Repo Manager, "
				 "que se edita en Ajustes. Se envía después de la auditoría programada; "
				 "si la auditoría falla, el correo lo dice en lugar de no llegar.")))
		partes.append(pie)
		return "".join(partes)
