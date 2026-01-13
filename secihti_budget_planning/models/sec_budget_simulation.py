# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SecBudgetSimulation(models.Model):
    _name = 'sec.budget.simulation'
    _description = 'Budget Planning Simulation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Simulation Name',
        required=True,
        default=lambda self: _('New Simulation')
    )

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today
    )

    project_id = fields.Many2one(
        'sec.project',
        string='Project',
        required=True,
        ondelete='cascade'
    )

    stage_id = fields.Many2one(
        'sec.stage',
        string='Stage',
        domain="[('project_id', '=', project_id)]",
        help='Optional: Filter by stage'
    )

    description = fields.Text(
        string='Description',
        help='Description of this simulation scenario'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived')
    ], string='Status', default='draft', required=True, tracking=True)

    planned_expense_ids = fields.One2many(
        'sec.planned.expense',
        'simulation_id',
        string='Planned Expenses'
    )

    total_planned_amount = fields.Monetary(
        string='Total Planned',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    total_allocated_amount = fields.Monetary(
        string='Total Allocated',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    total_unallocated_amount = fields.Monetary(
        string='Total Unallocated',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='project_id.currency_id',
        string='Currency',
        readonly=True
    )

    notes = fields.Html(
        string='Notes',
        help='Additional notes about this simulation'
    )

    result_line_ids = fields.One2many(
        'sec.budget.simulation.result.line',
        'simulation_id',
        string='Simulation Results by Budget Line',
        help='Shows how each budget line (rubro) will look after the simulation'
    )

    @api.depends('planned_expense_ids.amount', 'planned_expense_ids.allocated_amount')
    def _compute_totals(self):
        for simulation in self:
            total_planned = sum(simulation.planned_expense_ids.mapped('amount'))
            total_allocated = sum(simulation.planned_expense_ids.mapped('allocated_amount'))
            simulation.total_planned_amount = total_planned
            simulation.total_allocated_amount = total_allocated
            simulation.total_unallocated_amount = total_planned - total_allocated

    def action_activate(self):
        self.ensure_one()
        self.write({'state': 'active'})
        return True

    def action_archive(self):
        self.ensure_one()
        self.write({'state': 'archived'})
        return True

    def action_set_draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})
        return True

    def action_view_graphical_planning(self):
        """Open the graphical planning view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Budget Planning - %s') % self.name,
            'res_model': 'sec.budget.simulation',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'context': {'form_view_ref': 'secihti_budget_planning.view_sec_budget_simulation_planning_form'}
        }

    def _update_result_lines(self):
        """Update result lines based on current allocations"""
        self.ensure_one()

        # Delete existing result lines
        self.result_line_ids.unlink()

        # Group allocations by budget_line_id
        allocations_by_line = {}
        for allocation in self.planned_expense_ids.mapped('allocation_ids'):
            line_id = allocation.budget_line_id.id
            if line_id not in allocations_by_line:
                allocations_by_line[line_id] = {
                    'budget_line': allocation.budget_line_id,
                    'total_allocated': 0
                }
            allocations_by_line[line_id]['total_allocated'] += allocation.amount

        # Create result lines
        ResultLine = self.env['sec.budget.simulation.result.line']
        for line_id, data in allocations_by_line.items():
            budget_line = data['budget_line']
            ResultLine.create({
                'simulation_id': self.id,
                'budget_line_id': budget_line.id,
                'total_allocated': data['total_allocated'],
            })


class SecBudgetSimulationResultLine(models.Model):
    _name = 'sec.budget.simulation.result.line'
    _description = 'Budget Simulation Result Line'
    _order = 'activity_id, rubro_id'

    simulation_id = fields.Many2one(
        'sec.budget.simulation',
        string='Simulation',
        required=True,
        ondelete='cascade',
        index=True
    )

    budget_line_id = fields.Many2one(
        'sec.activity.budget.line',
        string='Budget Line',
        required=True,
        ondelete='cascade'
    )

    activity_id = fields.Many2one(
        'sec.activity',
        related='budget_line_id.activity_id',
        string='Activity',
        readonly=True,
        store=True
    )

    rubro_id = fields.Many2one(
        'sec.rubro',
        related='budget_line_id.rubro_id',
        string='Rubro',
        readonly=True,
        store=True
    )

    # Budget line amounts
    line_amount_total = fields.Monetary(
        string='Total Budget',
        related='budget_line_id.amount_total',
        readonly=True,
        currency_field='currency_id'
    )

    line_rem_total = fields.Monetary(
        string='Real Remaining',
        related='budget_line_id.rem_total',
        readonly=True,
        currency_field='currency_id',
        help='Real remaining budget before simulation'
    )

    # Simulation amounts
    total_allocated = fields.Monetary(
        string='Allocated in Simulation',
        currency_field='currency_id',
        help='Total amount allocated from this budget line in this simulation'
    )

    simulated_remaining = fields.Monetary(
        string='Simulated Remaining',
        compute='_compute_simulated_remaining',
        store=True,
        currency_field='currency_id',
        help='Remaining budget after applying this simulation'
    )

    simulated_remaining_status = fields.Selection([
        ('positive', 'Positive'),
        ('zero', 'Zero'),
        ('negative', 'Negative')
    ], string='Status', compute='_compute_simulated_remaining', store=True)

    currency_id = fields.Many2one(
        'res.currency',
        related='simulation_id.currency_id',
        string='Currency',
        readonly=True,
        store=True
    )

    @api.depends('line_rem_total', 'total_allocated')
    def _compute_simulated_remaining(self):
        for line in self:
            simulated_rem = (line.line_rem_total or 0) - (line.total_allocated or 0)
            line.simulated_remaining = simulated_rem

            if simulated_rem > 0:
                line.simulated_remaining_status = 'positive'
            elif simulated_rem == 0:
                line.simulated_remaining_status = 'zero'
            else:
                line.simulated_remaining_status = 'negative'
