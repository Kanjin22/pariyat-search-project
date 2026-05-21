document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('certificate-search-input');
    const searchButton = document.getElementById('certificate-search-btn');
    const yearFilter = document.getElementById('certificate-year-filter');
    const resultsContainer = document.getElementById('certificate-results-container');
    const resultsSummary = document.getElementById('certificate-results-summary');
    const timestampSpan = document.getElementById('certificate-info-timestamp');
    const countSpan = document.getElementById('certificate-info-count');
    const personCountSpan = document.getElementById('certificate-info-person-count');
    const sourceSpan = document.getElementById('certificate-info-source');
    const clearButton = document.getElementById('certificate-clear-btn');
    const selectedYear = String(window.CERTIFICATE_SELECTED_YEAR ?? '').trim();

    let activeController = null;
    let isSearching = false;

    const toThaiDigits = (value) => String(value ?? '').replace(/\d/g, (digit) => '0123456789'.indexOf(digit) >= 0 ? '๐๑๒๓๔๕๖๗๘๙'[Number(digit)] : digit);

    const escapeHtml = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

    const readJsonResponse = async (response) => {
        const contentType = String(response.headers.get('content-type') || '').toLowerCase();
        const text = await response.text();
        if (!contentType.includes('application/json')) {
            throw new Error(`Unexpected content-type (${contentType || 'unknown'})`);
        }
        try {
            return JSON.parse(text);
        } catch (error) {
            throw new Error('Invalid JSON response');
        }
    };

    const updateInfo = async () => {
        try {
            const response = await fetch('/api/certificates/info');
            const data = await readJsonResponse(response);
            if (!response.ok) {
                throw new Error(data?.error || `HTTP ${response.status}`);
            }
            timestampSpan.textContent = data.timestamp || '-';
            countSpan.textContent = toThaiDigits(data.certificate_count || 0);
            personCountSpan.textContent = toThaiDigits(data.person_count || 0);
            if (sourceSpan) {
                sourceSpan.textContent = data.source || '-';
            }
        } catch (error) {
            console.error('Failed to fetch certificate info:', error);
        }
    };

    const setSummary = (html, hidden = false) => {
        if (!resultsSummary) {
            return;
        }
        resultsSummary.innerHTML = hidden ? '' : html;
        resultsSummary.classList.toggle('hidden', hidden);
    };

    const setSearchState = (searching) => {
        isSearching = Boolean(searching);
        if (searchButton) {
            searchButton.disabled = isSearching;
            searchButton.textContent = isSearching ? 'กำลังค้นหา...' : 'ค้นหา';
        }
        if (clearButton) {
            clearButton.disabled = isSearching;
        }
    };

    const renderResults = (results, query) => {
        if (!query && !(yearFilter?.value || '')) {
            setSummary('', true);
            resultsContainer.innerHTML = '<div class="empty-state">พิมพ์คำค้นเพื่อค้นหาใบประกาศนียบัตรของตนเอง</div>';
            return;
        }
        if (!results.length) {
            setSummary(
                `<strong>ยังไม่พบข้อมูลใบประกาศ</strong>${query ? ` สำหรับคำค้น <span class="summary-highlight">${escapeHtml(query)}</span>` : ''}`
            );
            resultsContainer.innerHTML = `
                <div class="empty-state">
                    ยังไม่พบข้อมูลใบประกาศในชุดข้อมูลที่นำเข้ามาแสดง
                    <div class="empty-state-note">
                        อาจมีข้อมูลเพิ่มเติมจากระบบเก่าที่กำลังทยอยรวมเข้าระบบ หรือยังไม่มีการบันทึกใบประกาศในระบบปัจจุบัน
                    </div>
                </div>
            `;
            return;
        }

        const totalCertificates = results.reduce((sum, person) => sum + Number(person.certificate_count || 0), 0);
        const autoOpenSingle = results.length === 1;
        setSummary(
            `<strong>พบ ${escapeHtml(toThaiDigits(results.length))} คน</strong> และ <strong>${escapeHtml(toThaiDigits(totalCertificates))} ใบประกาศ</strong>`
            + (query ? ` สำหรับคำค้น <span class="summary-highlight">${escapeHtml(query)}</span>` : '')
            + ((yearFilter?.value || '') ? ` ในปี <span class="summary-highlight">${escapeHtml(toThaiDigits(yearFilter.value))}</span>` : '')
        );

        resultsContainer.innerHTML = results.map((person, personIndex) => {
            const certificateRows = (person.certificates || []).map((item) => `
                <tr>
                    <td>${escapeHtml(item.subject || '-')}</td>
                    <td>${escapeHtml(item.level || '-')}</td>
                    <td class="number-cell">${escapeHtml(toThaiDigits(item.year || '-'))}</td>
                    <td><strong>${escapeHtml(item.certificate_no || '-')}</strong></td>
                    <td>${escapeHtml(item.temple || '-')}</td>
                    <td>${escapeHtml(item.school || '-')}</td>
                </tr>
            `).join('');
            const shouldOpen = autoOpenSingle || Number(person.certificate_count || 0) === 1;
            const detailsClass = shouldOpen ? 'details' : 'details hidden';
            const buttonText = shouldOpen ? '[ ^ ซ่อนรายละเอียด ]' : '[ v ดูใบประกาศทั้งหมด ]';

            return `
                <div class="result-group certificate-result-group">
                    <div class="header">
                        <div>
                            <h3>${escapeHtml(person.name || '-')}</h3>
                            <div class="person-subtitle">
                                <span class="status-chip">${toThaiDigits(person.certificate_count || 0)} ใบประกาศ</span>
                            </div>
                        </div>
                        <button class="details-btn" data-target="certificate-details-${personIndex}">${buttonText}</button>
                    </div>
                    <div class="${detailsClass}" id="certificate-details-${personIndex}">
                        <div class="pass-list-table-wrapper">
                            <table class="pass-list-table">
                                <thead>
                                    <tr>
                                        <th>วิชา</th>
                                        <th>ชั้น</th>
                                        <th>ปี</th>
                                        <th>เลข ปกศ.</th>
                                        <th>สังกัดวัด</th>
                                        <th>สำนักเรียน</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${certificateRows}
                                </tbody>
                            </table>
                        </div>
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
            setSearchState(false);
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
        setSearchState(true);
        setSummary('<strong>กำลังค้นหา...</strong>');
        resultsContainer.innerHTML = '<div class="empty-state">กำลังค้นหาข้อมูลใบประกาศนียบัตร</div>';

        try {
            const response = await fetch(`/api/certificates/search?${params.toString()}`, { signal: activeController.signal });
            const payload = await readJsonResponse(response);
            if (!response.ok) {
                throw new Error(payload?.error || `HTTP ${response.status}`);
            }
            const results = Array.isArray(payload) ? payload : (payload?.results || []);
            renderResults(Array.isArray(results) ? results : [], query);
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('Failed to search certificates:', error);
                setSummary('<strong>เกิดข้อผิดพลาดระหว่างค้นหา</strong>');
                resultsContainer.innerHTML = '<div class="empty-state">เกิดข้อผิดพลาดระหว่างค้นหา</div>';
            }
        } finally {
            setSearchState(false);
        }
    };

    let debounceTimer = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(runSearch, 250);
    });
    searchInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            clearTimeout(debounceTimer);
            runSearch();
            return;
        }
        if (event.key === 'Escape') {
            searchInput.value = '';
            renderResults([], '');
        }
    });
    if (yearFilter) {
        yearFilter.addEventListener('change', runSearch);
        if (selectedYear) {
            yearFilter.value = selectedYear;
        }
    }
    if (searchButton) {
        searchButton.addEventListener('click', () => {
            clearTimeout(debounceTimer);
            runSearch();
        });
    }
    if (clearButton) {
        clearButton.addEventListener('click', () => {
            searchInput.value = '';
            if (yearFilter) {
                yearFilter.value = '';
            }
            renderResults([], '');
            searchInput.focus();
        });
    }
    document.querySelectorAll('[data-search-example]').forEach((button) => {
        button.addEventListener('click', () => {
            const exampleText = String(button.getAttribute('data-search-example') || '').trim();
            if (!exampleText) {
                return;
            }
            searchInput.value = exampleText;
            clearTimeout(debounceTimer);
            runSearch();
            searchInput.focus();
            searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
        });
    });

    updateInfo();
    if (selectedYear) {
        runSearch();
    }
});
