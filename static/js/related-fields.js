/* Native related-select enhancement. The server remains authoritative. */
(() => {
  'use strict';
  const selector = 'select[data-related-rules]';
  const original = new WeakMap();
  const rules = new WeakMap();

  function update(select) {
    if (select.disabled || !select.form) return;
    if (!rules.has(select)) {
      try {
        rules.set(select, JSON.parse(select.dataset.relatedRules));
      } catch (error) {
        console.error('Invalid related-field metadata', select.name, error);
        return; // Leave the native control usable; server rejects bad POSTs.
      }
    }
    let selectedInvalid = false;
    for (const option of select.options) {
      if (!original.has(option)) original.set(option, {disabled: option.disabled, hidden: option.hidden});
      const before = original.get(option);
      const allowed = !option.value || rules.get(select).every(rule => {
        const controller = select.form.elements[rule.controller];
        if (!controller) return true; // Never borrow a field from another form/prefix.
        const values = rule.values[option.value] || [];
        return values.includes('*') || values.includes(controller.value || '');
      });
      option.disabled = before.disabled || !allowed;
      option.hidden = before.hidden || !allowed;
      if (option.value && option.value === select.value && option.disabled) selectedInvalid = true;
    }
    if (selectedInvalid) {
      select.value = '';
      select.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }

  function initialize() {
    document.querySelectorAll(selector).forEach(update);
  }

  document.addEventListener('change', event => {
    if (!event.target.form) return;
    document.querySelectorAll(selector).forEach(select => {
      if (select.form !== event.target.form) return;
      const dependencies = rules.get(select);
      if (!dependencies || dependencies.some(rule => rule.controller === event.target.name)) update(select);
    });
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
  // Child-list only: changing hidden/disabled attrs does not trigger a loop.
  new MutationObserver(records => {
    if (records.some(record => record.addedNodes.length)) initialize();
  }).observe(document.documentElement, {subtree: true, childList: true});
})();
