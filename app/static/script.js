document.addEventListener('DOMContentLoaded', () => {
    const timestampSpan = document.getElementById('info-timestamp');
    const countSpan = document.getElementById('info-count');
    const searchInput = document.getElementById('search-input');
    const resultsContainer = document.getElementById('results-container');

    const fetchInitialInfo = async () => {
        try {
            const response = await fetch('/get_data_info');
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
        const response = await fetch(`/search?q=${encodeURIComponent(query)}`);
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
                const hasCert = reg.cert_nugdham || reg.cert_pali;
                const nugdhamLine = reg.cert_nugdham ? ` - ${reg.cert_nugdham}<br>` : '';
                const paliLine = reg.cert_pali ? ` - ${reg.cert_pali}<br>` : '';

                return `
                    <li class="reg-item">
                        <div class="reg-item-visible">
                            <span class="reg-info">
                                - <strong>(ลำดับที่ ${reg.sequence})</strong> สมัครสอบ ${reg.class_name} (<span class="status-text">${reg.reg_status}</span>)
                            </span>
                            ${hasCert ? `<button class="details-btn-reg" data-target="details-reg-${personIndex}-${regIndex}">[ v ดูรายละเอียดเพิ่มเติม ]</button>` : ''}
                        </div>
                        
                        ${hasCert ? `
                        <div class="details-reg" id="details-reg-${personIndex}-${regIndex}" style="display: none;">
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

            const telLine = person.tel_masked_text
                ? `- เบอร์โทรศัพท์: <a class="phone-link" href="tel:${person.tel_cleaned}">${person.tel_masked_text}</a><br>`
                : '';

            let idStatusClass = '';
            if (person.id_status_text.includes('✅')) {
                idStatusClass = 'status-valid';
            } else if (person.id_status_text.includes('❌')) {
                idStatusClass = 'status-invalid';
            }

            return `
                <div class="result-group">
                    <div class="header">
                        <h3>${person.name}</h3>
                        <button class="details-btn" data-target="details-${personIndex}">[ v ดูรายละเอียดเพิ่มเติม ]</button>
                    </div>
                    <div class="details" id="details-${personIndex}" style="display: none;">
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
                const isVisible = targetElement.style.display === 'block';

                targetElement.style.display = isVisible ? 'none' : 'block';
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