function toggleTheme() {
    const html = document.documentElement;
    const themeToggle = document.getElementById('theme-toggle');
    
    if (html.classList.contains('dark-mode')) {
        html.classList.remove('dark-mode');
        if (themeToggle) {
            themeToggle.textContent = '🌙 โหมดกลางคืน';
        }
        localStorage.setItem('theme', 'light');
    } else {
        html.classList.add('dark-mode');
        if (themeToggle) {
            themeToggle.textContent = '☀️ โหมดกลางวัน';
        }
        localStorage.setItem('theme', 'dark');
    }
}

function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    const html = document.documentElement;
    const themeToggle = document.getElementById('theme-toggle');
    
    if (savedTheme === 'dark') {
        html.classList.add('dark-mode');
        if (themeToggle) {
            themeToggle.textContent = '☀️ โหมดกลางวัน';
        }
    } else {
        if (themeToggle) {
            themeToggle.textContent = '🌙 โหมดกลางคืน';
        }
    }
    
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }
}

document.addEventListener('DOMContentLoaded', initTheme);
