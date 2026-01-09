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

    # Dummy field for diagram widget
    diagram_view = fields.Char(
        string='Diagram',
        compute='_compute_diagram_view',
        help='Visual diagram of budget allocations'
    )

    @api.depends('planned_expense_ids', 'planned_expense_ids.allocation_ids')
    def _compute_diagram_view(self):
        for simulation in self:
            simulation.diagram_view = 'diagram'

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

    def get_diagram_data(self):
        """
        Get data for the visual diagram widget
        Returns budget lines, planned expenses, and allocations
        """
        self.ensure_one()

        # Get all budget lines for this project (optionally filtered by stage)
        domain = [('project_id', '=', self.project_id.id)]
        if self.stage_id:
            domain.append(('stage_id', '=', self.stage_id.id))

        budget_lines = self.env['sec.activity.budget.line'].search(
            domain,
            order='activity_id, rubro_id'
        )

        # Calculate simulated allocated amounts for each budget line
        budget_line_data = []
        for line in budget_lines:
            # Get all allocations from this budget line in this simulation
            allocations = self.env['sec.budget.allocation'].search([
                ('simulation_id', '=', self.id),
                ('budget_line_id', '=', line.id)
            ])
            simulated_allocated = sum(allocations.mapped('amount'))

            # Color mapping based on remaining budget
            color = '#4caf50'  # green
            if line.rem_total < 0:
                color = '#f44336'  # red
            elif line.rem_total == 0:
                color = '#2196f3'  # blue

            budget_line_data.append({
                'id': line.id,
                'activity_id': line.activity_id.id,
                'activity_name': line.activity_id.name or line.activity_id.code,
                'rubro_id': line.rubro_id.id,
                'rubro_name': line.rubro_id.name,
                'amount_total': line.amount_total,
                'rem_total': line.rem_total,
                'simulated_allocated': simulated_allocated,
                'color': color,
            })

        # Get planned expenses
        expense_data = []
        for expense in self.planned_expense_ids:
            # Determine status class for badge
            if expense.allocation_status == 'fully_allocated':
                status_class = 'success'
            elif expense.allocation_status == 'partially_allocated':
                status_class = 'warning'
            else:
                status_class = 'danger'

            # Color mapping (can be customized per expense)
            color_map = {
                0: '#ffeb3b',  # yellow
                1: '#4caf50',  # green
                2: '#2196f3',  # blue
                3: '#ff9800',  # orange
                4: '#e91e63',  # pink
                5: '#9c27b0',  # purple
                6: '#00bcd4',  # cyan
                7: '#8bc34a',  # light green
                8: '#ff5722',  # deep orange
                9: '#607d8b',  # blue grey
            }
            expense_color = color_map.get(expense.color % 10, '#ffeb3b')

            expense_data.append({
                'id': expense.id,
                'name': expense.name,
                'amount': expense.amount,
                'allocated_amount': expense.allocated_amount,
                'remaining_amount': expense.remaining_amount,
                'allocation_percentage': expense.allocation_percentage,
                'allocation_status': expense.allocation_status,
                'allocation_status_class': status_class,
                'color': expense_color,
            })

        # Get allocations
        allocation_data = []
        for allocation in self.env['sec.budget.allocation'].search([
            ('simulation_id', '=', self.id)
        ]):
            allocation_data.append({
                'id': allocation.id,
                'budget_line_id': allocation.budget_line_id.id,
                'planned_expense_id': allocation.planned_expense_id.id,
                'amount': allocation.amount,
                'rubro_name': allocation.rubro_id.name,
                'expense_name': allocation.planned_expense_id.name,
                'simulated_remaining': allocation.simulated_remaining,
                'simulated_remaining_status': allocation.simulated_remaining_status,
            })

        return {
            'budget_lines': budget_line_data,
            'planned_expenses': expense_data,
            'allocations': allocation_data,
            'currency_symbol': self.currency_id.symbol or '$',
        }
