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
        Create the SQL view that shows ALL budget lines (rubros) from the project,
        including those that weren't used in the simulation.

        This gives a complete picture of how the project budget would look after
        applying the simulation.
        """
        tools.drop_view_if_exists(self.env.cr, self._table)

        query = """
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY sim.id, bl.activity_id, bl.rubro_id) AS id,
                    sim.id as simulation_id,
                    bl.activity_id,
                    bl.rubro_id,
                    bl.id as budget_line_id,
                    bl.amount_total as line_amount_total,
                    bl.rem_total as line_rem_total,
                    -- Amount allocated in this simulation (0 if not used)
                    COALESCE(alloc.total_allocated, 0) as amount,
                    -- Simulated remaining = Real Remaining - Allocated in Simulation
                    bl.rem_total - COALESCE(alloc.total_allocated, 0) as simulated_remaining,
                    -- Status based on simulated remaining
                    CASE
                        WHEN bl.rem_total - COALESCE(alloc.total_allocated, 0) > 0 THEN 'positive'
                        WHEN bl.rem_total - COALESCE(alloc.total_allocated, 0) = 0 THEN 'zero'
                        ELSE 'negative'
                    END as simulated_remaining_status,
                    proj.currency_id,
                    sim.project_id
                FROM
                    sec_budget_simulation sim
                    INNER JOIN sec_project proj ON sim.project_id = proj.id
                    -- Get all budget lines from the project's activities
                    CROSS JOIN sec_activity_budget_line bl
                    -- Left join to get allocations for this simulation (if any)
                    LEFT JOIN (
                        SELECT
                            a.simulation_id,
                            a.budget_line_id,
                            SUM(a.amount) as total_allocated
                        FROM sec_budget_allocation a
                        WHERE a.budget_line_id IS NOT NULL
                        GROUP BY a.simulation_id, a.budget_line_id
                    ) alloc ON alloc.simulation_id = sim.id AND alloc.budget_line_id = bl.id
                WHERE
                    -- Only include budget lines from activities that belong to the simulation's project
                    bl.activity_id IN (
                        SELECT id FROM sec_activity WHERE project_id = sim.project_id
                    )
                    -- Only include budget lines with budget (amount_total > 0)
                    AND bl.amount_total > 0
            )
        """ % self._table

        self.env.cr.execute(query)
