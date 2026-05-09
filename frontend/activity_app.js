const apiBase = 'http://127.0.0.1:8000';
const groupFileInput = document.getElementById('groupFile');
const groupPreview = document.getElementById('groupPreview');
const dropZone = document.getElementById('dropZone');
const uploadPlaceholder = document.getElementById('uploadPlaceholder');
const faceOverlay = document.getElementById('faceOverlay');
let activityChart = null;
let emotionChart = null;
let autoRefreshInterval = null;

const emotionUI = {
  happy: { emoji: '😊', label: '心情愉悦', class: 'emo-happy' },
  neutral: { emoji: '😐', label: '情绪平静', class: 'emo-neutral' },
  sad: { emoji: '😔', label: '情绪低落', class: 'emo-sad' },
  angry: { emoji: '💢', label: '情绪波动', class: 'emo-angry' },
  surprised: { emoji: '😲', label: '感到惊讶', class: 'emo-surprised' },
  unknown: { emoji: '❓', label: '识别中', class: 'emo-unknown' }
};

const iosColors = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#007aff', '#5856d6', '#af52de'];

function updateProgress(processed, total, message = '识别中') {
  const progressEl = document.getElementById('progressBar');
  const progressTextEl = document.getElementById('progressText');
  if (progressEl && progressTextEl) {
    const percent = Math.round((processed / total) * 100);
    progressEl.style.width = percent + '%';
    progressTextEl.textContent = `${message}: ${processed}/${total} (${percent}%)`;
  }
}

function showProgressBar() {
  const progressContainer = document.getElementById('progressContainer');
  if (progressContainer) {
    progressContainer.classList.remove('hidden');
  }
}

function hideProgressBar() {
  const progressContainer = document.getElementById('progressContainer');
  const progressTextEl = document.getElementById('progressText');
  if (progressContainer) {
    progressContainer.classList.add('hidden');
  }
  if (progressTextEl) {
    progressTextEl.textContent = '';
  }
}

function showToast(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function setText(id, obj) {
  document.getElementById(id).textContent =
    typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
}

function getEmoji(emotion) {
  const emo = emotionUI[emotion] || emotionUI.unknown;
  return emo.emoji;
}

function clearOverlay() {
  faceOverlay.innerHTML = '';
}

function renderFaceOverlay(faceBoxes = []) {
  clearOverlay();
  if (!Array.isArray(faceBoxes)) return;
  faceBoxes.forEach((box) => {
    const div = document.createElement('div');
    div.className = 'face-box';
    div.style.left = `${box.x}px`;
    div.style.top = `${box.y}px`;
    div.style.width = `${box.w}px`;
    div.style.height = `${box.h}px`;
    faceOverlay.appendChild(div);
  });
}

function bindPreviewFile(file) {
  if (!file) return;
  
  clearOverlay();
  
  const groupText = document.getElementById('groupText');
  if (groupText) {
    groupText.innerHTML = '';
  }
  
  const url = URL.createObjectURL(file);
  groupPreview.src = url;
  groupPreview.classList.remove('hidden');
  uploadPlaceholder.classList.add('hidden');
  clearOverlay();
}

function renderGroupResults(body) {
  if (body.matched_count === 0) return '<p class="error">未匹配到任何已注册学生</p>';

  const studentChips = body.matched_students.map((s) => {
    const emoInfo = emotionUI[s.emotion] || emotionUI.unknown;
    return `
      <div class="student-chip">
        <span class="chip-name">${s.student_name}</span>
        <span class="chip-emo">${emoInfo.emoji}</span>
        <small>${Math.round(s.score * 100) / 100}</small>
      </div>
    `;
  }).join('');

  return `
    <div class="res-card success">
      <div class="res-summary">
        <div><strong>总人数:</strong> ${body.total_faces}</div>
        <div><strong>识别成功:</strong> ${body.matched_count}</div>
      </div>
      <div class="chip-grid">${studentChips}</div>
    </div>
  `;
}

function renderActivityStats(data) {
  const items = data.items || [];
  if (items.length === 0) return '<p class="hint">暂无活动参与数据</p>';

  const listHtml = items.map((item, index) => `
    <div class="stats-row">
      <span class="rank">${index + 1}</span>
      <span class="name">${item.student_name}</span>
      <div class="activity-bar-bg">
        <div class="activity-bar-fill" style="width: ${Math.min((item.activity_count || 0) * 10, 100)}%"></div>
      </div>
      <span class="count"><b>${item.activity_count || 0}</b> 次</span>
    </div>
  `).join('');

  return `<div class="stats-container">${listHtml}</div>`;
}

function renderEmotionLegend(data) {
  const items = data.items || [];
  const emotionMap = {
    happy: '😊 开心',
    neutral: '😐 平静',
    sad: '😔 低落',
    angry: '💢 波动',
    surprised: '😲 惊讶',
    unknown: '❓ 未知'
  };
  return items.map((item) => `
    <div class="emo-badge">
      <span class="label">${emotionMap[item.emotion] || item.emotion}</span>
      <span class="val">${item.count} 人</span>
    </div>
  `).join('');
}

async function fastFetch(url, options = {}) {
  const { triggerBtn, headers, ...rest } = options;
  if (triggerBtn) {
    triggerBtn.disabled = true;
    triggerBtn.dataset.origText = triggerBtn.textContent;
    triggerBtn.textContent = '处理中...';
  }
  try {
    const resp = await fetch(url, {
      ...rest,
      headers: {
        'X-Role': 'teacher',
        ...(headers || {})
      }
    });
    const body = await resp.json();
    if (!resp.ok) {
      throw new Error(body.message || body.detail || '请求失败');
    }
    return body;
  } finally {
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.textContent = triggerBtn.dataset.origText || '提交';
    }
  }
}

