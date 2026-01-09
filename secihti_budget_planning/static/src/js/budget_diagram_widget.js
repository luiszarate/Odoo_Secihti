odoo.define('secihti_budget_planning.BudgetDiagramWidget', function (require) {
"use strict";

var AbstractField = require('web.AbstractField');
var core = require('web.core');
var fieldRegistry = require('web.field_registry');
var rpc = require('web.rpc');

var QWeb = core.qweb;

/**
 * Budget Diagram Widget
 * Displays a visual diagram showing budget lines (left) and planned expenses (right)
 * with visual connections representing allocations
 */
var BudgetDiagramWidget = AbstractField.extend({
    className: 'o_budget_diagram_widget',
    supportedFieldTypes: ['char'],

    /**
     * @override
     */
    init: function () {
        this._super.apply(this, arguments);
        this.diagramData = null;
    },

    /**
     * @override
     */
    start: function () {
        var self = this;
        return this._super.apply(this, arguments).then(function () {
            return self._loadDiagramData();
        });
    },

    /**
     * Load diagram data from the server
     */
    _loadDiagramData: function () {
        var self = this;
        return rpc.query({
            model: 'sec.budget.simulation',
            method: 'get_diagram_data',
            args: [this.res_id],
        }).then(function (data) {
            self.diagramData = data;
            self._renderDiagram();
        });
    },

    /**
     * Render the diagram
     */
    _renderDiagram: function () {
        var self = this;
        if (!this.diagramData) {
            this.$el.html('<p class="text-muted">No data available</p>');
            return;
        }

        var $container = $('<div class="budget_diagram_container">');

        // Left side: Budget lines
        var $leftPanel = $('<div class="budget_diagram_left">');
        $leftPanel.append('<h4>Available Budget (Rubros)</h4>');

        _.each(this.diagramData.budget_lines, function (line) {
            var $lineCard = $(QWeb.render('secihti_budget_planning.BudgetLineCard', {
                line: line,
                currency: self.diagramData.currency_symbol
            }));
            $lineCard.data('line-id', line.id);
            $leftPanel.append($lineCard);
        });

        // Right side: Planned expenses
        var $rightPanel = $('<div class="budget_diagram_right">');
        $rightPanel.append('<h4>Planned Expenses</h4>');

        _.each(this.diagramData.planned_expenses, function (expense) {
            var $expenseCard = $(QWeb.render('secihti_budget_planning.PlannedExpenseCard', {
                expense: expense,
                currency: self.diagramData.currency_symbol
            }));
            $expenseCard.data('expense-id', expense.id);
            $rightPanel.append($expenseCard);
        });

        // SVG canvas for connections
        var $svgContainer = $('<svg class="budget_diagram_connections">');

        $container.append($leftPanel);
        $container.append($svgContainer);
        $container.append($rightPanel);

        this.$el.empty().append($container);

        // Draw connections after DOM is ready
        setTimeout(function () {
            self._drawConnections($svgContainer);
        }, 100);
    },

    /**
     * Draw SVG connections between budget lines and planned expenses
     */
    _drawConnections: function ($svg) {
        var self = this;
        if (!this.diagramData.allocations || this.diagramData.allocations.length === 0) {
            return;
        }

        // Clear existing connections
        $svg.empty();

        // Set SVG dimensions
        var containerWidth = this.$('.budget_diagram_container').width();
        var containerHeight = this.$('.budget_diagram_container').height();
        $svg.attr('width', containerWidth).attr('height', containerHeight);

        // Draw each allocation as a line
        _.each(this.diagramData.allocations, function (allocation) {
            var $sourceLine = self.$('.budget_line_card[data-line-id="' + allocation.budget_line_id + '"]');
            var $targetExpense = self.$('.planned_expense_card[data-expense-id="' + allocation.planned_expense_id + '"]');

            if ($sourceLine.length && $targetExpense.length) {
                var sourcePos = $sourceLine.position();
                var targetPos = $targetExpense.position();

                var sourceHeight = $sourceLine.outerHeight();
                var targetHeight = $targetExpense.outerHeight();

                // Calculate connection points (right side of source, left side of target)
                var x1 = sourcePos.left + $sourceLine.outerWidth();
                var y1 = sourcePos.top + (sourceHeight / 2);
                var x2 = targetPos.left;
                var y2 = targetPos.top + (targetHeight / 2);

                // Create curved path (Bezier curve)
                var midX = (x1 + x2) / 2;
                var path = 'M ' + x1 + ' ' + y1 + ' C ' + midX + ' ' + y1 + ', ' + midX + ' ' + y2 + ', ' + x2 + ' ' + y2;

                // Determine color based on simulated remaining
                var strokeColor = '#e74c3c'; // red by default
                if (allocation.simulated_remaining_status === 'positive') {
                    strokeColor = '#27ae60'; // green
                } else if (allocation.simulated_remaining_status === 'zero') {
                    strokeColor = '#3498db'; // blue
                }

                // Create SVG path element
                var $path = $(document.createElementNS('http://www.w3.org/2000/svg', 'path'));
                $path.attr({
                    'd': path,
                    'stroke': strokeColor,
                    'stroke-width': '3',
                    'fill': 'none',
                    'opacity': '0.7',
                    'class': 'allocation_line'
                });

                // Add title for tooltip
                var $title = $(document.createElementNS('http://www.w3.org/2000/svg', 'title'));
                $title.text(allocation.rubro_name + ' → ' + allocation.expense_name + ': ' +
                           self.diagramData.currency_symbol + ' ' + allocation.amount.toFixed(2));
                $path.append($title);

                $svg.append($path);
            }
        });
    },

    /**
     * @override
     */
    destroy: function () {
        this._super.apply(this, arguments);
    },
});

fieldRegistry.add('budget_diagram', BudgetDiagramWidget);

return BudgetDiagramWidget;

});
