/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * La propuesta de checks requeridos — B2.3.
 *
 * ABRE VACÍA, Y LA PANTALLA VACÍA ES EL ARGUMENTO. Hoy no hay un solo check que exigir:
 * 17 repositorios declaran workflows en un archivo y ninguno corrió jamás. Una pantalla
 * que sólo dijera «no hay datos» dejaría a quien mira sin saber si es que el módulo no
 * miró; ésta dice los dos números y qué tiene que pasar para que aparezcan candidatos.
 *
 * PROPONE, NO DECIDE. No hay ningún botón que agregue el check a la plantilla: qué queda
 * exigido se decide una vez, mirando los números. Este componente los pone sobre la mesa.
 *
 * Y LOS NOMBRES SE MUESTRAN EN MONO Y SIN TOCAR. Es el string exacto que un ruleset va a
 * exigir; mostrarlo «lindo» —recortado, con mayúsculas arregladas— invitaría a copiar una
 * versión que GitHub nunca reporta, y un nombre aproximado bloquea todos los merges.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ChecksPropuestos extends Component {
	static template = "primate_repo_manager.ChecksPropuestos";
	static props = ["*"];

	setup() {
		this.orm = useService("orm");
		this.state = useState({ datos: null });
		onWillStart(() => this.cargar());
	}

	async cargar() {
		const id = this.props.record.resId;
		if (!id) {
			return;
		}
		this.state.datos = await this.orm.call(
			"repo.policy.template", "candidatos_de_check", [[id]]);
	}

	get hayCandidatos() {
		return Boolean(this.state.datos && this.state.datos.candidatos.length);
	}

	/** Por qué está vacía, con los dos números que lo explican. */
	get explicacionDelVacio() {
		const d = this.state.datos || {};
		return _t(
			"Sin candidatos todavía: %(declaran)s de %(total)s repositorios de esta " +
			"plantilla declaran workflows en un archivo, y %(corrieron)s han reportado " +
			"un check. Un check requerido cuyo nombre GitHub no reporta bloquea todos " +
			"los merges del repositorio, así que acá sólo aparece lo que se vio correr. " +
			"Cuando la CI se active, los candidatos aparecen ordenados por cobertura.",
			{
				declaran: d.con_workflows || 0,
				total: d.repositorios || 0,
				corrieron: d.con_checks || 0,
			});
	}

	cobertura(fila) {
		return _t("%(n)s de %(total)s", { n: fila.en_cuantos, total: fila.de_cuantos });
	}
}

registry.category("fields").add("repo_checks_propuestos", {
	component: ChecksPropuestos,
	supportedTypes: ["boolean", "char"],
});
