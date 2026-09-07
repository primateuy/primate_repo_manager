# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""CODEOWNERS: quién revisa qué, generado desde la política — B3.

PERSONAS CON NOMBRE, NO TEAMS. Es la decisión de F1 y no es una preferencia de estilo:
**los teams no existen en una cuenta de usuario**, y los 113 repositorios de Primate
cuelgan hoy de la cuenta `primateuy`. Un CODEOWNERS con `@primateuy/desarrollo` sería una
línea que GitHub ignora en silencio. Los owners por team esperan la migración a
organización; hasta entonces, cada owner es una persona.

CADA LÍNEA DICE DE DÓNDE SALE SU OWNER. Un CODEOWNERS generado sin procedencia es un
archivo que nadie se anima a tocar: no se sabe si esa línea la puso una regla, una
excepción o alguien a mano hace ocho meses. Acá cada patrón viene con el comentario de qué
lo declaró.

Y NO SE ESCRIBE LO QUE NO SE VERIFICÓ — la lección del check que no corrió, en versión
personas. **Un owner que GitHub va a ignorar no falla al escribirse: falla en silencio
después.** La línea se ignora, las PRs no piden esa revisión, y el repositorio parece
gobernado mientras nadie revisa nada. Por eso cada owner se valida contra el espejo —la
cuenta existe y tiene acceso a ESE repositorio— antes de que su línea entre al archivo.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# La marca que hace reconocible un CODEOWNERS NUESTRO. B3.2 la usa para no pisar jamás
# uno ajeno: sin esta primera línea, el archivo es de otro y no se toca.
MARCA = "# Generado por Primate Repo Manager"


class RepoPolicyCodeowner(models.Model):
	"""Un patrón de ruta y quién lo revisa, declarado en la plantilla.

	POR QUÉ NO SE DERIVA DE LOS GRANTS. «Quién puede escribir» y «quién tiene que revisar»
	son dos cosas distintas: hay gente con push que no revisa nada y revisores que no
	necesitan escribir. Derivar una de la otra las ataría para siempre y haría imposible
	el caso normal — el líder técnico revisa lo que no toca.
	"""
	_name = "repo.policy.codeowner"
	_inherit = ["repo.policy.audited"]
	_description = "Quién revisa qué, dentro de una plantilla"
	_order = "template_id, sequence, id"

	template_id = fields.Many2one(
		"repo.policy.template", string="Plantilla", required=True, ondelete="cascade")
	sequence = fields.Integer(
		string="Orden", default=10,
		help="CODEOWNERS aplica la ÚLTIMA regla que coincide, así que el orden decide. "
			 "Se escribe en este orden y no en otro.")
	path_pattern = fields.Char(
		string="Patrón de ruta", required=True,
		help="Como lo entiende GitHub: `*`, `addons/`, `*.py`.")
	member_id = fields.Many2one(
		"repo.member", string="Revisor", required=True, ondelete="restrict")
	reason = fields.Char(
		string="Por qué", help="Va como comentario al lado de la línea generada.")

	_codeowner_uniq = models.Constraint(
		"UNIQUE (template_id, path_pattern, member_id)",
		"Esa persona ya revisa ese patrón en esta plantilla.")


