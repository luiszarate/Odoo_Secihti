# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SecRubroDashboard(models.Model):
    """Dashboard de rubros por etapa"""
    _name = "sec.rubro.dashboard"
    _description = "Dashboard de Rubros por Etapa"
    _auto = False
    _order = "stage_name, rubro_name"

    # Identificadores
    stage_id = fields.Many2one("sec.stage", string="Etapa", readonly=True)
    stage_name = fields.Char(string="Nombre de Etapa", readonly=True)
    rubro_id = fields.Many2one("sec.rubro", string="Rubro", readonly=True)
    rubro_name = fields.Char(string="Nombre de Rubro", readonly=True)
    project_id = fields.Many2one("sec.project", string="Proyecto", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", readonly=True)

    # Montos presupuestados
    amount_programa = fields.Monetary(
        string="Presupuesto Programa (70%)",
        currency_field="currency_id",
        readonly=True,
    )
    amount_concurrente = fields.Monetary(
        string="Presupuesto Concurrente (30%)",
        currency_field="currency_id",
        readonly=True,
    )
    amount_total = fields.Monetary(
        string="Presupuesto Total",
        currency_field="currency_id",
        readonly=True,
    )

    # Montos ejecutados (gastados)
    exec_programa = fields.Monetary(
        string="Gastado Programa (70%)",
        currency_field="currency_id",
        readonly=True,
    )
    exec_concurrente = fields.Monetary(
        string="Gastado Concurrente (30%)",
        currency_field="currency_id",
        readonly=True,
    )
    exec_total = fields.Monetary(
        string="Gastado Total",
        currency_field="currency_id",
        readonly=True,
    )

    # Montos disponibles
    rem_programa = fields.Monetary(
        string="Disponible Programa",
        currency_field="currency_id",
        readonly=True,
    )
    rem_concurrente = fields.Monetary(
        string="Disponible Concurrente",
        currency_field="currency_id",
        readonly=True,
    )
    rem_total = fields.Monetary(
        string="Disponible Total",
        currency_field="currency_id",
        readonly=True,
    )

    # Porcentajes de ejecución
    pct_exec_programa = fields.Float(
        string="% Ejecución Programa",
        readonly=True,
    )
    pct_exec_concurrente = fields.Float(
        string="% Ejecución Concurrente",
        readonly=True,
    )
    pct_exec_total = fields.Float(
        string="% Ejecución Total",
        readonly=True,
    )

    def init(self):
        """Crea la vista SQL para el dashboard de rubros"""
        query = """
            CREATE OR REPLACE VIEW sec_rubro_dashboard AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY s.id, r.id) AS id,
                    s.id AS stage_id,
                    s.name AS stage_name,
                    r.id AS rubro_id,
                    r.name AS rubro_name,
                    s.project_id AS project_id,
                    p.currency_id AS currency_id,

                    -- Montos presupuestados (suma de todas las líneas presupuestales para este rubro en esta etapa)
                    COALESCE(SUM(bl.amount_programa), 0) AS amount_programa,
                    COALESCE(SUM(bl.amount_concurrente), 0) AS amount_concurrente,
                    COALESCE(SUM(bl.amount_total), 0) AS amount_total,

                    -- Montos ejecutados (suma de todas las líneas presupuestales para este rubro en esta etapa)
                    COALESCE(SUM(bl.exec_programa), 0) AS exec_programa,
                    COALESCE(SUM(bl.exec_concurrente), 0) AS exec_concurrente,
                    COALESCE(SUM(bl.exec_total), 0) AS exec_total,

                    -- Montos disponibles (presupuesto - ejecutado)
                    COALESCE(SUM(bl.amount_programa), 0) - COALESCE(SUM(bl.exec_programa), 0) AS rem_programa,
                    COALESCE(SUM(bl.amount_concurrente), 0) - COALESCE(SUM(bl.exec_concurrente), 0) AS rem_concurrente,
                    COALESCE(SUM(bl.amount_total), 0) - COALESCE(SUM(bl.exec_total), 0) AS rem_total,

                    -- Porcentajes de ejecución
                    CASE
                        WHEN COALESCE(SUM(bl.amount_programa), 0) > 0
                        THEN (COALESCE(SUM(bl.exec_programa), 0) / SUM(bl.amount_programa)) * 100
                        ELSE 0
                    END AS pct_exec_programa,
                    CASE
                        WHEN COALESCE(SUM(bl.amount_concurrente), 0) > 0
                        THEN (COALESCE(SUM(bl.exec_concurrente), 0) / SUM(bl.amount_concurrente)) * 100
                        ELSE 0
                    END AS pct_exec_concurrente,
                    CASE
                        WHEN COALESCE(SUM(bl.amount_total), 0) > 0
                        THEN (COALESCE(SUM(bl.exec_total), 0) / SUM(bl.amount_total)) * 100
                        ELSE 0
                    END AS pct_exec_total

                FROM sec_stage s
                INNER JOIN sec_project p ON s.project_id = p.id
                CROSS JOIN sec_rubro r
                LEFT JOIN sec_activity a ON a.stage_id = s.id
                LEFT JOIN sec_activity_budget_line bl ON bl.activity_id = a.id AND bl.rubro_id = r.id

                WHERE r.active = true

                GROUP BY s.id, s.name, r.id, r.name, s.project_id, p.currency_id

                -- Solo mostrar rubros que tienen presupuesto o ejecución en esta etapa
                HAVING COALESCE(SUM(bl.amount_total), 0) > 0 OR COALESCE(SUM(bl.exec_total), 0) > 0
            )
        """
        self.env.cr.execute(query)
