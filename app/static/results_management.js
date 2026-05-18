document.addEventListener('DOMContentLoaded', async () => {
    const searchInput = document.getElementById('result-search-input');
    const classFilter = document.getElementById('class-filter');
    const yearFilter = document.getElementById('year-filter');
    const resultsContainer = document.getElementById('result-management-container');
    const messageBox = document.getElementById('result-message');
    const statusOptions = Array.isArray(window.RESULT_STATUS_OPTIONS) ? window.RESULT_STATUS_OPTIONS : [];
    const loginUrl = '/staff/login?next=%2Fmanage-results';
    const selectedYear = String(window.SELECTED_YEAR ?? '').trim();

    if (yearFilter) {
        yearFilter.addEventListener('change', () => {
            const year = yearFilter.value;
            window.location.href = `/manage-results?year=${encodeURIComponent(year)}`;
        });
    }

    const loadClasses = async () => {
        try {
            const response = await fetch(`/get_classes?year=${encodeURIComponent(selectedYear)}`);
            if (response.status === 401) {
                window.location.href = loginUrl;
                return;
            }
            const classes = await response.json();
            classes.forEach((className) => {
                const option = document.createElement('option');
                option.value = className;
                option.textContent = className;
                classFilter.appendChild(option);
            });
        } catch (error) {
            console.error('Failed to load classes:', error);
        }
    };
    
    await loadClasses();

    const escapeHtml = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

    const getStatusBadgeClass = (status) => {
        switch (status) {
        case 'สอบได้':
            return 'status-exam-pass';
        case 'สอบตก':
            return 'status-fail';
        case 'สอบซ่อมได้':
            return 'status-remedial-pass';
        case 'สอบซ่อม':
            return 'status-remedial';
        case 'ขาดสอบ':
            return 'status-absent';
        case 'ขาดสิทธิ์':
            return 'status-disqualified';
        default:
            return 'status-empty';
        }
    };

    const showMessage = (message, isError = false) => {
        messageBox.textContent = message;
        messageBox.className = isError ? 'save-message error' : 'save-message success';
    };

    const clearMessage = () => {
        messageBox.textContent = '';
        messageBox.className = 'save-message';
    };

    const renderResults = (results) => {
        if (results.length === 0) {
            resultsContainer.innerHTML = '<p class="empty-state">ไม่พบข้อมูลที่ตรงกับการค้นหา</p>';
            return;
        }

        resultsContainer.innerHTML = results.map((person) => {
            const registrationsHtml = person.registrations.map((registration) => {
                const encodedRegistrationKey = encodeURIComponent(registration.registration_key);
                const optionsHtml = [
                    '<option value="">-- เลือกผลการสอบ --</option>',
                    ...statusOptions.map((status) => {
                        const selected = registration.exam_result_status === status ? 'selected' : '';
                        return `<option value="${escapeHtml(status)}" ${selected}>${escapeHtml(status)}</option>`;
                    })
                ].join('');

                return `
                <li class="result-manage-item">
                    <div class="result-manage-head">
                        <div class="result-manage-title">
                            <span>สมัครสอบ ${escapeHtml(registration.class_name)}</span>
                        </div>
                        ${registration.exam_result_status ? `<span class="saved-badge ${getStatusBadgeClass(registration.exam_result_status)}">${escapeHtml(registration.exam_result_status)}</span>` : ''}
                    </div>
                    <div class="result-manage-actions">
                        <select class="result-status-select" data-registration-key="${encodedRegistrationKey}">
                            ${optionsHtml}
                        </select>
                        <button class="save-result-btn" data-registration-key="${encodedRegistrationKey}">
                            บันทึก
                        </button>
                    </div>
                </li>
            `;
            }).join('');

            return `
            <section class="result-group manage-card">
                <div class="header">
                    <h3>${escapeHtml(person.name)}</h3>
                    <div class="person-subtitle">
                        ${person.exam_name && person.exam_name !== person.name ? `<span>ชื่อในปีสอบ ${escapeHtml(person.exam_name)}</span>` : ''}
                        <span>อายุ/พรรษา ${escapeHtml(person.age_pansa || '-')}</span>
                        <span>สังกัด ${escapeHtml(person.school_name || '-')}</span>
                        <span>กลุ่ม ${escapeHtml(person.group_name || '-')}</span>
                    </div>
                </div>
                <ul class="registrations-list manage-list">
                    ${registrationsHtml}
                </ul>
            </section>
        `;
        }).join('');

        attachSaveHandlers();
    };

    const attachSaveHandlers = () => {
        document.querySelectorAll('.save-result-btn').forEach((button) => {
            button.addEventListener('click', async () => {
                const registrationKey = decodeURIComponent(button.dataset.registrationKey || '');
                const item = button.closest('.result-manage-item');
                const select = item ? item.querySelector('.result-status-select') : null;
                const examResultStatus = select ? select.value : '';

                button.disabled = true;
                clearMessage();

                try {
                    const response = await fetch('/update_exam_result', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            year: selectedYear,
                            registration_key: registrationKey,
                            exam_result_status: examResultStatus
                        })
                    });
                    if (response.status === 401) {
                        window.location.href = loginUrl;
                        return;
                    }
                    const data = await response.json();

                    if (!response.ok || !data.success) {
                        throw new Error(data.message || 'ไม่สามารถบันทึกผลการสอบได้');
                    }

                    showMessage(data.message, false);
                    refreshBadge(button, examResultStatus);
                } catch (error) {
                    showMessage(error.message || 'เกิดข้อผิดพลาดในการบันทึก', true);
                } finally {
                    button.disabled = false;
                }
            });
        });
    };

    const refreshBadge = (button, examResultStatus) => {
        const item = button.closest('.result-manage-item');
        if (!item) {
            return;
        }

        const existingBadge = item.querySelector('.saved-badge');
        if (!examResultStatus) {
            if (existingBadge) {
                existingBadge.remove();
            }
            return;
        }

        if (existingBadge) {
            existingBadge.textContent = examResultStatus;
            existingBadge.className = `saved-badge ${getStatusBadgeClass(examResultStatus)}`;
            return;
        }

        const header = item.querySelector('.result-manage-head');
        if (header) {
            header.insertAdjacentHTML('beforeend', `<span class="saved-badge ${getStatusBadgeClass(examResultStatus)}">${escapeHtml(examResultStatus)}</span>`);
        }
    };

    const searchResults = async (query) => {
        try {
            const selectedClass = classFilter.value;
            let url = '/search_exam_results';
            const params = new URLSearchParams();
            if (selectedYear) {
                params.append('year', selectedYear);
            }
            if (query) {
                params.append('q', query);
            }
            if (selectedClass) {
                params.append('class', selectedClass);
            }
            if (params.toString()) {
                url += '?' + params.toString();
            }
            const response = await fetch(url);
            if (response.status === 401) {
                window.location.href = loginUrl;
                return;
            }
            const results = await response.json();
            renderResults(results);
        } catch (error) {
            resultsContainer.innerHTML = '<p class="empty-state">เกิดข้อผิดพลาดในการค้นหา</p>';
            showMessage('ไม่สามารถโหลดข้อมูลผลการสอบได้', true);
        }
    };

    const performSearch = async () => {
        const query = searchInput.value.trim();
        const selectedClass = classFilter.value;
        clearMessage();

        if (!query && !selectedClass) {
            resultsContainer.innerHTML = '<p class="empty-state">พิมพ์ชื่อหรือเลือกชั้นเพื่อค้นหารายชื่อ</p>';
            return;
        }

        if (query && query.length < 2 && !selectedClass) {
            resultsContainer.innerHTML = '<p class="empty-state">พิมพ์อย่างน้อย 2 ตัวอักษรเพื่อค้นหารายชื่อ</p>';
            return;
        }

        await searchResults(query);
    };

    searchInput.addEventListener('input', performSearch);
    classFilter.addEventListener('change', performSearch);

    resultsContainer.innerHTML = '<p class="empty-state">พิมพ์ชื่อหรือเลือกชั้นเพื่อค้นหารายชื่อ</p>';
});
