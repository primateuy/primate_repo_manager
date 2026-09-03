/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * El tramo de lectura del criterio de salida, recorrido en un navegador.
 *
 * Prueba dos cosas que sólo existen en pantalla:
 *
 * · EL CAMINO SIN CALLEJONES. corrida → sus hallazgos → el repositorio afectado → los
 *   hallazgos de ese repositorio. Cada tramo es un botón o un click en un enlace; si
 *   alguno abre un formulario improvisado por Odoo —como pasaba antes de que existiera el
 *   de repositorio— el paso siguiente no encuentra lo que busca.
 *
 * · LA CLASIFICACIÓN A MANO Y SU MARCA. Editar el campo tiene que dejar el origen en
 *   «Definida a mano» sin apretar nada más. Que la auditoría después la respete se prueba
 *   en Python —`test_una_clasificacion_puesta_a_mano_sobrevive_a_la_auditoria`—; acá se
 *   prueba que la pantalla haga su parte, que es la que el usuario ve.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("prm_repositorio", {
	steps: () => [
		{
			content: "abrir el repositorio desde la lista",
			trigger: ".o_list_view td[name=full_name]:contains(sbx-uno)",
			run: "click",
		},
		{
			content: "el formulario existe y muestra sus ramas",
			trigger: ".o_notebook a:contains(Ramas)",
			run: "click",
		},
		{
			trigger: ".o_field_widget[name=branch_ids] td:contains(19.0)",
		},
		{
			content: "y sus colaboradores, con el ORIGEN del permiso y no sólo el permiso",
			trigger: ".o_notebook a:contains(Colaboradores)",
			run: "click",
		},
		{
			trigger: ".o_field_widget[name=collaborator_ids] th:contains(Origen)",
		},
		{
			// En Odoo 19 un campo de selección no es un `<select>` nativo sino un
			// `SelectMenu`: se abre y se elige, como lo hace una persona.
			content: "clasificar a mano: abrir el desplegable",
			trigger: ".o_field_widget[name=classification] .o_select_menu_toggler",
			run: "click",
		},
		{
			content: "y elegir, sin apretar ningún botón de «fijar a mano»",
			trigger: ".o-dropdown--menu .o-dropdown-item:contains(Cliente)",
			run: "click",
		},
		{
			content: "guardar",
			trigger: ".o_form_button_save",
			run: "click",
		},
		{
			content: "EL ORIGEN QUEDA EN «DEFINIDA A MANO» SIN APRETAR NINGÚN BOTÓN MÁS",
			trigger: ".o_field_widget[name=classification_source]:contains(Definida a mano)",
		},
		{
			content: "desde el repositorio se llega a sus hallazgos",
			trigger: "button[name=action_open_findings]",
			run: "click",
		},
		{
			content: "y la lista muestra el hallazgo, no una columna de ids",
			trigger: ".o_list_view td:contains(rama sin protección)",
			run: "click",
		},
		{
			content: "desde el hallazgo se vuelve al repositorio, sin callejón",
			trigger: ".o_field_widget[name=repository_id] a:contains(sbx-uno)",
			run: "click",
		},
		{
			content: "y el repositorio conserva la decisión que se tomó recién",
			trigger: ".o_field_widget[name=classification_source]:contains(Definida a mano)",
		},
	],
});
