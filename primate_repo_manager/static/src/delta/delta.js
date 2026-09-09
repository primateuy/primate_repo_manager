/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * «Qué cambió respecto de la corrida anterior» — página 2b del entregable.
 *
 * POR QUÉ ESTA PANTALLA EXISTE. La lista completa de una corrida no se lee: doscientos
 * setenta y tres hallazgos son un muro. Lo que alguien necesita el lunes a la mañana es
 * «tres cosas nuevas esta semana», y eso es lo que se dibuja acá.
 *
 * TRES BLOQUES, Y EL TERCERO ES EL QUE HACE CREÍBLES A LOS OTROS DOS. «Sin confirmar»
 * lista los repositorios que no se pudieron volver a leer, CON SU MOTIVO, y dice que sus
 * hallazgos anteriores no cuentan como resueltos ni como nuevos. Sin ese bloque, el
 * número de resueltos mejora solo cada vez que GitHub falla.
 *
 * NADA SE CALCULA ACÁ. Las filas, la frase y las salvedades llegan armadas del servidor:
 * qué se puede afirmar y qué no es una decisión del producto, no del navegador. Este
 * componente pinta. Es la misma regla de la tabla de ramas.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/** El color dice UNA cosa: qué tan grave es. Las clases salen del vocabulario común. */
const CHIP = {
	critical: "rm-chip-critical",
	high: "rm-chip-high",
	medium: "rm-chip-medium",
	low: "rm-chip-quiet",
	info: "rm-chip-quiet",
};

export class Delta extends Component {
	static template = "primate_repo_manager.Delta";
	static props = ["*"];

	setup() {
		this.orm = useService("orm");
		this.action = useService("action");
		this.state = useState({ datos: null, cargando: true, comparandoCon: null });
		onWillStart(() => this.cargar());
	}

	async cargar(anteriorId = null) {
		const id = this.props.record.resId;
		if (!id) {
			this.state.cargando = false;
			return;
		}
		this.state.cargando = true;
		this.state.datos = await this.orm.call(
			"repo.audit.delta", "para_pantalla", [id], { anterior: anteriorId });
		this.state.comparandoCon = anteriorId;
		this.state.cargando = false;
	}

	chip(fila) {
		return CHIP[fila.severidad] || "rm-chip-quiet";
	}

	async comparar(ev) {
		const valor = ev.target.value;
		await this.cargar(valor ? Number(valor) : null);
	}

	/**
	 * «Armar plan con los N nuevos». ARMA Y NO EJECUTA, como todo en este módulo: deja
	 * un plan en borrador que después alguien tiene que aprobar operación por operación.
	 */
	async armarPlan() {
		const accion = await this.orm.call(
			"repo.audit.run", "action_armar_plan_con_los_nuevos",
			[this.props.record.resId],
			{ hallazgo_ids: this.state.datos.nuevos_ids || [] });
		if (accion) {
			await this.action.doAction(accion);
		}
	}

	get textoDelBoton() {
		const n = (this.state.datos && this.state.datos.nuevos.length) || 0;
		return _t("Armar plan con los %s nuevos", n);
	}
}

export const deltaField = {
	component: Delta,
	supportedTypes: ["one2many"],
};

registry.category("fields").add("repo_delta", deltaField);
