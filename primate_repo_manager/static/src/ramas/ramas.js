/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * La pestaña de ramas — página 3b del entregable, columna por columna.
 *
 * LA COLUMNA QUE JUSTIFICA LA PANTALLA es «Protección», que no dice sólo el estado sino
 * POR QUÉ: «Exige: 1 revisión, sin borrado · Tiene: nada». Una lista que dice «sin
 * protección» y nada más obliga a abrir la política en otra pestaña y comparar de memoria.
 *
 * TRES ESTADOS, NO DOS. Una rama que no se pudo leer NO se dibuja como «no tiene»: va con
 * su trama rayada y su causa. Es la misma distinción que F1 defendió en el informe —GitHub
 * devuelve el mismo 404 para «no está protegida» y para «no podés saberlo»— y dibujarla
 * mal acá sería ese defecto volviendo por la ventana de la interfaz.
 *
 * NADA SE CALCULA ACÁ. Las filas llegan armadas del servidor: la comparación es política,
 * y la política se decide en un solo lugar. Este componente pinta.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * El color dice UNA cosa: qué tan grave es. Por eso «parcial» usa el amarillo de
 * severidad media y no un color propio, y por eso lo ILEGIBLE no lleva chip de color:
 * lleva la trama rayada del sistema. Pintarlo de rojo diría «está mal», y lo que pasa es
 * que no se sabe — que es otra cosa y se ve distinta a propósito.
 */
const ESTADOS = {
	completa: { etiqueta: _t("Completa"), chip: "rm-chip-done" },
	parcial: { etiqueta: _t("Parcial"), chip: "rm-chip-medium" },
	sin_proteccion: { etiqueta: _t("Sin protección"), chip: "rm-chip-critical" },
	no_exige: { etiqueta: _t("No exige protección"), chip: "rm-chip-quiet" },
	ilegible: { etiqueta: _t("Desconocida: no se pudo leer la protección"), chip: null },
};

export class Ramas extends Component {
	static template = "primate_repo_manager.Ramas";
	static props = ["*"];

	setup() {
		this.orm = useService("orm");
		this.state = useState({ filas: [] });
		onWillStart(() => this.cargar());
	}

	async cargar() {
		const id = this.props.record.resId;
		if (!id) {
			// Un repositorio que todavía no se guardó no tiene ramas que mostrar, y
			// preguntar por ellas devolvería un error que no le dice nada a nadie.
			return;
		}
		this.state.filas = await this.orm.call(
			"repo.repository", "datos_de_ramas", [[id]]);
	}

	estado(fila) {
		return ESTADOS[fila.comparacion.estado] || ESTADOS.no_exige;
	}

	/** ¿Esta fila muestra la línea «Exige … · Tiene …»? */
	explica(fila) {
		return ["sin_proteccion", "parcial"].includes(fila.comparacion.estado);
	}

	lista(valores) {
		return valores.join(", ");
	}

	get vacio() {
		return _t("Todavía no se auditó este repositorio, así que no hay ramas que mostrar.");
	}
}

export const ramasField = {
	component: Ramas,
	supportedTypes: ["one2many"],
};

registry.category("fields").add("repo_ramas", ramasField);
