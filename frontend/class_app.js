const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const apiBase = 'http://127.0.0.1:8000';
const attendanceText = document.getElementById('attendanceText');
let activeStream = null;
let capturedImageBase64 = null;
let classEmotionChart = null;
let autoCheckEnabled = true;

const iosColors = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#007aff', '#5856d6', '#af52de'];

function showHint(message, type = 'info') {
  if (attendanceText) {
    attendanceText.innerHTML = `<p class="${type === 'error' ? 'error' : 'hint'}">${message}</p>`;
  }
}

function updateCameraStatus() {
  const statusEl = document.getElementById('cameraStatus');
  if (statusEl) {
    if (activeStream) {
      statusEl.innerHTML = '📷 摄像头已开启';
      statusEl.className = 'camera-status active';
    } else {
      statusEl.innerHTML = '📷 摄像头未开启';
      statusEl.className = 'camera-status inactive';
    }
  }
}

if (video) {
  video.addEventListener('error', () => {
    showHint('摄像头错误，请检查设备', 'error');
    stopCamera();
    updateCameraStatus();
  });
}

function stopCamera() {
  if (activeStream) {
    activeStream.getTracks().forEach((track) => track.stop());
    activeStream = null;
  }
  video.srcObject = null;
  updateCameraStatus();
}

const emotionUI = {
  happy: { emoji: '😊', label: '心情愉悦', class: 'emo-happy' },
  neutral: { emoji: '😐', label: '情绪平静', class: 'emo-neutral' },
  sad: { emoji: '😔', label: '情绪低落', class: 'emo-sad' },
  angry: { emoji: '💢', label: '情绪波动', class: 'emo-angry' },
  surprised: { emoji: '😲', label: '感到惊讶', class: 'emo-surprised' },
  unknown: { emoji: '❓', label: '识别中', class: 'emo-unknown' }
};

function setText(id, obj) {
  document.getElementById(id).textContent =
    typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
}

function getEmoji(emotion) {
  const emo = emotionUI[emotion] || emotionUI.unknown;
  return emo.emoji;
}

function renderAttendanceResult(body) {
  const emo = emotionUI[body.emotion] || emotionUI.unknown;
  const confidence = Math.round(Number(body.emotion_confidence) || 0);
  const boundedConfidence = Math.max(0, Math.min(100, confidence));
  const blurOrFft = body.reason.match(/(?:blur|fft)=([0-9.]+)/)?.[1] || 'N/A';
  
  let livenessWarning = '';
  if (body.success && !body.liveness_passed) {
    livenessWarning = `<div class="liveness-warning">⚠️ 签到成功，但存在风险: ${body.reason}</div>`;
  }

  let registerHint = '';
  if (!body.success && body.reason.includes('Please register first')) {
    registerHint = `
      <div class="register-hint">
        <p>⚠️ 未识别到学生信息</p>
        <p>请前往 <a href="register.html" style="color: var(--ios-primary); text-decoration: underline;">学生注册页面</a> 完成注册</p>
      </div>
    `;
  }

  return `
    <div class="res-card ${body.success ? 'success' : 'fail'}">
      ${livenessWarning}
      ${registerHint}
      <div class="res-main">
        <span class="status-icon">${body.success ? '✅' : '❌'}</span>
        <div class="info">
          <p class="name">${body.student_name || '未知身份'}</p>
          <p class="id">${body.student_id || '-'}</p>
        </div>
      </div>
      <div class="emotion-bar-container">
        <div class="emotion-label">${emo.emoji} ${emo.label}</div>
        <div class="confidence-bar">
          <div class="confidence-fill" style="width: ${boundedConfidence}%"></div>
        </div>
        <small>可靠度: ${boundedConfidence}%</small>
      </div>
      <ul>
        <li>活体置信度: ${body.liveness_passed ? '高 ✅' : '低 ⚠️（风险预警）'}</li>
        <li>纹理/清晰度分值: ${blurOrFft}</li>
        <li>情绪模型: ${body.emotion_source || 'unknown'} / ${body.emotion || 'unknown'}</li>
      </ul>
      <p><b>原因:</b> ${body.reason || '-'}</p>
    </div>
  `;
}

