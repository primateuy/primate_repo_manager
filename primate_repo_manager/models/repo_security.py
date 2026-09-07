# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Alertas de seguridad de GitHub, espejadas — B6.

TRES ESTADOS, Y NINGUNO SE COLAPSA CON OTRO. Medido contra la cuenta real el 7-sep-2026,
no supuesto:

    hay alertas          la API devolvió la lista (vacía o no: una lista vacía ES un dato)
    apagado en el repo   la función existe y está deshabilitada ahí
    no se pudo leer      falta permiso, techo de plan, o la API no contestó

**«Apagado» no es «cero alertas».** Un panel que diga «cero secretos filtrados» porque la
función estaba apagada afirma sobre algo que nunca miró, y es la peor pantalla que este
módulo podría tener. Por eso el estado vive en su propia fila y no se deduce de que la
lista esté vacía.

EL SECRETO NUNCA VIAJA ACÁ. Ver `RepoSecurityAlert`: se guarda dónde está, de qué tipo es
y el enlace a GitHub. El valor no, ni siquiera el fragmento que la API ofrece.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

FUENTES = [
	("secret_scanning", "Secretos filtrados"),
	("dependabot", "Vulnerabilidades de dependencias"),
]

ESTADOS = [
	("con_datos", "Leído"),
	("apagado", "Apagado en el repositorio"),
	("no_legible", "No se pudo leer"),
]


class RepoSecurityScan(models.Model):
	"""En qué estado quedó la lectura de una fuente de alertas, por repositorio.

	Una fila por repositorio y fuente. Existe para que «no hay alertas» y «no se miró»
	sean dos filas distintas y no la misma ausencia.
	"""
	_name = "repo.security.scan"
	_description = "Estado de la lectura de alertas de seguridad"
	_order = "repository_id, source"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	source = fields.Selection(FUENTES, string="Fuente", required=True, index=True)
	state = fields.Selection(ESTADOS, string="Estado", required=True)
	cause = fields.Char(
		string="Causa",
		help="Cuando está apagado o no se pudo leer: el mensaje de GitHub, tal cual. Es "
			 "lo que distingue una acción gratis de una decisión comercial.")
	needs_advanced_security = fields.Boolean(
		string="Encenderlo exige Advanced Security",
		help="Sólo para secret scanning en repositorios PRIVADOS. No sale del mensaje de "
			 "GitHub —que dice lo mismo en público y en privado— sino de la visibilidad "
			 "del repositorio, que es un hecho que ya tenemos. Se marca aparte para no "
			 "hacerlo pasar por una respuesta de la API.")
	alert_count = fields.Integer(string="Alertas abiertas")
	last_seen_at = fields.Datetime(string="Leído por última vez", readonly=True)
	origin = fields.Selection(
		[("sync", "Auditoría"), ("webhook", "Evento de GitHub")],
		string="Por dónde entró", default="sync", required=True)

	_scan_uniq = models.Constraint(
		"UNIQUE (repository_id, source)",
		"Esa fuente ya está registrada para el repositorio.")

	@api.model
	def upsert(self, repo, source, state, cause=False, alert_count=0, origin="sync"):
		"""La única forma de escribir el estado de una lectura."""
		valores = {
			"repository_id": repo.id, "source": source, "state": state,
			"cause": cause or False, "alert_count": alert_count,
			"needs_advanced_security": bool(
				source == "secret_scanning" and state == "apagado"
				and repo.visibility == "private"),
			"last_seen_at": fields.Datetime.now(), "origin": origin,
		}
		fila = self.search([
			("repository_id", "=", repo.id), ("source", "=", source)], limit=1)
		if not fila:
			return self.create(valores)
		iguales = all(fila[campo] == valores[campo] for campo in (
			"state", "cause", "alert_count", "needs_advanced_security"))
		fila.write({"last_seen_at": valores["last_seen_at"], "origin": origin}
				   if iguales else valores)
		return fila


