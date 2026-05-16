function showToast(message, type = 'success', title = '') {
    const container = document.querySelector('.toast-container') || createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: '✅',
        error: '❌',
        info: 'ℹ️'
    };
    
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || '📢'}</span>
        <div class="toast-content">
            ${title ? `<div class="toast-title">${title}</div>` : ''}
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">×</button>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        if (toast.parentElement) {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

function createToastContainer() {
    const container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
}

document.getElementById('backup-btn')?.addEventListener('click', async () => {
    const btn = document.getElementById('backup-btn');
    btn.disabled = true;
    btn.textContent = 'กำลังสำรอง...';
    
    try {
        const response = await fetch('/api/backup', {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success', 'สำเร็จ!');
        } else {
            showToast(data.message || 'เกิดข้อผิดพลาด', 'error', 'ผิดพลาด!');
        }
    } catch (error) {
        console.error('Error creating backup:', error);
        showToast('เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error', 'ผิดพลาด!');
    } finally {
        btn.disabled = false;
        btn.textContent = 'สำรองข้อมูลตอนนี้';
    }
});

document.addEventListener('DOMContentLoaded', () => {
    createToastContainer();
});
