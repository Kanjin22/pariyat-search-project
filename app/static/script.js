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
            // --- จุดแก้ไขที่ 1: แยกข้อมูล อายุ/พรรษา ---
            let age = '';
            let pansa = '';
            const agePansaString = person.age_pansa || ''; // ดึงข้อมูลมาและป้องกันค่า null

            if (agePansaString.includes('/')) {
                // ถ้ามีเครื่องหมาย '/' ให้แยกส่วนกัน
                const parts = agePansaString.split('/');
                age = parts[0];
                pansa = parts[1];
            } else {
                // ถ้าไม่มี ก็ให้เป็นแค่อายุ
                age = agePansaString;
            }

            // สร้าง HTML สำหรับบรรทัดพรรษา (จะแสดงก็ต่อเมื่อมีข้อมูล)
            const pansaLine = pansa ? `- พรรษา: ${pansa}<br>` : '';

            // (โค้ดส่วน regListHtml เหมือนเดิม)
            const regListHtml = person.registrations.map((reg, regIndex) => {
                const hasCert = reg.cert_nugdham || reg.cert_pali;
                const nugdhamLine = reg.cert_nugdham ? `: ${reg.cert_nugdham}<br>` : '';
                const paliLine = reg.cert_pali ? `: ${reg.cert_pali}<br>` : '';
                return `
                <li class="reg-item">
                    - <strong>(ลำดับที่ ${reg.sequence})</strong> สมัครสอบ ${reg.class_name} (<span>${reg.reg_status}</span>)
                    ${hasCert ? `<button class="details-btn-reg" data-target="details-reg-${personIndex}-${regIndex}">[ v ดูรายละเอียดเพิ่มเติม ]</button>` : ''}
                    ${hasCert ? `<div class="details-reg" id="details-reg-${personIndex}-${regIndex}" style="display: none;">- เลขประกาศนียบัตรเดิม:<br><div class="cert-details">${nugdhamLine}${paliLine}</div></div>` : ''}
                </li>`;
            }).join('');

            // --- จุดแก้ไขที่ 2: ปรับปรุงโครงสร้าง HTML ---
            return `
            <div class="result-group">
                <div class="header">
                    <h3>${person.name}</h3>
                    <!-- ย้ายปุ่มมาไว้ท้ายชื่อ และลบ อายุ/พรรษา ออกไป -->
                    <button class="details-btn" data-target="details-${personIndex}">[ v ดูรายละเอียดเพิ่มเติม ]</button>
                </div>
                <div class="details" id="details-${personIndex}" style="display: none;">
                    <strong>ข้อมูลส่วนตัว:</strong><br>
                    <div class="details-content">
                        <!-- นำ อายุ และ พรรษา มาแสดงที่นี่ -->
                        - อายุ: ${age || '-'}<br>
                        ${pansaLine}
                        - สังกัด: ${person.school_name || '-'}<br>
                        - กลุ่ม: ${person.group_name || '-'}
                    </div>
                </div>
                <ul class="registrations-list">
                    ${regListHtml}
                </ul>
            </div>
        `;
        }).join('');

        // (Event Listener เหมือนเดิม)
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