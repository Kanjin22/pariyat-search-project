document.addEventListener('DOMContentLoaded', () => {
    const timestampSpan = document.getElementById('info-timestamp');
    const countSpan = document.getElementById('info-count');
    const searchInput = document.getElementById('search-input');
    const resultsContainer = document.getElementById('results-container');
    const yearFilter = document.getElementById('year-filter');

    const selectedYear = String(window.SELECTED_YEAR ?? '').trim();
    const currentMode = String(window.CURRENT_MODE ?? '').trim();

    if (yearFilter) {
        yearFilter.addEventListener('change', () => {
            const year = yearFilter.value;
            const params = new URLSearchParams();
            if (year) {
                params.set('year', year);
            }
            if (currentMode) {
                params.set('mode', currentMode);
            }
            window.location.href = `/?${params.toString()}`;
        });
    }

    const fetchInitialInfo = async () => {
        try {
            const params = new URLSearchParams();
            if (selectedYear) {
                params.set('year', selectedYear);
            }
            if (currentMode) {
                params.set('mode', currentMode);
            }
            const url = params.toString() ? `/get_data_info?${params.toString()}` : '/get_data_info';
            const response = await fetch(url);
            const data = await response.json();
            timestampSpan.textContent = data.timestamp;
            countSpan.textContent = data.count;
        } catch (error) {
            timestampSpan.textContent = "เกิดข้อผิดพลาด";
            console.error("Failed to fetch initial info:", error);
        }
    };

    searchInput.addEventListener('input', async (e) => {
        const query = e.target.value.trim();
        if (query.length < 2) {
            resultsContainer.innerHTML = '';
            return;
        }
        const params = new URLSearchParams();
        params.set('q', query);
        if (selectedYear) {
            params.set('year', selectedYear);
        }
        if (currentMode) {
            params.set('mode', currentMode);
        }
        const response = await fetch(`/search?${params.toString()}`);
        const results = await response.json();
        renderResults(results);
    });

    const renderResults = (results) => {
        if (results.length === 0) {
            resultsContainer.innerHTML = '<p>ไม่พบข้อมูลที่ตรงกับการค้นหา</p>';
            return;
        }

        resultsContainer.innerHTML = results.map((person, personIndex) => {
            const regListHtml = person.registrations.map((reg, regIndex) => {

                const isPaliSubject = reg.class_name.includes('บ.ศ.') || reg.class_name.includes('ป.');

                let nugdhamLine = '';
                let paliLine = '';

                const nugdhamMark = reg.cert_nugdham_current_ok ? ' ✓' : '';
                const paliMark = reg.cert_pali_current_ok ? ' ✓' : '';

                if (isPaliSubject) {
                    nugdhamLine = reg.cert_nugdham ? ` - ${reg.cert_nugdham}${nugdhamMark}<br>` : '';
                    paliLine = reg.cert_pali ? ` - ${reg.cert_pali}${paliMark}<br>` : '';
                } else {
                    nugdhamLine = reg.cert_nugdham ? ` - ${reg.cert_nugdham}${nugdhamMark}<br>` : '';
                }

                const hasCertToShow = nugdhamLine || paliLine;

                return `
                <li class="reg-item">
                    <div class="reg-item-visible">
                        <span class="reg-info">
                            - <strong>(ลำดับที่ ${reg.sequence})</strong> สมัครสอบ ${reg.class_name} (<span class="status-text">${reg.reg_status}</span>)
                        </span>
                        ${hasCertToShow ? `<button class="details-btn-reg" data-target="details-reg-${personIndex}-${regIndex}">[ v ดูรายละเอียดเพิ่มเติม ]</button>` : ''}
                    </div>
                    
                    ${hasCertToShow ? `
                    <div class="details-reg hidden" id="details-reg-${personIndex}-${regIndex}">
                        <strong>เลขประกาศนียบัตรเดิม:</strong><br>
                        <div class="cert-details">
                            ${nugdhamLine}
                            ${paliLine}
                        </div>
                    </div>
                    ` : ''}
                </li>
            `;
            }).join('');

            const telLine = person.tel_masked_text ? `- เบอร์โทรศัพท์: <a class="phone-link" href="tel:${person.tel_cleaned}">${person.tel_masked_text}</a><br>` : '';
            let idStatusClass = '';
            if (person.id_status_text.includes('✅')) { idStatusClass = 'status-valid'; }
            else if (person.id_status_text.includes('❌')) { idStatusClass = 'status-invalid'; }

            return `
            <div class="result-group">
                <div class="header">
                    <h3>${person.name}</h3>
                    <button class="details-btn" data-target="details-${personIndex}">[ v ดูรายละเอียดเพิ่มเติม ]</button>
                </div>
                <div class="details hidden" id="details-${personIndex}">
                    <strong>ข้อมูลส่วนตัว:</strong><br>
                    <div class="details-content">
                        - อายุ: ${person.age_pansa.split('/')[0] || '-'}<br>
                        ${person.age_pansa.includes('/') ? `- พรรษา: ${person.age_pansa.split('/')[1]}<br>` : ''}
                        - สังกัด: ${person.school_name || '-'}<br>
                        - กลุ่ม: ${person.group_name || '-'}<br>
                        - เลข ปชช.: <span class="${idStatusClass}">${person.id_status_text}</span><br>
                        ${telLine}
                    </div>
                </div>
                <ul class="registrations-list">
                    ${regListHtml}
                </ul>
            </div>
        `;
        }).join('');

        document.querySelectorAll('.details-btn, .details-btn-reg').forEach(button => {
            button.addEventListener('click', () => {
                const targetId = button.dataset.target;
                const targetElement = document.getElementById(targetId);
                const isVisible = !targetElement.classList.contains('hidden');

                targetElement.classList.toggle('hidden');
                if (button.classList.contains('details-btn')) {
                    button.textContent = isVisible ? '[ v ดูรายละเอียดเพิ่มเติม ]' : '[ ^ ซ่อนรายละเอียด ]';
                } else {
                    button.textContent = isVisible ? '[ v ดูรายละเอียดเพิ่มเติม ]' : '[ ^ ซ่อนรายละเอียด ]';
                }
            });
        });
    };

    fetchInitialInfo();
});
