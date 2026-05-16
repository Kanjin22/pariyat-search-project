document.addEventListener('DOMContentLoaded', () => {
    renderCharts();
});

function renderCharts() {
    const stats = window.statistics || {};

    const statusCtx = document.getElementById('statusChart');
    if (statusCtx && stats.by_status) {
        const statusLabels = Object.keys(stats.by_status);
        const statusData = Object.values(stats.by_status);
        const colors = [
            '#ef4444',
            '#f59e0b',
            '#22c55e',
            '#3b82f6',
            '#8b5cf6'
        ];

        new Chart(statusCtx, {
            type: 'doughnut',
            data: {
                labels: statusLabels,
                datasets: [{
                    data: statusData,
                    backgroundColor: colors.slice(0, statusLabels.length),
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
