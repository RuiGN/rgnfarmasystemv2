(function () {
    function onlyDigits(value) {
        return String(value || '').replace(/\D/g, '');
    }

    function maskCpf(value) {
        return onlyDigits(value)
            .slice(0, 11)
            .replace(/(\d{3})(\d)/, '$1.$2')
            .replace(/(\d{3})(\d)/, '$1.$2')
            .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
    }

    function maskCnpj(value) {
        return onlyDigits(value)
            .slice(0, 14)
            .replace(/(\d{2})(\d)/, '$1.$2')
            .replace(/(\d{3})(\d)/, '$1.$2')
            .replace(/(\d{3})(\d)/, '$1/$2')
            .replace(/(\d{4})(\d{1,2})$/, '$1-$2');
    }

    function maskCpfCnpj(value) {
        return onlyDigits(value).length <= 11 ? maskCpf(value) : maskCnpj(value);
    }

    function maskCep(value) {
        return onlyDigits(value).slice(0, 8).replace(/(\d{5})(\d{1,3})$/, '$1-$2');
    }

    function maskPhone(value) {
        var digits = onlyDigits(value).slice(0, 11);
        if (digits.length <= 10) {
            return digits
                .replace(/(\d{2})(\d)/, '($1) $2')
                .replace(/(\d{4})(\d{1,4})$/, '$1-$2');
        }
        return digits
            .replace(/(\d{2})(\d)/, '($1) $2')
            .replace(/(\d{5})(\d{1,4})$/, '$1-$2');
    }

    function maskNcm(value) {
        return onlyDigits(value)
            .slice(0, 8)
            .replace(/(\d{4})(\d)/, '$1.$2')
            .replace(/(\d{2})(\d{1,2})$/, '$1.$2');
    }

    function maskCfop(value) {
        return onlyDigits(value).slice(0, 4);
    }

    function maskCest(value) {
        return onlyDigits(value)
            .slice(0, 7)
            .replace(/(\d{2})(\d)/, '$1.$2')
            .replace(/(\d{3})(\d{1,2})$/, '$1.$2');
    }

    function maskDate(value) {
        return onlyDigits(value)
            .slice(0, 8)
            .replace(/(\d{2})(\d)/, '$1/$2')
            .replace(/(\d{2})(\d)/, '$1/$2');
    }

    function maskTime(value) {
        return onlyDigits(value)
            .slice(0, 4)
            .replace(/(\d{2})(\d)/, '$1:$2');
    }

    function maskDateTime(value) {
        return onlyDigits(value)
            .slice(0, 12)
            .replace(/(\d{2})(\d)/, '$1/$2')
            .replace(/(\d{2})(\d)/, '$1/$2')
            .replace(/(\d{4})(\d)/, '$1 $2')
            .replace(/(\d{2})(\d)/, '$1:$2');
    }

    function applyMask(input) {
        var mask = input.dataset.mask;
        if (mask === 'cpf') {
            input.value = maskCpf(input.value);
        } else if (mask === 'cnpj') {
            input.value = maskCnpj(input.value);
        } else if (mask === 'cpf-cnpj') {
            input.value = maskCpfCnpj(input.value);
        } else if (mask === 'cep') {
            input.value = maskCep(input.value);
        } else if (mask === 'phone') {
            input.value = maskPhone(input.value);
        } else if (mask === 'ncm') {
            input.value = maskNcm(input.value);
        } else if (mask === 'cfop') {
            input.value = maskCfop(input.value);
        } else if (mask === 'cest') {
            input.value = maskCest(input.value);
        } else if (mask === 'date') {
            input.value = maskDate(input.value);
        } else if (mask === 'time') {
            input.value = maskTime(input.value);
        } else if (mask === 'datetime') {
            input.value = maskDateTime(input.value);
        }
    }

    function validateCpf(value) {
        var digits = onlyDigits(value);
        var firstSum = 0;
        var secondSum = 0;
        var firstDigit;
        var secondDigit;
        var index;

        if (digits.length !== 11 || /^(\d)\1+$/.test(digits)) {
            return false;
        }

        for (index = 0; index < 9; index += 1) {
            firstSum += Number(digits[index]) * (10 - index);
        }
        firstDigit = 11 - (firstSum % 11);
        firstDigit = firstDigit >= 10 ? 0 : firstDigit;

        for (index = 0; index < 10; index += 1) {
            secondSum += Number(digits[index]) * (11 - index);
        }
        secondDigit = 11 - (secondSum % 11);
        secondDigit = secondDigit >= 10 ? 0 : secondDigit;

        return digits.slice(-2) === String(firstDigit) + String(secondDigit);
    }

    function cnpjDigit(digits, weights) {
        var sum = weights.reduce(function (total, weight, index) {
            return total + Number(digits[index]) * weight;
        }, 0);
        var remainder = sum % 11;
        return remainder < 2 ? 0 : 11 - remainder;
    }

    function validateCnpj(value) {
        var digits = onlyDigits(value);
        var firstWeights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
        var secondWeights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
        var firstDigit;
        var secondDigit;

        if (digits.length !== 14 || /^(\d)\1+$/.test(digits)) {
            return false;
        }

        firstDigit = cnpjDigit(digits.slice(0, 12), firstWeights);
        secondDigit = cnpjDigit(digits.slice(0, 13), secondWeights);
        return digits.slice(-2) === String(firstDigit) + String(secondDigit);
    }

    function validateDocument(input) {
        var validation = input.dataset.validate;
        var digits = onlyDigits(input.value);
        var valid = true;

        if (!digits) {
            input.setCustomValidity('');
            return true;
        }

        if (validation === 'cpf') {
            valid = validateCpf(digits);
        } else if (validation === 'cnpj') {
            valid = validateCnpj(digits);
        } else if (validation === 'cpf-cnpj') {
            valid = digits.length === 11 ? validateCpf(digits) : validateCnpj(digits);
        }

        input.setCustomValidity(valid ? '' : 'CPF/CNPJ invalido.');
        return valid;
    }

    function setFieldValue(form, target, value) {
        var field = form.querySelector('[data-address-target="' + target + '"]');
        if (field && !field.value && value) {
            field.value = value;
            field.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    function detectCepGroup(input) {
        var match = input.name.match(/^(.*?)zipcode$/i) || input.name.match(/^(.*?)cep$/i);
        return match && match[1] ? match[1] : '';
    }

    function lookupCep(input) {
        var cep = onlyDigits(input.value);
        var form = input.closest('form');

        if (cep.length !== 8 || !form) {
            return;
        }

        var cepInput = input;
        cepInput.placeholder = 'Consultando CEP...';
        cepInput.setCustomValidity('');
        cepInput.classList.add('cep-loading');

        var group = detectCepGroup(input);
        var suffix = group ? '_' + group : '';

        fetch('/app/cep-lookup/?cep=' + cep)
            .then(function (response) {
                if (!response.ok) {
                    return response.json().then(function (err) {
                        throw new Error(err.error || 'CEP not found');
                    });
                }
                return response.json();
            })
            .then(function (data) {
                cepInput.classList.remove('cep-loading');
                cepInput.placeholder = '00000-000';

                if (data.error) {
                    cepInput.setCustomValidity(data.error);
                    cepInput.reportValidity();
                    return;
                }

                cepInput.setCustomValidity('');
                setFieldValue(form, 'street' + suffix, data.logradouro);
                setFieldValue(form, 'neighborhood' + suffix, data.bairro);
                
                var cityField = form.querySelector('[data-address-target="city' + suffix + '"]');
                if (cityField && cityField.tagName === 'SELECT') {
                    setFieldValue(form, 'city' + suffix, data.city_id);
                    setFieldValue(form, 'state' + suffix, data.state_id);
                    setFieldValue(form, 'country' + suffix, data.country_id);
                } else {
                    setFieldValue(form, 'city' + suffix, data.cidade);
                    setFieldValue(form, 'state' + suffix, data.uf);
                }
            })
            .catch(function (err) {
                cepInput.classList.remove('cep-loading');
                cepInput.placeholder = '00000-000';
                cepInput.setCustomValidity(err.message || 'Não foi possível consultar o CEP.');
                cepInput.reportValidity();
            });
    }

    function bindInput(input) {
        input.addEventListener('input', function () {
            applyMask(input);
            if (input.dataset.validate) {
                validateDocument(input);
            }
        });

        input.addEventListener('blur', function () {
            applyMask(input);
            if (input.dataset.validate) {
                validateDocument(input);
            }
            if (input.dataset.cepSource === 'true') {
                lookupCep(input);
            }
        });
    }

    function initGovernanceParameterForm() {
        var typeControl = document.querySelector('[data-governance-value-type="true"]');
        var rulesControl = document.querySelector('[data-governance-rules="true"]');
        var valueCache = new Map();

        if (!typeControl || !rulesControl) {
            return;
        }

        function controlValue(control) {
            if (control.type === 'checkbox') {
                return control.checked ? 'true' : 'false';
            }
            return control.value;
        }

        function parsedRules() {
            try {
                var rules = JSON.parse(rulesControl.value || '{}');
                return rules && typeof rules === 'object' ? rules : {};
            } catch (error) {
                return {};
            }
        }

        function copyControlAttributes(control, replacement) {
            var typeSpecificAttributes = [
                'type',
                'value',
                'checked',
                'selected',
                'required',
                'role',
                'step',
                'rows',
                'cols',
                'data-governance-rendered-type'
            ];
            Array.prototype.forEach.call(control.attributes, function (attribute) {
                if (typeSpecificAttributes.indexOf(attribute.name) === -1) {
                    replacement.setAttribute(attribute.name, attribute.value);
                }
            });
            replacement.name = control.name;
            replacement.id = control.id;
            replacement.className = control.className
                .split(/\s+/)
                .filter(function (className) {
                    return ['form-control', 'form-select', 'form-check-input'].indexOf(className) === -1;
                })
                .join(' ');
            if (replacement.type === 'checkbox') {
                replacement.classList.add('form-check-input');
            } else if (replacement.tagName === 'SELECT') {
                replacement.classList.add('form-select');
            } else {
                replacement.classList.add('form-control');
            }
        }

        function addOption(select, value, label) {
            var option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            select.appendChild(option);
        }

        function createReplacement(control, role, valueType, rules, cachedValue) {
            var replacement;
            var choices;

            if (valueType === 'boolean' && role === 'current') {
                replacement = document.createElement('input');
                replacement.type = 'checkbox';
                replacement.setAttribute('role', 'switch');
                replacement.checked = cachedValue === 'true' || cachedValue === 'on';
            } else if (valueType === 'boolean') {
                replacement = document.createElement('select');
                addOption(replacement, '', 'Não definido');
                addOption(replacement, 'true', 'Ativado');
                addOption(replacement, 'false', 'Desativado');
            } else if (valueType === 'integer' || valueType === 'days') {
                replacement = document.createElement('input');
                replacement.type = 'number';
                replacement.step = '1';
            } else if (valueType === 'decimal') {
                replacement = document.createElement('input');
                replacement.type = 'number';
                replacement.step = 'any';
            } else if (valueType === 'choice') {
                replacement = document.createElement('select');
                if (role === 'default') {
                    addOption(replacement, '', 'Não definido');
                }
                choices = Array.isArray(rules.choices) ? rules.choices : [];
                choices.forEach(function (choice) {
                    addOption(replacement, String(choice), String(choice));
                });
            } else if (valueType === 'json') {
                replacement = document.createElement('textarea');
            } else {
                replacement = document.createElement('input');
                replacement.type = 'text';
            }

            copyControlAttributes(control, replacement);
            replacement.dataset.governanceRenderedType = valueType;
            replacement.required = role === 'current' && valueType !== 'boolean';
            if (replacement.type !== 'checkbox') {
                replacement.value = cachedValue;
            }
            return replacement;
        }

        function replaceControl(role, valueType, rules) {
            var selector = '[data-governance-value="' + role + '"]';
            var control = document.querySelector(selector);
            var previousType;
            var previousValue;
            var cacheKey;
            var cachedValue;
            var replacement;

            if (!control) {
                return;
            }

            previousType = control.dataset.governanceRenderedType || valueType;
            previousValue = controlValue(control);
            valueCache.set(role + ':' + previousType, previousValue);
            cacheKey = role + ':' + valueType;
            cachedValue = valueCache.has(cacheKey) ? valueCache.get(cacheKey) : '';
            replacement = createReplacement(control, role, valueType, rules, cachedValue);
            control.replaceWith(replacement);
        }

        function renderGovernanceControls() {
            var valueType = typeControl.value;
            var rules = parsedRules();
            replaceControl('current', valueType, rules);
            replaceControl('default', valueType, rules);
        }

        typeControl.addEventListener('change', renderGovernanceControls);
        rulesControl.addEventListener('input', renderGovernanceControls);
        renderGovernanceControls();
    }

    // Keep the server's single ISO field/name. Only its narrow-screen editor
    // changes: a native date calendar plus an explicit HH:MM:SS editor.
    function enhanceDateTime(source) {
        if (source.hidden || source.readOnly || source.disabled || source.dataset.datetimeSplitReady) return;
        var validator = source.cloneNode(false);
        var label = source.labels && source.labels[0];
        var title = source.getAttribute('aria-label') || (label && label.textContent.trim()) || 'Data e hora';
        var group = document.createElement('div');
        group.className = 'datetime-split';
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', title);
        var controls = {};
        ['date', 'time'].forEach(function (part) {
            var wrapper = document.createElement('div');
            var caption = document.createElement('label');
            var control = document.createElement('input');
            control.type = part === 'date' ? 'date' : 'text';
            control.id = source.id + '__' + part;
            control.className = source.className;
            control.dataset.datetimePart = part;
            control.setAttribute('aria-label', title + ' — ' + (part === 'date' ? 'Data' : 'Hora, com segundos'));
            ['aria-describedby', 'aria-invalid'].forEach(function (attribute) {
                if (source.hasAttribute(attribute)) control.setAttribute(attribute, source.getAttribute(attribute));
            });
            caption.htmlFor = control.id;
            caption.className = 'datetime-split__label';
            caption.textContent = part === 'date' ? 'Data' : 'Hora (HH:MM:SS, 24 h)';
            if (part === 'time') {
                control.pattern = '([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,3})?';
                control.placeholder = 'HH:MM:SS';
                control.title = 'Informe horas, minutos e segundos (24 horas), por exemplo 09:51:17.';
                control.autocomplete = 'off';
            }
            wrapper.appendChild(caption);
            wrapper.appendChild(control);
            if (part === 'date' && typeof control.showPicker === 'function') {
                var picker = document.createElement('button');
                picker.type = 'button';
                picker.className = 'btn btn-outline-secondary btn-sm mt-1';
                picker.dataset.datetimePicker = part;
                picker.textContent = 'Abrir calendário';
                picker.setAttribute('aria-label', title + ' — ' + picker.textContent);
                picker.addEventListener('click', function () {
                    control.focus();
                    control.showPicker();
                });
                wrapper.appendChild(picker);
            }
            group.appendChild(wrapper);
            controls[part] = control;
        });
        var parts = source.value.split('T');
        controls.date.value = parts[0] || '';
        controls.time.value = parts[1] && parts[1].length === 5 ? parts[1] + ':00' : parts[1] || '';
        source.dataset.datetimeSplitReady = 'true';
        source.hidden = true;
        // Text keeps invalid/partial edits intact in POSTs that bypass client
        // validation; the unchanged Django field must reject them, not clear them.
        // Unlike type=hidden, changing a text value does not mutate defaultValue.
        source.type = 'text';
        source.readOnly = true;
        source.classList.add('datetime-split-source');
        source.removeAttribute('aria-invalid');
        source.insertAdjacentElement('afterend', group);
        if (label) label.htmlFor = controls.date.id;

        var syncing = false;
        function validateParts() {
            var date = controls.date, time = controls.time;
            var complete = date.value && time.value;
            ['required', 'min', 'max', 'step'].forEach(function (attribute) {
                if (source.hasAttribute(attribute)) validator.setAttribute(attribute, source.getAttribute(attribute));
                else validator.removeAttribute(attribute);
            });
            validator.value = source.value;
            date.min = source.min.split('T')[0];
            date.max = source.max.split('T')[0];
            date.required = source.required || !!time.value || time.validity.badInput;
            time.required = source.required || !!date.value || date.validity.badInput;
            date.disabled = time.disabled = source.disabled;
            group.querySelectorAll('[data-datetime-picker]').forEach(function (picker) { picker.disabled = source.disabled; });
            date.setCustomValidity('');
            time.setCustomValidity('');
            if (complete && !time.validity.patternMismatch && !validator.validity.valid) {
                time.setCustomValidity(validator.validationMessage);
            }
        }
        function hydrate() {
            var value = source.value.split('T');
            controls.date.value = value[0] || '';
            controls.time.value = value[1] && value[1].length === 5 ? value[1] + ':00' : value[1] || '';
            validateParts();
        }
        function sync(event) {
            var date = controls.date, time = controls.time;
            source.value = date.value || time.value || date.validity.badInput
                ? date.value + 'T' + time.value : '';
            validateParts();
            syncing = true;
            source.dispatchEvent(new Event(event.type, { bubbles: true }));
            syncing = false;
        }
        [controls.date, controls.time].forEach(function (control) {
            control.addEventListener('input', sync);
            control.addEventListener('change', sync);
        });
        source.addEventListener('input', function () { if (!syncing) hydrate(); });
        source.addEventListener('change', function () { if (!syncing) hydrate(); });
        new MutationObserver(validateParts).observe(source, {
            attributes: true, attributeFilter: ['disabled', 'required', 'min', 'max', 'step']
        });
        if (source.form) source.form.addEventListener('reset', function () { queueMicrotask(hydrate); });
        validateParts();
    }

    function initResponsiveDateTimes() {
        var narrow = window.matchMedia('(max-width: 575.98px)');
        function scan(root) {
            if (!narrow.matches) return;
            if (root.matches && root.matches('input[type="datetime-local"]')) enhanceDateTime(root);
            root.querySelectorAll('input[type="datetime-local"]').forEach(enhanceDateTime);
        }
        scan(document);
        narrow.addEventListener('change', function () { scan(document); });
        // Inline templates are inert; new rendered rows receive their own IDs.
        new MutationObserver(function (records) {
            records.forEach(function (record) {
                record.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1) scan(node);
                });
            });
        }).observe(document.body, { childList: true, subtree: true });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initResponsiveDateTimes();
        initGovernanceParameterForm();
        document.querySelectorAll('[data-mask]').forEach(bindInput);
        document.querySelectorAll('form').forEach(function (form) {
            form.addEventListener('submit', function (event) {
                var invalidDocument = Array.prototype.some.call(
                    form.querySelectorAll('[data-validate]'),
                    function (input) {
                        return !validateDocument(input);
                    }
                );

                if (invalidDocument) {
                    event.preventDefault();
                    form.reportValidity();
                } else {
                    if (!form.classList.contains('no-loader')) {
                        var overlay = document.getElementById('global-processing-overlay');
                        if (overlay) {
                            overlay.classList.remove('d-none');
                            overlay.classList.add('d-flex');
                            var submitButtons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
                            submitButtons.forEach(function(btn) {
                                // setTimeout is used here so the form still submits correctly
                                setTimeout(function() {
                                    btn.disabled = true;
                                }, 10);
                            });
                        }
                    }
                }
            });
        });
    });
}());
