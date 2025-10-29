document.addEventListener('DOMContentLoaded', () => {
    // ตัวแปรที่เกี่ยวกับปุ่มอัปเดตถูกลบออกไปแล้ว
    const timestampSpan = document.getElementById('info-timestamp');
    const countSpan = document.getElementById('info-count');
    const searchInput = document.getElementById('search-input');
    const resultsContainer = document.getElementById('results-container');

    // 1. โหลดข้อมูล timestamp เริ่มต้นเมื่อเปิดหน้าเว็บ
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

    // 2. ส่วน Event Listener ของปุ่มอัปเดตถูกลบออกไปแล้ว

    // 3. จัดการการค้นหา
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

    // 4. ฟังก์ชันแสดงผลการค้นหา (เหมือนเดิม)
    const renderResults = (results) => {
        if (results.length === 0) {
            resultsContainer.innerHTML = '<p>ไม่พบข้อมูลที่ตรงกับการค้นหา</p>';
            return;
        }

        resultsContainer.innerHTML = results.map(person => `
            <div class="result-group">
                <div class="header">
                    <h3>${person.name}</h3>
                    <p>อายุ/พรรษา: ${person.age_pansa}</p>
                </div>
                <ul class="registrations-list">
                    ${person.registrations.map(reg => `
                        <li>- <strong>(ลำดับที่ ${reg.sequence})</strong> สมัครสอบ ${reg.class_name} (<span>${reg.reg_status}</span>)</li>
                    `).join('')}
                </ul>
            </div>
        `).join('');
    };
    
    // เริ่มทำงาน!
    fetchInitialInfo();
});