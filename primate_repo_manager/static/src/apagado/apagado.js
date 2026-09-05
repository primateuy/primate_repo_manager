/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * EL CASILLERO APAGADO — la única implementación de la regla 2.
 *
 * «El producto completo siempre se ve; lo no implementado se muestra desactivado, con su
 * cartel de qué es y con qué bloque llega.» Vale en la navegación y también DENTRO de
 * cada pantalla: un botón, una pestaña, una columna o un bloque de algo que todavía no
 * existe va acá.
 *
 * POR QUÉ UNA SOLA. La navegación ya tenía su versión, y cada pantalla iba a inventar la
 * suya: cinco variantes del mismo cartel divergen, y la que menos se mira envejece mal.
 * Esta recibe qué es y con qué bloque llega, y nada más — no acepta un `onClick`, porque
 * un casillero apagado que hace algo dejó de estar apagado.
 */

import { Component } from "@odoo/owl";

export class Apagado extends Component {
	static template = "primate_repo_manager.Apagado";
	static props = {
		// Qué es, en las palabras del usuario: «Comparar con anterior».
		que: { type: String },
		// Con qué bloque llega: «E2». Se muestra tal cual, sin inventar fechas — una
		// fecha prometida es una deuda; un bloque es un lugar en el plan.
		bloque: { type: String },
		// «boton» (en línea) o «bloque» (una caja del tamaño de lo que va a venir).
		forma: { type: String, optional: true },
		// Una línea más de contexto, cuando el nombre no alcanza para entender qué falta.
		detalle: { type: String, optional: true },
	};
	static defaultProps = { forma: "boton" };

	get clase() {
		return "rm-apagado rm-apagado-" + this.props.forma;
	}

	get cartel() {
		return `${this.props.que} — llega con ${this.props.bloque}`;
	}
}
