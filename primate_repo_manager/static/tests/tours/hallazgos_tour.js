/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Hallazgos y la bandeja del plan, en un navegador de verdad.
 *
 * Los tres defectos de la primera corrida no daban error de servidor ni de consola:
 *
 * · Dos literales de cadena pegados en varias líneas. En Python son una sola cadena; en
 *   JavaScript son un ERROR DE SINTAXIS que rompe el bundle ENTERO —no sólo este módulo—
 *   y deja la página en blanco, sin un solo mensaje. Es el mismo tropiezo que el `context`
 *   partido en dos que dejó diez pantallas rotas, cambiado de lenguaje.
 * · La acción abría con «agrupar por severidad» de fábrica, y una lista agrupada de Odoo
 *   carga sólo las cabeceras: la pantalla decía «no hay hallazgos que coincidan» con
 *   cuatro en el paginador. Afirmar algo falso con calma es peor que romperse.
 * · El chip mostraba `1_CRITICAL`, que es el valor de ORDEN y no la etiqueta.
 *
 * Por eso este tour comprueba cosas que parecen obvias: que haya filas, que el chip diga
 * una palabra y no un código, y que el camino por teclado llegue hasta el final.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("prm_hallazgos", {
	url: "/odoo/action-primate_repo_manager.action_repo_audit_finding",
	steps: () => [
		{
			trigger: ".rm-hallazgos .rm-hallazgos-fila:not(.rm-hallazgos-encabezado)",
			content: "hay hallazgos a la vista",
		},
		{
			trigger: ".rm-hallazgos-grupo .rm-chip",
			content: "el chip dice la palabra, no el código de orden",
			run() {
				const chip = document.querySelector(".rm-hallazgos-grupo .rm-chip");
				if (/^\d_/.test(chip.textContent.trim())) {
					throw new Error(
						"el chip muestra el valor de orden y no la etiqueta: " +
						chip.textContent.trim());
				}
			},
		},
		{
			trigger: ".rm-bandeja-zona",
			content: "la bandeja del plan está, y en reposo invita",
			run() {
				const soltar = document.querySelector(".rm-bandeja-soltar");
				if (!soltar.textContent.includes("Arrastrá")) {
					throw new Error("la zona de soltar no dice qué hacer");
				}
			},
		},
		{
			// PREVENCIÓN ANTES QUE EXPLICACIÓN: lo que no se puede arrastrar no tiene
			// mango. Si esto falla, la pantalla estaría ofreciendo un gesto que va a
			// rebotar.
			trigger: ".rm-hallazgos-lista",
			content: "lo que no se puede remediar NO tiene mango",
			run() {
				const sinAccion = [...document.querySelectorAll(".rm-hallazgos-fila")]
					.filter((f) => f.querySelector(".rm-hallazgos-no"));
				for (const fila of sinAccion) {
					if (fila.querySelector(".rm-mango:not(.rm-mango-sin)")) {
						throw new Error(
							"un hallazgo que no se puede remediar tiene mango de arrastre");
					}
					if (fila.getAttribute("draggable") === "true") {
						throw new Error(
							"un hallazgo que no se puede remediar es arrastrable");
					}
				}
			},
		},
		{
			trigger: ".rm-mango:not(.rm-mango-sin)",
			content: "el mango se enfoca y el espacio levanta",
			run() {
				const mango = document.querySelector(".rm-mango:not(.rm-mango-sin)");
				mango.focus();
				mango.dispatchEvent(
					new KeyboardEvent("keydown", { key: " ", bubbles: true }));
			},
		},
		{
			trigger: ".rm-hallazgos-levantado",
			content: "la fila levantada se ve, no sólo se anuncia",
		},
		{
			trigger: ".rm-bandeja-anuncio:not(:empty)",
			content: "y se anuncia para el lector de pantalla",
		},
		{
			trigger: ".rm-mango:not(.rm-mango-sin)",
			content: "el espacio otra vez lo suelta en la bandeja",
			run() {
				document.querySelector(".rm-mango:not(.rm-mango-sin)").dispatchEvent(
					new KeyboardEvent("keydown", { key: " ", bubbles: true }));
			},
		},
		{
			trigger: ".rm-bandeja-tarjeta",
			content: "ENTRÓ AL PLAN por teclado, sin tocar el mouse",
		},
		{
			trigger: ".rm-hallazgos-ya",
			content: "y la fila de origen lo dice: sin toast, el estado ya está a la vista",
		},
	],
});
