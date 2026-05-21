document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('certificate-search-input');
    const yearFilter = document.getElementById('certificate-year-filter');
    const resultsContainer = document.getElementById('certificate-results-container');
    const timestampSpan = document.getElementById('certificate-info-timestamp');
    const countSpan = document.getElementById('certificate-info-count');
    const personCountSpan = document.getElementById('certificate-info-person-count');
    const selectedYear = String(window.CERTIFICATE_SELECTED_YEAR ?? '').trim();

    let activeController = null;

    const toThaiDigits = (value) => String(value ?? '').replace(/\d/g, (digit) => '0123456789'.indexOf(digit) >= 0 ? '๐๑๒๓๔๕๖๗๘๙'[Number(digit)] : digit);

    const escapeHtml = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

    const updateInfo = async () => {
        try {
            const response = await fetch('/api/certificates/info');
            const data = await response.json();
            timestampSpan.textContent = data.timestamp || '-';
            countSpan.textContent = toThaiDigits(data.certificate_count || 0);
            personCountSpan.textContent = toThaiDigits(data.person_count || 0);
        } catch (error) {
            console.error('Failed to fetch certificate info:', error);
        }
    };

    const renderResults = (results, query) => {
        if (!query && !(yearFilter?.value || '')) {
            resultsContainer.innerHTML = '<div class="empty-state">พิมพ์คำค้นเพื่อค้นหาใบประกาศนียบัตรของตนเอง</div>';
            return;
        }
        if (!results.length) {
            resultsContainer.innerHTML = '<div class="empty-state">ไม่พบข้อมูลที่ตรงกับการค้นหา</div>';
            return;
        }

        resultsContainer.innerHTML = results.map((person, personIndex) => {
            const certificateItems = (person.certificates || []).map((item) => `
                <li class="certificate-item">
                    <div class="certificate-grid">
                        <div><span class="certificate-label">เลข ปกศ.</span><strong>${escapeHtml(item.certificate_no || '-')}</strong></div>
                        <div><span class="certificate-label">วิชา</span>${escapeHtml(item.subject || '-')}</div>
                        <div><span class="certificate-label">ชั้น</span>${escapeHtml(item.level || '-')}</div>
                        <div><span class="certificate-label">ปี</span>${escapeHtml(toThaiDigits(item.year || '-'))}</div>
                        <div><span class="certificate-label">จังหวัด</span>${escapeHtml(item.province || '-')}</div>
                        <div><span class="certificate-label">สำนักเรียน</span>${escapeHtml(item.school || '-')}</div>
                    </div>
                </li>
            `).join('');

            return `
                <div class="result-group certificate-result-group">
                    <div class="header">
                        <div>
                            <h3>${escapeHtml(person.name || '-')}</h3>
                            <div class="person-subtitle">
                                <span class="status-chip">${toThaiDigits(person.certificate_count || 0)} ใบประกาศ</span>
                            </div>
                        </div>
                        <button class="details-btn" data-target="certificate-details-${personIndex}">[ v ดูใบประกาศทั้งหมด ]</button>
                    </div>
                    <div class="details hidden" id="certificate-details-${personIndex}">
                        <ul class="registrations-list certificate-list">
                            ${certificateItems}
                        </ul>
                    </div>
                </div>
            `;
        }).join('');

        document.querySelectorAll('.details-btn').forEach((button) => {
            button.addEventListener('click', () => {
                const targetElement = document.getElementById(button.dataset.target);
                if (!targetElement) {
                    return;
                }
                const isVisible = !targetElement.classList.contains('hidden');
                targetElement.classList.toggle('hidden');
                button.textContent = isVisible ? '[ v ดูใบประกาศทั้งหมด ]' : '[ ^ ซ่อนรายละเอียด ]';
            });
        });
    };

    const runSearch = async () => {
        const query = searchInput.value.trim();
        const year = yearFilter?.value || '';
        if (query.length < 2 && !year) {
            renderResults([], '');
            return;
        }

        const params = new URLSearchParams();
        if (query) {
            params.set('q', query);
        }
        if (year) {
            params.set('year', year);
        }

        if (activeController) {
            activeController.abort();
        }
        activeController = new AbortController();

        try {
            const response = await fetch(`/api/certificates/search?${params.toString()}`, { signal: activeController.signal });
            const results = await response.json();
            renderResults(results, query);
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('Failed to search certificates:', error);
                resultsContainer.innerHTML = '<div class="empty-state">เกิดข้อผิดพลาดระหว่างค้นหา</div>';
            }
        }
    };

    let debounceTimer = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(runSearch, 250);
    });
    if (yearFilter) {
        yearFilter.addEventListener('change', runSearch);
        if (selectedYear) {
            yearFilter.value = selectedYear;
        }
    }

    updateInfo();
    if (selectedYear) {
        runSearch();
    }
});
