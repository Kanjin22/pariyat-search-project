let staffAccounts = [];
let editingUsername = null;

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

function showMessage(text, isError = false) {
    const messageEl = document.getElementById('staff-message');
    messageEl.textContent = text;
    messageEl.className = 'save-message' + (isError ? ' error' : ' success');
    setTimeout(() => {
        messageEl.textContent = '';
        messageEl.className = 'save-message';
    }, 5000);
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatDate(isoString) {
    if (!isoString) return '-';
    try {
        const date = new Date(isoString);
        return date.toLocaleDateString('th-TH', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return isoString;
    }
}

async function loadStaff() {
    try {
        const response = await fetch('/api/staff');
        const data = await response.json();
        if (data.success) {
            staffAccounts = data.accounts;
            renderStaffList();
        }
    } catch (error) {
        console.error('Error loading staff:', error);
    }
}

function renderStaffList() {
    const container = document.getElementById('staff-list-container');
    if (!staffAccounts || staffAccounts.length === 0) {
        container.innerHTML = '<p class="empty-state">ยังไม่มีเจ้าหน้าที่ในระบบ</p>';
        return;
    }

    container.innerHTML = staffAccounts.map(account => {
        const isActive = account.active !== false;
        const isOwnAccount = account.username === (window.currentStaffUsername || '');
        const isEditing = editingUsername === account.username;
        const role = account.role || 'staff';

        return `
            <div class="staff-card" data-username="${escapeHtml(account.username)}">
                <div class="staff-card-header">
                    <div style="display: flex; align-items: center; flex-wrap: wrap;">
                        <h3>${escapeHtml(account.full_name || account.username)}</h3>
                        <span class="role-badge ${role}">${role === 'admin' ? 'Admin' : 'Staff'}</span>
                    </div>
                    <span class="staff-badge ${isActive ? 'active' : 'inactive'}">
                        ${isActive ? 'ใช้งานอยู่' : 'ปิดใช้งาน'}
                    </span>
                </div>
                <div class="staff-card-body">
                    <div class="staff-info-row">
                        <span class="staff-info-label">ชื่อผู้ใช้:</span> ${escapeHtml(account.username)}
                    </div>
                    <div class="staff-info-row">
                        <span class="staff-info-label">ชื่อ-สกุล:</span> ${escapeHtml(account.full_name || '-')}
                    </div>
                    <div class="staff-info-row">
                        <span class="staff-info-label">สร้างเมื่อ:</span> ${formatDate(account.created_at)}
                    </div>
                    ${account.updated_at ? `
                        <div class="staff-info-row">
                            <span class="staff-info-label">แก้ไขล่าสุด:</span> ${formatDate(account.updated_at)}
                        </div>
                    ` : ''}
                </div>
                ${isEditing ? renderEditForm(account) : ''}
                <div class="staff-card-actions">
                    <button class="staff-btn edit" onclick="startEdit('${escapeHtml(account.username)}')" ${isEditing ? 'disabled' : ''}>
                        แก้ไข
                    </button>
                    <button class="staff-btn toggle ${!isActive ? 'inactive-btn' : ''}" 
                            onclick="toggleStaff('${escapeHtml(account.username)}', ${!isActive})"
                            ${isOwnAccount ? 'disabled' : ''}>
                        ${isActive ? 'ปิดใช้งาน' : 'เปิดใช้งาน'}
                    </button>
                    <button class="staff-btn delete" 
                            onclick="deleteStaff('${escapeHtml(account.username)}')"
                            ${isOwnAccount ? 'disabled' : ''}>
                        ลบ
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function renderEditForm(account) {
    const role = account.role || 'staff';
    return `
        <form class="edit-staff-form" onsubmit="saveEdit(event, '${escapeHtml(account.username)}')">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label" for="edit-fullname-${escapeHtml(account.username)}">ชื่อ-สกุล</label>
                    <input class="form-input" type="text" id="edit-fullname-${escapeHtml(account.username)}" 
                           value="${escapeHtml(account.full_name || '')}" />
                </div>
                <div class="form-group">
                    <label class="form-label" for="edit-role-${escapeHtml(account.username)}">สิทธิ์การเข้าถึง</label>
                    <select class="form-input" id="edit-role-${escapeHtml(account.username)}">
                        <option value="staff" ${role === 'staff' ? 'selected' : ''}>Staff (จัดการผลสอบ)</option>
                        <option value="admin" ${role === 'admin' ? 'selected' : ''}>Admin (จัดการทุกอย่าง)</option>
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label" for="edit-password-${escapeHtml(account.username)}">รหัสผ่านใหม่ (ถ้าต้องการเปลี่ยน)</label>
                <input class="form-input" type="password" id="edit-password-${escapeHtml(account.username)}" placeholder="เว้นว่างถ้าไม่ต้องการเปลี่ยน" />
            </div>
            <div class="edit-staff-actions">
                <button type="submit" class="staff-btn edit">บันทึก</button>
                <button type="button" class="staff-btn cancel" onclick="cancelEdit()">ยกเลิก</button>
            </div>
        </form>
    `;
}

function startEdit(username) {
    editingUsername = username;
    renderStaffList();
}

function cancelEdit() {
    editingUsername = null;
    renderStaffList();
}

async function saveEdit(event, username) {
    event.preventDefault();
    const fullName = document.getElementById(`edit-fullname-${username}`)?.value?.trim() || null;
    const password = document.getElementById(`edit-password-${username}`)?.value || null;
    const role = document.getElementById(`edit-role-${username}`)?.value;

    const payload = {};
    if (fullName !== null) payload.full_name = fullName;
    if (password) payload.password = password;
    if (role) payload.role = role;

    try {
        const response = await fetch(`/api/staff/${encodeURIComponent(username)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, 'success', 'บันทึกสำเร็จ!');
            editingUsername = null;
            loadStaff();
        } else {
            showToast(data.message || 'เกิดข้อผิดพลาด', 'error', 'ผิดพลาด!');
        }
    } catch (error) {
        console.error('Error updating staff:', error);
        showToast('เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error', 'ผิดพลาด!');
    }
}

async function toggleStaff(username, active) {
    try {
        const response = await fetch(`/api/staff/${encodeURIComponent(username)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active })
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, 'success');
            loadStaff();
        } else {
            showToast(data.message || 'เกิดข้อผิดพลาด', 'error');
        }
    } catch (error) {
        console.error('Error toggling staff:', error);
        showToast('เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
    }
}

async function deleteStaff(username) {
    if (!confirm(`คุณแน่ใจหรือไม่ว่าต้องการลบเจ้าหน้าที่ "${username}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/staff/${encodeURIComponent(username)}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, 'success', 'ลบสำเร็จ!');
            loadStaff();
        } else {
            showToast(data.message || 'เกิดข้อผิดพลาด', 'error', 'ผิดพลาด!');
        }
    } catch (error) {
        console.error('Error deleting staff:', error);
        showToast('เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error', 'ผิดพลาด!');
    }
}

document.getElementById('add-staff-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const username = document.getElementById('new-username')?.value?.trim();
    const fullName = document.getElementById('new-fullname')?.value?.trim();
    const password = document.getElementById('new-password')?.value;
    const role = document.getElementById('new-role')?.value || 'staff';

    if (!username || !password) {
        showToast('กรุณากรอกชื่อผู้ใช้และรหัสผ่าน', 'error', 'ผิดพลาด!');
        return;
    }

    try {
        const response = await fetch('/api/staff', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, full_name: fullName, password, role })
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, 'success', 'เพิ่มสำเร็จ!');
            document.getElementById('add-staff-form').reset();
            loadStaff();
        } else {
            showToast(data.message || 'เกิดข้อผิดพลาด', 'error', 'ผิดพลาด!');
        }
    } catch (error) {
        console.error('Error adding staff:', error);
        showToast('เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error', 'ผิดพลาด!');
    }
});

document.addEventListener('DOMContentLoaded', () => {
    createToastContainer();
    loadStaff();
});
