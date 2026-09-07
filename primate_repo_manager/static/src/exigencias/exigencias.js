/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * «Incumplen hoy», por exigencia — página 4a del entregable.
 *
 * POR QUÉ ESTE NÚMERO CAMBIA UNA DECISIÓN. El formulario dice qué exige la plantilla;
 * esta columna dice a cuántos les falta. Subir las aprobaciones de 1 a 2 puede no afectar
 * a nadie o romperle el día a veinte equipos, y sin el número las dos cosas se ven igual.
 *
 * LO QUE NO SE PUDO LEER NO ENGROSA EL NÚMERO, Y SE DICE. Contarlo como incumplimiento
 * acusaría a repositorios sanos; dejarlo afuera en silencio los contaría como sanos.
 * Va aparte, con su trama, debajo de la tabla.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class Exigencias extends Component {
	static template = "primate_repo_manager.Exigencias";
	static props = ["*"];

	setup() {
		this.orm = useService("orm");
		this.state = useState({ filas: [] });
		onWillStart(() => this.cargar());
	}

	async cargar() {
		const id = this.props.record.resId;
		if (!id) {
			return;
		}
		this.state.filas = await this.orm.call(
			"repo.policy.template", "incumplimientos_por_exigencia", [[id]]);
	}

	/** El chip sólo se pinta cuando hay algo que mirar. Cero no es una alarma. */
	chip(fila) {
		return fila.incumplen ? "rm-chip-high" : "rm-chip-done";
	}

	get ilegibles() {
		return this.state.filas.length ? this.state.filas[0].ilegibles : 0;
	}

	get evaluadas() {
		return this.state.filas.length ? this.state.filas[0].evaluadas : 0;
	}

	get avisoIlegibles() {
		return _t(
			"%s rama(s) gobernada(s) no se pudieron leer y no entran en estos números: " +
			"de lo que no se pudo leer no se afirma nada.",
			this.ilegibles);
	}

	get vacio() {
		return _t("Esta plantilla todavía no gobierna ninguna rama auditada.");
	}
}

registry.category("fields").add("repo_exigencias", {
	component: Exigencias,
	supportedTypes: ["char", "integer"],
});
