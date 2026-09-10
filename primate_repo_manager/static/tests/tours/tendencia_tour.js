/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * La tendencia, dibujada — página 1b del entregable.
 *
 * ESTE TOUR EXISTE POR UNA SOLA COSA: que la línea se CORTE donde una corrida no se pudo
 * medir. Que la serie traiga el hueco se prueba en Python; que el dibujo lo respete, no.
 * Una polilínea que una los dos extremos saltándose el hueco pasaría todos los tests de
 * servidor y afirmaría en pantalla que esa semana se midió.
 *
 * Con CINCO corridas y la del medio fallida, la línea tiene que salir en DOS tramos. Con
 * tres no alcanza: cada lado queda con un solo punto y una línea necesita dos, así que el
 * dibujo saldría vacío y el tour no probaría nada.
 *
 * Y el hueco se dibuja como una BANDA y no como una línea fina. La primera versión usaba
 * `<line>` y OWL no lo renderizaba dentro del `<svg>` —los `<circle>` y los `<polyline>`
 * del mismo bloque sí—, cosa que sólo se vio corriendo el tour. La banda además se lee
 * mejor: ocupa el lugar que esa corrida ocupa en la serie.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("prm_tendencia", {
	steps: () => [
		{
			content: "el panel abre",
			trigger: ".rm-panel",
		},
		{
			content: "se despliega el detalle",
			trigger: ".rm-panel-pliegue a",
			run: "click",
		},
		{
			content: "la tendencia está",
			trigger: ".rm-panel-tendencia h2:contains(Cómo venimos)",
		},
		{
			// EL PASO QUE JUSTIFICA EL TOUR.
			content: "la línea sale en DOS tramos: se corta en la corrida sin medición",
			trigger: ".rm-panel-serie:first-of-type svg polyline:nth-of-type(2)",
		},
		{
			content: "cada corrida medida tiene su punto",
			trigger: ".rm-panel-serie:first-of-type svg circle",
		},
		{
			content: "y el hueco lleva su marca, no un punto en cero",
			trigger: ".rm-panel-serie:first-of-type svg rect.rm-panel-hueco",
		},
		{
			content: "y se dice en palabras, para quien no mira el dibujo",
			// La frase pasó del pie a su propia línea: con los tres elementos en
			// la misma fila quedaba centrada encima del dibujo y lo tapaba.
			trigger: ".rm-panel-serie-aviso:contains(no se rellena)",
		},
	],
});
