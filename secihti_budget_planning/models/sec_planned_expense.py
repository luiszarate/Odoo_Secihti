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
        # This could open a wizard for quick allocation
        # For now, we'll just return the allocations view
        return self.action_view_allocations()