function renderClassParticipationList(data) {
  const items = data.items || [];
  if (items.length === 0) return '<p class="hint">暂无签到记录</p>';

  const listHtml = items.map((item, index) => `
    <div class="stats-row">
      <span class="rank">${index + 1}</span>
      <span class="name">${item.student_name}</span>
      <span class="id">${item.student_id}</span>
      <span class="count"><b>${item.attendance_count || 0}</b> 次</span>
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

async function toBase64FromVideo() {
  const ctx = canvas.getContext('2d');
  
  if (!activeStream || video.readyState !== 4) {
    throw new Error('摄像头尚未准备好，请稍候');
  }
  
  if (video.videoWidth === 0 || video.videoHeight === 0) {
    throw new Error('无法获取视频画面尺寸');
  }
  
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  console.log("采样成功");
  return canvas.toDataURL('image/jpeg', 0.9);
}

document.getElementById('btnOpenCam').addEventListener('click', async () => {
  try {
    stopCamera();
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    activeStream = stream;
    video.srcObject = stream;
    
    capturedImageBase64 = null;
    
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.width = 640;
      canvas.height = 480;
    }
    
    updateCameraStatus();
    showHint('摄像头已开启，请对准摄像头');
  } catch (err) {
    showHint('摄像头调用失败: ' + err.message, 'error');
    updateCameraStatus();
  }
});

document.getElementById('btnCapture').addEventListener('click', async () => {
  try {
    if (!activeStream) {
      throw new Error('请先开启摄像头');
    }
    showHint('正在拍照，请保持不动 1 秒...');
    await new Promise((resolve) => setTimeout(resolve, 1000));
    capturedImageBase64 = await toBase64FromVideo();
    showHint('拍照成功，请点击"确认签到"按钮完成签到');
  } catch (err) {
    showHint('拍照失败: ' + err.message, 'error');
  }
});

document.getElementById('btnAttendance').addEventListener('click', async (e) => {
  const triggerBtn = e.target;
  const classNameInput = document.getElementById('className');
  const className = classNameInput?.value?.trim();
  const teacherNameInput = document.getElementById('teacherName');
  const teacherName = teacherNameInput?.value?.trim();
  
  try {
    if (!className) {
      throw new Error('请先填写课程名称');
    }
    if (!teacherName) {
      throw new Error('请先填写教师姓名');
    }
    if (!activeStream) {
      throw new Error('请先开启摄像头以获取实时画面');
    }
    
    let image_base64;
    if (capturedImageBase64) {
      image_base64 = capturedImageBase64;
      capturedImageBase64 = null;
    } else {
      image_base64 = await toBase64FromVideo();
    }
    const body = await fastFetch(`${apiBase}/api/attendance/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classroom_id: className, teacher_name: teacherName, image_base64 }),
      triggerBtn
    });
    attendanceText.innerHTML = renderAttendanceResult(body);

    if (body.success) {
      capturedImageBase64 = null;
      
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      canvas.width = 640;
      canvas.height = 480;
      
      setTimeout(() => {
        showHint('请下一位同学对准摄像头');
      }, 3000);
      
      updateClassCharts();
    }
  } catch (err) {
    showHint(err.message, 'error');
  }
});

async function updateClassCharts() {
  try {
    const className = document.getElementById('className').value.trim() || 'default';
    const body = await fastFetch(`${apiBase}/api/reports/class-detail?classroom_id=${encodeURIComponent(className)}`, { triggerBtn: null });
    
    document.getElementById('classParticipationList').innerHTML = renderClassParticipationList({ items: body.list });
    
    const items = body.emotions || [];
    const chartDom = document.getElementById('classEmotionChart');
    if (classEmotionChart) {
      classEmotionChart.dispose();
    }
    classEmotionChart = echarts.init(chartDom);
    
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
    
    classEmotionChart.setOption(option);
  } catch (err) {
    console.error('更新图表失败:', err.message);
  }
}

document.getElementById('btnDownloadDaily').addEventListener('click', async () => {
  const triggerBtn = document.getElementById('btnDownloadDaily');
  try {
    const body = await fastFetch(`${apiBase}/api/reports/export-attendance`, {
      method: 'POST',
      triggerBtn
    });
    alert(`考勤名册已生成在服务器: ${body.file_path}`);
  } catch (err) {
    alert(`导出失败: ${err.message}`);
  }
});
