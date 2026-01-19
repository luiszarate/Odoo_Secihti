# -*- coding: utf-8 -*-

from odoo import models, fields, api, tools


class SecBudgetRubroSummary(models.Model):
    """
    SQL View that groups budget allocations by Activity + Rubro
    to show aggregated totals in the simulation view.

    This solves the issue of duplicate rubros appearing in the
    "Rubros Después de Simulación" tab.
    """
    _name = 'sec.budget.rubro.summary'
    _description = 'Budget Rubro Summary (Grouped by Activity + Rubro)'
    _auto = False  # This is a SQL view, not a regular table
    _order = 'simulation_id, activity_id, rubro_id'

    simulation_id = fields.Many2one(
        'sec.budget.simulation',
        string='Simulation',
        readonly=True
    )

    activity_id = fields.Many2one(
        'sec.activity',
        string='Activity',
        readonly=True
    )

    rubro_id = fields.Many2one(
        'sec.rubro',
        string='Rubro',
        readonly=True
    )

    budget_line_id = fields.Many2one(
        'sec.activity.budget.line',
        string='Budget Line',
        readonly=True,
        help='Reference to the budget line (there should be only one per activity+rubro)'
    )

    line_amount_total = fields.Monetary(
        string='Total Budget',
        readonly=True,
        currency_field='currency_id',
        help='Total budget allocated to this rubro in the activity'
    )

    line_rem_total = fields.Monetary(
        string='Real Remaining',
        readonly=True,
        currency_field='currency_id',
        help='Remaining budget before simulation (from real budget line)'
    )

    amount = fields.Monetary(
        string='Allocated in Simulation',
        readonly=True,
        currency_field='currency_id',
        help='Total amount allocated from this rubro in this simulation (sum of all allocations)'
    )

    simulated_remaining = fields.Monetary(
        string='Simulated Remaining',
        readonly=True,
        currency_field='currency_id',
        help='Remaining budget after simulation: Real Remaining - Allocated in Simulation'
    )

    simulated_remaining_status = fields.Selection([
        ('positive', 'Positive'),
        ('zero', 'Zero'),
        ('negative', 'Negative')
    ], string='Status', readonly=True)

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        readonly=True
    )

    project_id = fields.Many2one(
        'sec.project',
        string='Project',
        readonly=True
    )

    def init(self):
        """
        Create the SQL view that groups allocations by simulation + activity + rubro
        """
        tools.drop_view_if_exists(self.env.cr, self._table)

        query = """
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    -- Use ROW_NUMBER to generate unique IDs for the view
                    ROW_NUMBER() OVER (ORDER BY a.simulation_id, a.activity_id, a.rubro_id) AS id,
                    a.simulation_id,
                    a.activity_id,
                    a.rubro_id,
                    -- Get the budget line ID (should be unique per activity+rubro)
                    MAX(a.budget_line_id) as budget_line_id,
                    -- Sum the allocated amounts for this rubro across all planned expenses
                    SUM(a.amount) as amount,
                    -- Budget line totals (these should be the same for all allocations of the same budget_line)
                    MAX(bl.amount_total) as line_amount_total,
                    MAX(bl.rem_total) as line_rem_total,
                    -- Calculate simulated remaining: Real Remaining - Total Allocated in this simulation
                    MAX(bl.rem_total) - SUM(a.amount) as simulated_remaining,
                    -- Determine status based on simulated remaining
                    CASE
                        WHEN MAX(bl.rem_total) - SUM(a.amount) > 0 THEN 'positive'
                        WHEN MAX(bl.rem_total) - SUM(a.amount) = 0 THEN 'zero'
                        ELSE 'negative'
                    END as simulated_remaining_status,
                    -- Get currency and project from simulation
                    MAX(s.currency_id) as currency_id,
                    MAX(s.project_id) as project_id
                FROM
                    sec_budget_allocation a
                    INNER JOIN sec_budget_simulation s ON a.simulation_id = s.id
                    INNER JOIN sec_activity_budget_line bl ON a.budget_line_id = bl.id
                WHERE
                    a.budget_line_id IS NOT NULL
                    AND a.rubro_id IS NOT NULL
                GROUP BY
                    a.simulation_id,
                    a.activity_id,
                    a.rubro_id
            )
        """ % self._table

        self.env.cr.execute(query)
