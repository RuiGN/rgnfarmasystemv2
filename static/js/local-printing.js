(() => {
    'use strict';

    const statusNode = document.querySelector('[data-label-print-status]');
    if (!statusNode) return;

    function showStatus(message, tone) {
        statusNode.className = `alert alert-${tone} mb-4`;
        statusNode.textContent = message;
    }

    document.querySelectorAll('[data-label-print-button]').forEach(button => {
        const form = button.closest('[data-label-print-form]');
        const csrfToken = form?.querySelector('[name="csrfmiddlewaretoken"]')?.value;
        if (!csrfToken) return;

        button.addEventListener('click', async () => {
            if (button.disabled) return;
            if (!window.confirm('Enviar esta etiqueta imediatamente para a impressora?')) return;
            button.disabled = true;
            showStatus('Enviando etiqueta pela VPN…', 'info');
            try {
                const response = await fetch(button.dataset.labelPrintUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || 'Não foi possível imprimir a etiqueta.');
                }
                showStatus(data.detail || 'Etiqueta enviada à impressora.', 'success');
            } catch (error) {
                showStatus(error.message || 'Não foi possível imprimir a etiqueta.', 'danger');
            } finally {
                button.disabled = false;
            }
        });
    });
})();