class RepoRepositoryCodeowners(models.Model):
	_inherit = "repo.repository"

	def generar_codeowners(self):
		"""El contenido del CODEOWNERS de este repositorio, con su procedencia.

		Returns:
			dict: ``contenido`` (el archivo, o cadena vacía si no hay nada escribible),
			``lineas`` (las que entraron) y ``omitidos``: los owners que NO se escriben,
			cada uno con su motivo. **La lista de omitidos no es un detalle: es la razón
			por la que este método existe.** Un owner que GitHub ignora no rompe nada al
			escribirse; rompe después, callado.
		"""
		self.ensure_one()
		plantilla = self.plantilla_efectiva()
		if not plantilla or not plantilla.codeowner_ids:
			return {"contenido": "", "lineas": [], "omitidos": []}

		lineas, omitidos = [], []
		for regla in plantilla.codeowner_ids:
			motivo = self._por_que_no_puede_ser_owner(regla.member_id)
			if motivo:
				omitidos.append({
					"login": regla.member_id.github_login or regla.member_id.display_name,
					"patron": regla.path_pattern,
					"motivo": motivo,
				})
				continue
			lineas.append({
				"patron": regla.path_pattern,
				"login": regla.member_id.github_login,
				"procedencia": regla.reason or _(
					"declarado en la plantilla «%s»") % plantilla.name,
			})

		return {
			"contenido": self._texto_de_codeowners(plantilla, lineas) if lineas else "",
			"lineas": lineas,
			"omitidos": omitidos,
		}

	def _por_que_no_puede_ser_owner(self, miembro):
		"""La validación contra el espejo. Devuelve el motivo, o False si puede.

		DOS COSAS, Y LAS DOS SE COMPRUEBAN CONTRA LO OBSERVADO, no contra lo declarado:
		que la cuenta exista en GitHub —la vimos— y que tenga acceso a ESTE repositorio.
		GitHub ignora en silencio la línea de un owner sin acceso: no avisa, no falla, y
		las PRs simplemente no piden esa revisión.
		"""
		self.ensure_one()
		# «Sin cuenta de GitHub» NO se comprueba acá, y no es un olvido: `repo.member`
		# exige `github_login`, así que esa rama no podría dispararse nunca. Una guarda
		# que no puede fallar es peor que ninguna — parece cubrir algo. Hay un test que
		# fija la garantía en el modelo, que es donde vive.
		colaborador = self.collaborator_ids.filtered(
			lambda c: c.member_id == miembro)
		if not colaborador:
			return _(
				"«%s» no figura como colaborador de este repositorio en el espejo, y "
				"GitHub ignora en silencio la línea de un owner sin acceso"
			) % miembro.github_login
		return False

	def _texto_de_codeowners(self, plantilla, lineas):
		"""El archivo, con su marca y la procedencia de cada línea."""
		self.ensure_one()
		cabecera = [
			MARCA,
			"# Repositorio: %s · plantilla: %s" % (self.full_name, plantilla.code),
			"# Generado el %s. NO editar a mano: la próxima aplicación lo reescribe."
			% fields.Date.to_string(fields.Date.today()),
			"#",
			"# Cada línea dice de dónde sale su revisor. Los owners son PERSONAS: los",
			"# teams no existen en una cuenta de usuario, y una línea con un team que no",
			"# existe la ignora GitHub sin avisar.",
			"",
		]
		cuerpo = []
		for linea in lineas:
			cuerpo.append("# %s" % linea["procedencia"])
			cuerpo.append("%s @%s" % (linea["patron"], linea["login"]))
			cuerpo.append("")
		return "\n".join(cabecera + cuerpo).rstrip("\n") + "\n"


	# ------------------------------------------------------------------
	# B3.3 · qué trabajo de otro se pierde, en castellano
	# ------------------------------------------------------------------

	def ediciones_manuales(self, nuestro, actual):
		"""Las ediciones que alguien hizo a mano, legibles para quien decide.

		LA PREGUNTA DE QUIEN MIRA NO ES «QUÉ BYTES DIFIEREN». Es «qué trabajo de otro se
		va si aprieto». Un diff crudo contesta la primera y deja la segunda para que la
		deduzca cada uno — y la vara es la de D2.4: la pantalla que decide entre copias
		divergentes dice qué desaparece si elegís, no qué hash cambió.

		Por eso se comparan las LÍNEAS DE OWNER, no el texto entero: la cabecera la
		reescribimos nosotros en cada generación —lleva la fecha— y mostrarla como
        «cambio de otro» sería acusar a alguien del ruido que hacemos nosotros.

		Returns:
			list: dicts con ``tipo`` (`agregada`, `cambiada`, `quitada`), ``patron``,
			``owners`` y, en las cambiadas, ``owners_antes``.
		"""
		antes = self._owners_por_patron(nuestro)
		ahora = self._owners_por_patron(actual)
		cambios = []
		for patron, owners in ahora.items():
			if patron not in antes:
				cambios.append({"tipo": "agregada", "patron": patron, "owners": owners})
			elif owners != antes[patron]:
				cambios.append({"tipo": "cambiada", "patron": patron,
								"owners": owners, "owners_antes": antes[patron]})
		for patron, owners in antes.items():
			if patron not in ahora:
				cambios.append({"tipo": "quitada", "patron": patron, "owners": owners})
		return cambios

	def _owners_por_patron(self, texto):
		"""Las líneas de owner de un CODEOWNERS, sin comentarios ni vacías."""
		salida = {}
		for linea in (texto or "").splitlines():
			limpia = linea.strip()
			if not limpia or limpia.startswith("#"):
				continue
			partes = limpia.split()
			if len(partes) < 2:
				continue
			salida[partes[0]] = partes[1:]
		return salida

	def frase_de_ediciones(self, cambios):
		"""Las ediciones, en frases. Es lo que se guarda en el payload y lo que se lee.

		Va como texto y no como estructura porque tiene que sobrevivir dentro de la
		huella del plan y leerse en la bitácora seis meses después, donde no va a haber
		un componente que la interprete.
		"""
		frases = []
		for cambio in cambios:
			owners = " ".join("@%s" % o.lstrip("@") for o in cambio["owners"])
			if cambio["tipo"] == "agregada":
				frases.append(_("Alguien agregó a mano: %(patron)s → %(owners)s") % {
					"patron": cambio["patron"], "owners": owners})
			elif cambio["tipo"] == "quitada":
				frases.append(_("Alguien quitó a mano: %(patron)s (era %(owners)s)") % {
					"patron": cambio["patron"], "owners": owners})
			else:
				antes = " ".join(
					"@%s" % o.lstrip("@") for o in cambio["owners_antes"])
				frases.append(_(
					"Alguien cambió a mano quién revisa %(patron)s: %(antes)s → "
					"%(owners)s") % {"patron": cambio["patron"], "antes": antes,
									 "owners": owners})
		return "\n".join(frases)