dropZone.addEventListener('click', () => groupFileInput.click());
groupFileInput.addEventListener('change', (e) => {
  const file = e.target.files?.[0];
  bindPreviewFile(file);
});
dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const file = e.dataTransfer?.files?.[0];
  if (!file) return;
  const dt = new DataTransfer();
  dt.items.add(file);
  groupFileInput.files = dt.files;
  bindPreviewFile(file);
});

document.getElementById('btnGroup').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnGroup');
  const file = groupFileInput?.files?.[0];
  const groupText = document.getElementById('groupText');
  const activityNameInput = document.getElementById('activityName');
  const activityName = activityNameInput?.value?.trim();
  const activityTypeInput = document.getElementById('activityType');
  const activityType = activityTypeInput?.value || 'other';
  const activityTimeInput = document.getElementById('activityTime');
  const activityTime = activityTimeInput?.value;
  
  if (!activityName) {
    groupText.innerHTML = '<p class="error">请填写活动名称</p>';
    return;
  }
  if (!file) {
    groupText.innerHTML = '<p class="error">请选择图片文件</p>';
    return;
  }
  groupText.innerHTML = '<p>正在识别中，请稍候...</p>';
  showProgressBar();
  updateProgress(0, 100, '开始识别');
  
  try {
    const form = new FormData();
    form.append('activity_name', activityName);
    form.append('activity_type', activityType);
    if (activityTime) {
      form.append('activity_time', activityTime);
    }
    form.append('file', file);

    updateProgress(30, 100, '上传中');
    
    const body = await fastFetch(`${apiBase}/api/group-photo/recognize`, {
      method: 'POST',
      body: form,
      triggerBtn
    });
    
    updateProgress(80, 100, '渲染结果');
    
    setTimeout(() => {
      groupText.innerHTML = renderGroupResults(body);
      renderFaceOverlay(body.face_boxes);
      hideProgressBar();
      updateActivityCharts(activityName);
      showToast(`✅ 识别成功！共 ${body.matched_count} 人`);
    }, 100);
    
  } catch (err) {
    groupText.innerHTML = `<p class="error">合照识别失败: ${err.message}</p>`;
    hideProgressBar();
  }
});

