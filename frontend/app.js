const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const apiBaseInput = document.getElementById('apiBase');
const roleSelect = document.getElementById('roleSelect');
const groupFileInput = document.getElementById('groupFile');
const groupPreview = document.getElementById('groupPreview');
const dropZone = document.getElementById('dropZone');
const uploadPlaceholder = document.getElementById('uploadPlaceholder');
const faceOverlay = document.getElementById('faceOverlay');
let activeStream = null;
let capturedImageBase64 = null;
let activityChart = null;
let emotionChart = null;
const emotionUI = {
  happy: { emoji: '😊', label: '心情愉悦', class: 'emo-happy' },
  neutral: { emoji: '😐', label: '情绪平静', class: 'emo-neutral' },
  sad: { emoji: '😔', label: '情绪低落', class: 'emo-sad' },
  angry: { emoji: '💢', label: '情绪波动', class: 'emo-angry' },
  surprised: { emoji: '😲', label: '感到惊讶', class: 'emo-surprised' },
  unknown: { emoji: '❓', label: '识别中', class: 'emo-unknown' }
};

function apiBase() {
  return apiBaseInput.value.trim().replace(/\/$/, '');
}

function setText(id, obj) {
  document.getElementById(id).textContent =
    typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
}

function roleHeader() {
  return roleSelect.value || 'teacher';
}

function getEmoji(emotion) {
  const emo = emotionUI[emotion] || emotionUI.unknown;
  return emo.emoji;
}

function renderGroupResults(body) {
  if (body.matched_count === 0) return '<p class="error">未匹配到任何已注册学生</p>';

  const studentChips = body.matched_students.map((s) => `
    <div class="student-chip">
      <span class="chip-name">${s.student_name}</span>
      <span class="chip-emo">${getEmoji(s.emotion)}</span>
      <small>${Math.round(s.score * 100) / 100}</small>
    </div>
  `).join('');

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
  const url = URL.createObjectURL(file);
  groupPreview.src = url;
  groupPreview.classList.remove('hidden');
  uploadPlaceholder.classList.add('hidden');
  clearOverlay();
}

function renderAttendanceResult(body) {
  const emo = emotionUI[body.emotion] || emotionUI.unknown;
  const confidence = Math.round(Number(body.emotion_confidence) || 0);
  const boundedConfidence = Math.max(0, Math.min(100, confidence));
  const blurOrFft = body.reason.match(/(?:blur|fft)=([0-9.]+)/)?.[1] || 'N/A';

  return `
    <div class="res-card ${body.success ? 'success' : 'fail'}">
      <div class="res-main">
        <span class="status-icon">${body.success ? '✅' : '❌'}</span>
        <div class="info">
          <p class="name">${body.student_name || '未知身份'}</p>
          <p class="id">${body.student_id || '-'}</p>
        </div>
      </div>
      <div class="emotion-bar-container">
        <div class="emotion-label">${emo.emoji} ${emo.label}</div>
        <div class="progress-bg confidence-bar">
          <div class="progress-fill confidence-fill ${emo.class}" style="width: ${boundedConfidence}%"></div>
        </div>
        <small>可靠度: ${boundedConfidence}%</small>
      </div>
      <ul>
        <li>活体置信度: ${body.liveness_passed ? '高' : '低（风险预警）'}</li>
        <li>纹理/清晰度分值: ${blurOrFft}</li>
        <li>情绪模型: ${body.emotion_source || 'unknown'} / ${body.emotion || 'unknown'}</li>
      </ul>
      <p><b>原因:</b> ${body.reason || '-'}</p>
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
        ...(headers || {}),
        'X-Role': roleHeader()
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

async function toBase64FromVideo() {
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.9);
}

function stopCamera() {
  if (activeStream) {
    activeStream.getTracks().forEach((track) => track.stop());
    activeStream = null;
  }
  video.srcObject = null;
}

document.getElementById('btnOpenCam').addEventListener('click', async () => {
  try {
    stopCamera();
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    activeStream = stream;
    video.srcObject = stream;
    capturedImageBase64 = null;
    setText('attendanceText', '摄像头已开启，请拍照后再注册或考勤');
  } catch (err) {
    setText('attendanceText', `摄像头调用失败: ${err.message}`);
  }
});

document.getElementById('btnCapture').addEventListener('click', async () => {
  try {
    if (!activeStream) {
      throw new Error('请先开启摄像头');
    }
    setText('attendanceText', '正在拍照，请保持不动 1 秒...');
    await new Promise((resolve) => setTimeout(resolve, 1000));
    capturedImageBase64 = await toBase64FromVideo();
    setText('attendanceText', '拍照成功。你可以继续拍照，或直接注册/考勤。');
  } catch (err) {
    setText('attendanceText', `拍照失败: ${err.message}`);
  }
});

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

document.getElementById('btnHealth').addEventListener('click', async () => {
  try {
    const body = await fastFetch(`${apiBase()}/api/health`, {
      triggerBtn: document.getElementById('btnHealth')
    });
    setText('healthText', body.ok ? '服务正常' : '服务异常');
  } catch (err) {
    setText('healthText', `请求失败: ${err.message}`);
  }
});

document.getElementById('btnRegister').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnRegister');
  const studentId = document.getElementById('studentId').value.trim();
  const studentName = document.getElementById('studentName').value.trim();
  if (!studentId || !studentName) {
    setText('registerText', '请填写学号和姓名');
    return;
  }

  try {
    if (!capturedImageBase64) {
      throw new Error('请先点击“拍照”，注册只使用拍照后的冻结图像');
    }
    const image_base64 = capturedImageBase64;
    const body = await fastFetch(`${apiBase()}/api/students/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_id: studentId, name: studentName, image_base64 }),
      triggerBtn
    });
    setText('registerText', body);
  } catch (err) {
    setText('registerText', `注册失败: ${err.message}`);
  }
});

