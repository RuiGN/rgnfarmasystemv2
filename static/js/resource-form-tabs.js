(function () {
    document.addEventListener('DOMContentLoaded', function () {
        const Tab = window.bootstrap && window.bootstrap.Tab;
        if (!Tab) return;

        document.querySelectorAll('[data-ui="resource-form-tabs"]').forEach(function (root) {
            const form = root.closest('form');
            const buttons = Array.from(root.querySelectorAll('[role="tab"]'));
            if (!form || !buttons.length) return;
            buttons.forEach(function (button) { Tab.getOrCreateInstance(button); });
            root.dataset.tabsReady = 'true';
            form.noValidate = true;
            let invalidBatch = false;

            function reveal(control, report) {
                const pane = control.closest('[role="tabpanel"]');
                if (!pane || !root.contains(pane)) return;
                const button = buttons.find(function (item) {
                    return item.getAttribute('aria-controls') === pane.id;
                });
                if (!button) return;
                function focus() {
                    if (!pane.classList.contains('active')) return;
                    control.focus();
                    if (report) control.reportValidity();
                }
                if (pane.classList.contains('active')) {
                    focus();
                } else {
                    button.addEventListener('shown.bs.tab', focus, { once: true });
                    Tab.getOrCreateInstance(button).show();
                }
            }

            root.querySelector('[role="tablist"]').addEventListener('keydown', function (event) {
                const index = buttons.indexOf(event.target);
                if (index < 0) return;
                let target;
                if (event.key === 'Home') target = 0;
                else if (event.key === 'End') target = buttons.length - 1;
                else if (event.key === 'ArrowRight') target = (index + 1) % buttons.length;
                else if (event.key === 'ArrowLeft') target = (index + buttons.length - 1) % buttons.length;
                else return;
                event.preventDefault();
                event.stopPropagation();
                Tab.getOrCreateInstance(buttons[target]).show();
                buttons[target].focus();
            });

            form.addEventListener('invalid', function (event) {
                if (invalidBatch) return;
                invalidBatch = true;
                reveal(event.target, false);
                queueMicrotask(function () { invalidBatch = false; });
            }, true);

            form.addEventListener('submit', function (event) {
                // Separate server actions preserve the principal editor, even
                // when its required fields are intentionally still incomplete.
                if (event.submitter && event.submitter.formNoValidate) return;
                if (form.checkValidity()) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                const control = form.querySelector('input:invalid, select:invalid, textarea:invalid');
                if (control) reveal(control, true);
            }, true);

            const firstError = root.querySelector('.tab-pane.active [aria-invalid="true"]:not([disabled])');
            if (firstError) firstError.focus();
        });
    });
}());