class RepoSecurityAlert(models.Model):
	"""Una alerta de seguridad, espejada.

	EL SECRETO NO ENTRA ACÁ, Y ES UNA REGLA DEL MÓDULO, NO UNA OMISIÓN.

	La API de secret scanning devuelve el secreto —entero en `secret`, y parcial en los
	campos de contexto—. Nada de eso se guarda: **un módulo de gobernanza no replica la
	filtración que reporta**. Copiarlo, aunque sea un fragmento, lo pondría en la base, en
	los backups, en la bitácora, en el informe en PDF y en la pantalla — multiplicando por
	seis los lugares donde ese secreto existe, que es exactamente lo contrario de lo que
	se está tratando de arreglar.

	Lo que sí se guarda alcanza para actuar: **qué tipo de secreto es, dónde está, y el
	enlace a GitHub**, que es donde alguien con permiso puede verlo y revocarlo.
	"""
	_name = "repo.security.alert"
	_description = "Alerta de seguridad de un repositorio"
	_order = "repository_id, source, external_id desc"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	source = fields.Selection(FUENTES, string="Fuente", required=True, index=True)
	external_id = fields.Integer(string="Número en GitHub", required=True, index=True)
	state = fields.Char(string="Estado en GitHub", index=True)
	# Secret scanning.
	secret_type = fields.Char(string="Tipo de secreto")
	location = fields.Char(
		string="Dónde",
		help="Ruta del archivo donde GitHub lo encontró. Nunca el contenido.")
	# Dependabot.
	severity = fields.Char(string="Severidad según GitHub")
	package_name = fields.Char(string="Paquete")
	summary = fields.Char(string="Resumen")
	html_url = fields.Char(
		string="Ver en GitHub",
		help="Donde alguien con permiso puede ver el detalle. El detalle no se copia acá.")
	last_seen_at = fields.Datetime(string="Visto por última vez", readonly=True)
	origin = fields.Selection(
		[("sync", "Auditoría"), ("webhook", "Evento de GitHub")],
		string="Por dónde entró", default="sync", required=True)

	_alert_uniq = models.Constraint(
		"UNIQUE (repository_id, source, external_id)",
		"Esa alerta ya está registrada para el repositorio.")

	# Los campos de la API que NO se copian, declarados para que la omisión sea una
	# decisión visible y no un olvido. Hay un test que falla si alguno aparece como campo.
	CAMPOS_PROHIBIDOS = ("secret", "secret_value", "raw_secret", "fragment", "match")

	@api.model
	def upsert(self, repo, source, alerta, origin="sync"):
		"""Espeja una alerta, tomando SÓLO lo que se puede guardar.

		El filtrado es por lista blanca —se nombra lo que entra— y no por lista negra: una
		lista negra deja pasar el campo nuevo que GitHub agregue mañana, y acá el campo
		nuevo que se cuele puede ser el secreto.
		"""
		valores = {
			"repository_id": repo.id,
			"source": source,
			"external_id": alerta.get("number"),
			"state": alerta.get("state"),
			"html_url": alerta.get("html_url"),
			"last_seen_at": fields.Datetime.now(),
			"origin": origin,
		}
		if source == "secret_scanning":
			valores["secret_type"] = (
				alerta.get("secret_type_display_name") or alerta.get("secret_type"))
			ubicacion = alerta.get("locations_url") or ""
			valores["location"] = ubicacion.split("/repos/")[-1] if ubicacion else False
		else:
			aviso = alerta.get("security_advisory") or {}
			vulnerabilidad = alerta.get("security_vulnerability") or {}
			paquete = (vulnerabilidad.get("package") or {})
			valores["severity"] = (
				vulnerabilidad.get("severity") or aviso.get("severity"))
			valores["package_name"] = paquete.get("name")
			valores["summary"] = aviso.get("summary")

		fila = self.search([
			("repository_id", "=", repo.id), ("source", "=", source),
			("external_id", "=", valores["external_id"]),
		], limit=1)
		if not fila:
			return self.create(valores)
		iguales = all(
			fila[campo] == valores[campo] for campo in valores
			if campo not in ("last_seen_at", "origin"))
		fila.write({"last_seen_at": valores["last_seen_at"], "origin": origin}
				   if iguales else valores)
		return fila
