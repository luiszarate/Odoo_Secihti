# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SecPlannedExpense(models.Model):
    _name = 'sec.planned.expense'
    _description = 'Planned Expense (Simulation)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    name = fields.Char(
        string='Description',
        required=True,
        help='Description of the planned expense'
    )

    simulation_id = fields.Many2one(
        'sec.budget.simulation',
        string='Simulation',
        required=True,
        ondelete='cascade',
        index=True
    )

    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Used to order planned expenses'
    )

    amount = fields.Monetary(
        string='Total Cost',
        required=True,
        currency_field='currency_id',
        help='Total cost of this planned expense'
    )

    allocation_ids = fields.One2many(
        'sec.budget.allocation',
        'planned_expense_id',
        string='Budget Allocations'
    )

    allocated_amount = fields.Monetary(
        string='Allocated Amount',
        compute='_compute_allocation_status',
        store=True,
        currency_field='currency_id',
        help='Total amount allocated from budget lines'
    )

    remaining_amount = fields.Monetary(
        string='Remaining to Allocate',
        compute='_compute_allocation_status',
        store=True,
        currency_field='currency_id',
        help='Amount still needing allocation'
    )

    allocation_percentage = fields.Float(
        string='Allocation %',
        compute='_compute_allocation_status',
        store=True,
        help='Percentage of total cost that has been allocated'
    )

    is_fully_allocated = fields.Boolean(
        string='Fully Allocated',
        compute='_compute_allocation_status',
        store=True,
        help='True if the entire amount has been allocated'
    )

    allocation_status = fields.Selection([
        ('not_allocated', 'Not Allocated'),
        ('partially_allocated', 'Partially Allocated'),
        ('fully_allocated', 'Fully Allocated'),
        ('over_allocated', 'Over Allocated')
    ], string='Status', compute='_compute_allocation_status', store=True)

    allocation_status_color = fields.Char(
        string='Status Color',
        compute='_compute_allocation_status',
        help='Color for status badge'
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='simulation_id.currency_id',
        string='Currency',
        readonly=True,
        store=True
    )

    project_id = fields.Many2one(
        'sec.project',
        related='simulation_id.project_id',
        string='Project',
        readonly=True,
        store=True
    )

    notes = fields.Text(
        string='Notes',
        help='Additional notes about this planned expense'
    )

    color = fields.Integer(
        string='Color Index',
        default=0,
        help='Color for kanban view (like post-it colors)'
    )

    # UX Enhancement fields
    can_auto_complete = fields.Boolean(
        string='Can Auto-Complete',
        compute='_compute_can_auto_complete',
        help='True if there are budget lines with enough remaining to complete this expense'
    )

    available_budget_lines_count = fields.Integer(
        string='Available Budget Lines',
        compute='_compute_can_auto_complete',
        help='Number of budget lines with sufficient budget to complete this expense'
    )

    @api.depends('amount', 'allocation_ids.amount', 'simulation_id.project_id')
    def _compute_can_auto_complete(self):
        """Check if there are budget lines that can complete this expense"""
        for expense in self:
            if expense.remaining_amount <= 0:
                expense.can_auto_complete = False
                expense.available_budget_lines_count = 0
                continue

            # Get available budget lines from the same project
            available_lines = self._get_available_budget_lines()

            # Count lines with enough remaining budget
            sufficient_lines = available_lines.filtered(
                lambda line: line.rem_total >= expense.remaining_amount
            )

            expense.available_budget_lines_count = len(sufficient_lines)
            expense.can_auto_complete = len(sufficient_lines) > 0

    def _get_available_budget_lines(self):
        """Get budget lines from the same project that have remaining budget"""
        self.ensure_one()

        if not self.project_id:
            return self.env['sec.activity.budget.line']

        # Get all activities from the same project
        activities = self.env['sec.activity'].search([
            ('stage_id.project_id', '=', self.project_id.id)
        ])

        # Get all budget lines from these activities with remaining budget
        budget_lines = self.env['sec.activity.budget.line'].search([
            ('activity_id', 'in', activities.ids),
            ('rem_total', '>', 0)
        ])

        # Filter out lines that would be over-allocated in this simulation
        available_lines = budget_lines.filtered(lambda line: self._get_simulated_remaining(line) > 0)

        return available_lines

    def _get_simulated_remaining(self, budget_line):
        """Calculate simulated remaining for a budget line in this simulation"""
        self.ensure_one()

        # Get all allocations for this budget line in this simulation
        allocations = self.env['sec.budget.allocation'].search([
            ('simulation_id', '=', self.simulation_id.id),
            ('budget_line_id', '=', budget_line.id)
        ])

        total_allocated = sum(allocations.mapped('amount'))
        return budget_line.rem_total - total_allocated

    @api.depends('amount', 'allocation_ids.amount')
    def _compute_allocation_status(self):
        for expense in self:
            allocated = sum(expense.allocation_ids.mapped('amount'))
            remaining = expense.amount - allocated

            expense.allocated_amount = allocated
            expense.remaining_amount = remaining

            if expense.amount > 0:
                expense.allocation_percentage = (allocated / expense.amount) * 100
            else:
                expense.allocation_percentage = 0

            # Determine allocation status
            if allocated == 0:
                status = 'not_allocated'
                color = 'danger'  # Red
            elif allocated < expense.amount:
                status = 'partially_allocated'
                color = 'warning'  # Yellow/Orange
            elif allocated == expense.amount:
                status = 'fully_allocated'
                color = 'success'  # Green
            else:  # allocated > expense.amount
                status = 'over_allocated'
                color = 'danger'  # Red

            expense.allocation_status = status
            expense.allocation_status_color = color
            expense.is_fully_allocated = (allocated >= expense.amount)

    @api.constrains('amount')
    def _check_amount_positive(self):
        for expense in self:
            if expense.amount <= 0:
                raise ValidationError(_('The planned expense amount must be greater than zero.'))

    def action_view_allocations(self):
        """Open a view to manage allocations for this expense"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Budget Allocations - %s') % self.name,
            'res_model': 'sec.budget.allocation',
            'view_mode': 'tree,form',
            'domain': [('planned_expense_id', '=', self.id)],
            'context': {
                'default_planned_expense_id': self.id,
                'default_simulation_id': self.simulation_id.id,
            },
            'target': 'current',
        }

    def action_quick_allocate(self):
        """Quick allocation wizard - allocates from available budget lines"""
        self.ensure_one()

        # Check if there are available budget lines
        available_lines = self._get_available_budget_lines()

        if not available_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Budget Available'),
                    'message': _('There are no budget lines with remaining budget available for this project. Please check your project activities and budget lines.'),
                    'type': 'warning',
                    'sticky': True,
                }
            }

        # Return wizard action
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quick Allocate - %s') % self.name,
            'res_model': 'sec.budget.allocation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_planned_expense_id': self.id,
                'default_simulation_id': self.simulation_id.id,
            },
        }

    def action_auto_complete_allocation(self):
        """Automatically complete allocation to 100% from best available budget line"""
        self.ensure_one()

        if self.remaining_amount <= 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Already Completed'),
                    'message': _('This expense is already fully or over-allocated.'),
                    'type': 'warning',
                }
            }

        # Get budget lines with sufficient remaining
        available_lines = self._get_available_budget_lines()
        sufficient_lines = available_lines.filtered(
            lambda line: self._get_simulated_remaining(line) >= self.remaining_amount
        )

        if not sufficient_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Insufficient Budget'),
                    'message': _('No single budget line has enough remaining budget to complete this expense. Use Quick Allocate for multiple allocations.'),
                    'type': 'warning',
                }
            }

        # Use the budget line with the most remaining (to preserve smaller budgets)
        best_line = sufficient_lines.sorted(lambda line: self._get_simulated_remaining(line), reverse=True)[0]

        # Create the allocation
        self.env['sec.budget.allocation'].create({
            'simulation_id': self.simulation_id.id,
            'planned_expense_id': self.id,
            'activity_id': best_line.activity_id.id,
            'budget_line_id': best_line.id,
            'amount': self.remaining_amount,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success!'),
                'message': _('Allocated %s from %s to complete this expense.') % (
                    self.remaining_amount,
                    best_line.rubro_id.name
                ),
                'type': 'success',
                'sticky': False,
            }
        }
