document.addEventListener('DOMContentLoaded', () => {
    renderCharts();
});

function renderCharts() {
    const stats = window.statistics || {};

    const statusCtx = document.getElementById('statusChart');
    if (statusCtx && stats.by_status) {
        const statusOrder = ['สอบได้', 'สอบซ่อมได้', 'สอบซ่อม', 'สอบตก', 'ขาดสอบ', 'ขาดสิทธิ์', 'ยังไม่บันทึกผล'];
        const statusColorMap = {
            'สอบได้': '#22c55e',
            'สอบซ่อมได้': '#3b82f6',
            'สอบซ่อม': '#f59e0b',
            'สอบตก': '#9ca3af',
            'ขาดสอบ': '#ef4444',
            'ขาดสิทธิ์': '#8b5cf6',
            'ยังไม่บันทึกผล': '#cbd5e1'
        };
        const statusEntries = stats.by_status || {};
        const statusLabels = [
            ...statusOrder.filter((name) => Object.prototype.hasOwnProperty.call(statusEntries, name)),
            ...Object.keys(statusEntries).filter((name) => !statusOrder.includes(name))
        ];
        const statusData = statusLabels.map((label) => statusEntries[label]);
        const colors = statusLabels.map((label) => statusColorMap[label] || '#64748b');

        new Chart(statusCtx, {
            type: 'doughnut',
            data: {
                labels: statusLabels,
                datasets: [{
                    data: statusData,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#ffffff'
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }

    const classCtx = document.getElementById('classChart');
    if (classCtx && stats.by_class) {
        const classLabels = Object.keys(stats.by_class);
        const classData = Object.values(stats.by_class);

        new Chart(classCtx, {
            type: 'bar',
            data: {
                labels: classLabels,
                datasets: [{
                    label: 'จำนวนผู้สมัคร',
                    data: classData,
                    backgroundColor: '#667eea',
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45
                        }
                    }
                }
            }
        });
    }
}