document.getElementById('btnAttendance').addEventListener('click', async (e) => {
  const triggerBtn = e.target;
  const attendanceText = document.getElementById('attendanceText');
  try {
    if (!capturedImageBase64 && !activeStream) {
      throw new Error('请先点击“拍照”，考勤只使用拍照后的冻结图像');
    }
    const usingLiveFrame = Boolean(activeStream);
    const image_base64 = usingLiveFrame ? await toBase64FromVideo() : capturedImageBase64;
    if (!usingLiveFrame) {
      attendanceText.innerHTML = '<p class="error">当前使用冻结帧签到。建议先点“开启摄像头”获取最新画面。</p>';
    }
    const classroom_id = document.getElementById('classroomId').value.trim() || 'default';
    const body = await fastFetch(`${apiBase()}/api/attendance/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classroom_id, image_base64 }),
      triggerBtn
    });
    attendanceText.innerHTML = renderAttendanceResult(body);
  } catch (err) {
    attendanceText.innerHTML = `<p class="error">${err.message}</p>`;
  }
});

document.getElementById('btnGroup').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnGroup');
  const file = groupFileInput.files[0];
  const groupText = document.getElementById('groupText');
  if (!file) {
    groupText.innerHTML = '<p class="error">请选择图片文件</p>';
    return;
  }
  groupText.innerHTML = '<p>正在识别中，请稍候...</p>';
  try {
    const form = new FormData();
    form.append('activity_name', document.getElementById('activityName').value || 'default_activity');
    form.append('file', file);

    const body = await fastFetch(`${apiBase()}/api/group-photo/recognize`, {
      method: 'POST',
      body: form,
      triggerBtn
    });
    groupText.innerHTML = renderGroupResults(body);
    // Optional overlay: render only when backend provides face boxes.
    renderFaceOverlay(body.face_boxes);
  } catch (err) {
    groupText.innerHTML = `<p class="error">合照识别失败: ${err.message}</p>`;
  }
});

document.getElementById('btnActivityReport').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnActivityReport');
  try {
    const body = await fastFetch(`${apiBase()}/api/reports/activity-stats`, { triggerBtn });
    setText('activityReportText', body);
    document.getElementById('activityReportWrapper').innerHTML = renderActivityStats(body);
    const items = body.items || [];
    const ctx = document.getElementById('activityChart').getContext('2d');
    if (activityChart) activityChart.destroy();
    activityChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: items.map((i) => i.student_name),
        datasets: [{
          label: '参与次数',
          data: items.map((i) => i.activity_count ?? i.frequency ?? 0),
          backgroundColor: '#7ad3e5'
        }]
      },
      options: { responsive: true, plugins: { legend: { display: false } } }
    });
  } catch (err) {
    setText('activityReportText', `获取失败: ${err.message}`);
  }
});

document.getElementById('btnEmotionReport').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnEmotionReport');
  try {
    const body = await fastFetch(`${apiBase()}/api/reports/emotion`, { triggerBtn });
    setText('emotionReportText', body);
    document.getElementById('emotionLegend').innerHTML = renderEmotionLegend(body);
    const items = body.items || [];
    const ctx = document.getElementById('emotionChart').getContext('2d');
    if (emotionChart) emotionChart.destroy();
    emotionChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: items.map((i) => i.emotion),
        datasets: [{
          data: items.map((i) => i.count),
          backgroundColor: ['#ff8fa3', '#7ad3e5', '#ffd166', '#06d6a0', '#a78bfa', '#f97316']
        }]
      },
      options: { responsive: true }
    });
  } catch (err) {
    setText('emotionReportText', `获取失败: ${err.message}`);
  }
});

document.getElementById('btnExportAttendance').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnExportAttendance');
  try {
    const body = await fastFetch(`${apiBase()}/api/reports/export-attendance`, {
      method: 'POST',
      triggerBtn
    });
    const notice = document.createElement('div');
    notice.className = 'download-notice';
    notice.innerHTML = `✅ 报表已生成！<br/><small>路径：${body.file_path}</small>`;
    document.body.appendChild(notice);
    setTimeout(() => notice.remove(), 5000);
    setText('emotionReportText', `导出成功: ${body.file_path}`);
  } catch (err) {
    setText('emotionReportText', `导出失败: ${err.message}`);
  }
});

document.getElementById('btnDownloadDaily').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnDownloadDaily');
  try {
    const body = await fastFetch(`${apiBase()}/api/reports/export-attendance`, {
      method: 'POST',
      triggerBtn
    });
    alert(`考勤名册已生成在服务器: ${body.file_path}`);
  } catch (err) {
    alert(`导出失败: ${err.message}`);
  }
});
