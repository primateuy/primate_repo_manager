# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Una fila por corrida y por métrica. La historia, comprada desde hoy.

POR QUÉ EMPIEZA CON B4 Y NO CON EL PANEL QUE LA VA A MOSTRAR (E4). **La tendencia no se
reconstruye hacia atrás.** Recalcular el pasado desde el espejo daría el estado de HOY
proyectado sobre fechas viejas, que es peor que no tener historia: sería una línea con
forma de dato y sin ningún dato adentro. Si las métricas empezaran a guardarse en E4, ese
panel abriría con un punto — y un gráfico de tendencia con un solo punto es un número con
adornos.

Cuesta un modelo chico y una llamada al cerrar la corrida. Para cuando E4 exista va a
haber meses de historia real detrás.

NO SE INCREMENTA NADA. Cada corrida INSERTA sus filas; nadie suma sobre una fila
compartida. Es la cuarta regla de construcción, y acá se cumple sola porque una medición
pertenece a una corrida y a ninguna otra.

LO QUE NO SE PUDO LEER NO SE MAQUILLA. Las métricas se copian del panel de salud tal como
él las calcula, con su doctrina: los repositorios que no se pudieron leer no entran en los
porcentajes y se cuentan aparte. Guardar acá un número «redondeado hacia lo bueno» sería
mentirle a un gráfico que nadie va a poder auditar dentro de seis meses.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class RepoMetric(models.Model):
	_name = "repo.metric"
	_description = "Medición de una corrida de auditoría"
	_order = "measured_at desc, key"

	run_id = fields.Many2one(
		"repo.audit.run", string="Corrida", required=True, ondelete="cascade", index=True)
	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True, ondelete="cascade", index=True)
	key = fields.Char(string="Métrica", required=True, index=True)
	value = fields.Float(string="Valor", required=True)
	measured_at = fields.Datetime(string="Medida el", required=True, index=True)

	_metric_uniq = models.Constraint(
		"UNIQUE (run_id, key)",
		"Esa corrida ya tiene esa métrica medida.")

	@api.model
	def registrar_corrida(self, run):
		"""Toma la foto de las métricas al cerrar una corrida.

		Idempotente por la restricción de unicidad: recalcular una corrida no duplica
		filas. Si ya están, se dejan como estaban — una medición vieja no se reescribe con
		el estado de hoy, que es justo lo que arruinaría la serie.
		"""
		if self.search_count([("run_id", "=", run.id)]):
			return self.browse()
		datos = self.env["repo.health.panel"].datos(backend_id=run.backend_id.id)
		cuando = run.finished_at or fields.Datetime.now()
		filas = [
			{
				"run_id": run.id, "backend_id": run.backend_id.id,
				"key": clave, "value": valor, "measured_at": cuando,
			}
			for clave, valor in self._metricas(datos).items()
		]
		return self.create(filas) if filas else self.browse()

	@api.model
	def _metricas(self, datos):
		"""Qué se guarda de todo lo que el panel calcula: **los tres números**.

		Sólo el bloque `numeros`, y de él sólo lo que ES un número. Guardar todo lo que
		el panel devuelve arrastraría ids de conexión y frases de estado, que no son una
		serie: una historia de ids no se grafica y no se compara con nada.

		UN VALOR AUSENTE NO SE GUARDA COMO CERO. El panel devuelve `None` cuando no hay
		nada que medir —que es distinto de medir cero, y ésa es su regla de oro— y acá se
		respeta salteando la fila. Un cero inventado es indistinguible de un cero medido
		dentro de seis meses, cuando nadie se acuerde.

		El tramo «sin leer» de cada número SÍ se guarda, con su propia clave: sin él, un
		porcentaje de una corrida donde la mitad no se pudo leer se compararía de igual a
		igual con uno donde se leyó todo.
		"""
		salida = {}
		for numero in (datos or {}).get("numeros") or []:
			clave = numero.get("clave")
			if not clave:
				continue
			valor = numero.get("valor")
			if isinstance(valor, (int, float)) and not isinstance(valor, bool):
				salida[clave] = float(valor)
			sin_leer = numero.get("sin_leer")
			if isinstance(sin_leer, (int, float)) and not isinstance(sin_leer, bool):
				salida["%s.sin_leer" % clave] = float(sin_leer)
		return salida