async function updateActivityCharts(activityName) {
  try {
    const body = await fastFetch(`${apiBase}/api/reports/activity-detail?activity_name=${encodeURIComponent(activityName)}`, { triggerBtn: null });
    
    document.getElementById('activityStatsWrapper').innerHTML = renderActivityStats({ items: body.list });
    
    const items = body.emotions || [];
    const chartDom = document.getElementById('activityEmotionChart');
    if (emotionChart) {
      emotionChart.dispose();
    }
    emotionChart = echarts.init(chartDom);
    
    const option = {
      tooltip: {
        trigger: 'item',
        formatter: '{b}: {c} 人 ({d}%)'
      },
      legend: {
        orient: 'vertical',
        left: 'left',
        bottom: 0,
        textStyle: {
          fontSize: 13
        }
      },
      series: [
        {
          name: '情绪分布',
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 10,
            borderColor: '#fff',
            borderWidth: 2
          },
          label: {
            show: false,
            position: 'center'
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 20,
              fontWeight: 'bold'
            }
          },
          labelLine: {
            show: false
          },
          data: items.map((item, index) => ({
            value: item.count,
            name: item.emotion,
            itemStyle: {
              color: iosColors[index % iosColors.length]
            }
          }))
        }
      ]
    };
    
    emotionChart.setOption(option);
  } catch (err) {
    console.error('更新活动图表失败:', err.message);
  }
}

document.getElementById('btnActivityReport').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnActivityReport');
  try {
    const body = await fastFetch(`${apiBase}/api/reports/activity-stats`, { triggerBtn });
    setText('activityReportText', body);
    document.getElementById('activityStatsWrapper').innerHTML = renderActivityStats(body);
    const items = body.items || [];
    const chartDom = document.getElementById('activityChart');
    if (activityChart) {
      activityChart.dispose();
    }
    activityChart = echarts.init(chartDom);
    
    const option = {
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'shadow'
        }
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: items.map((i) => i.student_name),
        axisLabel: {
          interval: 0,
          rotate: 30
        }
      },
      yAxis: {
        type: 'value',
        name: '参与次数'
      },
      series: [
        {
          name: '参与次数',
          type: 'bar',
          data: items.map((i) => i.activity_count ?? i.frequency ?? 0),
          itemStyle: {
            borderRadius: [8, 8, 0, 0],
            color: function(params) {
              return iosColors[params.dataIndex % iosColors.length];
            }
          }
        }
      ]
    };
    
    activityChart.setOption(option);
  } catch (err) {
    setText('activityReportText', `获取失败: ${err.message}`);
  }
});

document.getElementById('btnEmotionReport').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnEmotionReport');
  try {
    const body = await fastFetch(`${apiBase}/api/reports/emotion`, { triggerBtn });
    setText('emotionReportText', body);
    document.getElementById('emotionLegend').innerHTML = renderEmotionLegend(body);
    const items = body.items || [];
    const chartDom = document.getElementById('emotionChart');
    if (emotionChart) {
      emotionChart.dispose();
    }
    emotionChart = echarts.init(chartDom);
    
    const option = {
      tooltip: {
        trigger: 'item',
        formatter: '{b}: {c} 人 ({d}%)'
      },
      legend: {
        orient: 'vertical',
        left: 'left',
        bottom: 0,
        textStyle: {
          fontSize: 13
        }
      },
      series: [
        {
          name: '情绪分布',
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 10,
            borderColor: '#fff',
            borderWidth: 2
          },
          label: {
            show: false,
            position: 'center'
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 20,
              fontWeight: 'bold'
            }
          },
          labelLine: {
            show: false
          },
          data: items.map((item, index) => ({
            value: item.count,
            name: item.emotion,
            itemStyle: {
              color: iosColors[index % iosColors.length]
            }
          }))
        }
      ]
    };
    
    emotionChart.setOption(option);
  } catch (err) {
    setText('emotionReportText', `获取失败: ${err.message}`);
  }
});

document.getElementById('btnExportAttendance').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnExportAttendance');
  try {
    const body = await fastFetch(`${apiBase}/api/reports/export-attendance`, {
      method: 'POST',
      triggerBtn
    });
    const notice = document.createElement('div');
    notice.className = 'download-notice';
    notice.innerHTML = `✅ 报表已生成！<br/><small>路径：${body.file_path}</small>`;
    document.body.appendChild(notice);
    setTimeout(() => notice.remove(), 5000);
    setText('emotionReportText', `导出成功: ${body.file_path}`);
    showToast('✅ 导出成功');
  } catch (err) {
    setText('emotionReportText', `导出失败: ${err.message}`);
  }
});

function startAutoRefresh() {
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval);
  }
  autoRefreshInterval = setInterval(() => {
    const activityName = document.getElementById('activityName')?.value.trim();
    if (activityName) {
      updateActivityCharts(activityName);
    }
  }, 30000);
}

document.addEventListener('DOMContentLoaded', () => {
  startAutoRefresh();
});
