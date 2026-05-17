document.addEventListener('DOMContentLoaded', function() {
  loadStatistics();
});

async function loadStatistics() {
  try {
    const response = await fetch(`/api/statistics/${department}/${subsection}?year=${encodeURIComponent(String(selectedYear ?? ''))}`);
    const data = await response.json();
    
    if (data.success && data.statistics) {
      renderCharts(data.statistics);
    }
  } catch (error) {
    console.error('Error loading statistics:', error);
  }
}

function renderCharts(stats) {
  renderStatusChart(stats.by_status || {});
  renderClassChart(stats.by_class || {});
}

function renderStatusChart(statusData) {
  const ctx = document.getElementById('statusChart');
  if (!ctx) return;

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
  const labels = [
    ...statusOrder.filter((name) => Object.prototype.hasOwnProperty.call(statusData, name)),
    ...Object.keys(statusData).filter((name) => !statusOrder.includes(name))
  ];
  const data = labels.map((label) => statusData[label]);
  const colors = labels.map((label) => statusColorMap[label] || '#64748b');

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: colors,
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            font: {
              family: 'Sarabun',
              size: 14
            },
            padding: 20
          }
        }
      }
    }
  });
}

function renderClassChart(classData) {
  const ctx = document.getElementById('classChart');
  if (!ctx) return;

  const labels = Object.keys(classData);
  const data = Object.values(classData);

  const colors = labels.map(() => {
    const hue = Math.floor(Math.random() * 360);
    return `hsl(${hue}, 70%, 50%)`;
  });

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'จำนวนผู้สมัคร',
        data: data,
        backgroundColor: colors,
        borderRadius: 8
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          display: false
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            maxTicksLimit: 8,
            callback: function(value) {
              return String(Math.round(value));
            },
            font: {
              family: 'Sarabun'
            }
          }
        },
        x: {
          ticks: {
            font: {
              family: 'Sarabun'
            }
          }
        }
      }
    }
  });
}
