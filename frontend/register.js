const apiBase = 'http://127.0.0.1:8000';
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
let stream = null;

const studentIdInput = document.getElementById('studentId');
const studentNameInput = document.getElementById('studentName');
const studentMajorInput = document.getElementById('studentMajor');
const studentGenderInput = document.getElementById('studentGender');
const registerText = document.getElementById('registerText');

function showToast(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

async function openCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ 
      video: { 
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode: 'user'
      } 
    });
    video.srcObject = stream;
  } catch (err) {
    registerText.innerHTML = `<p class="error">无法访问摄像头: ${err.message}</p>`;
  }
}

function captureImage() {
  if (!stream || video.readyState !== 4) {
    registerText.innerHTML = '<p class="error">摄像头尚未准备好，请稍候</p>';
    return null;
  }
  
  if (video.videoWidth === 0 || video.videoHeight === 0) {
    registerText.innerHTML = '<p class="error">无法获取视频画面尺寸</p>';
    return null;
  }
  
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  console.log("采样成功");
  return canvas.toDataURL('image/jpeg', 0.9);
}

async function registerStudent() {
  const studentId = studentIdInput?.value?.trim();
  const studentName = studentNameInput?.value?.trim();
  const studentMajor = studentMajorInput?.value?.trim();
  const studentGender = studentGenderInput?.value;
  
  if (!studentId || !studentName || !studentMajor || !studentGender) {
    registerText.innerHTML = '<p class="error">请填写完整的学生信息</p>';
    return;
  }
  
  const imageData = captureImage();
  if (!imageData) {
    return;
  }
  
  registerText.innerHTML = '<p>正在注册中...</p>';
  
  try {
    const formData = new FormData();
    formData.append('student_id', studentId);
    formData.append('student_name', studentName);
    formData.append('major', studentMajor);
    formData.append('gender', studentGender);
    
    const base64Data = imageData.split(',')[1];
    const byteCharacters = atob(base64Data);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: 'image/jpeg' });
    formData.append('file', blob, 'photo.jpg');
    
    const res = await fetch(`${apiBase}/api/register`, {
      method: 'POST',
      headers: {
        'X-Role': 'teacher'
      },
      body: formData
    });
    
    const result = await res.json();
    
    if (!res.ok) {
      throw new Error(result.message || result.detail || '注册失败');
    }
    
    registerText.innerHTML = `
      <div class="res-card success">
        <p><strong>✅ 注册成功！</strong></p>
        <p>学号: ${studentId}</p>
        <p>姓名: ${studentName}</p>
        <p>照片已保存到: ${result.file_path}</p>
      </div>
    `;
    showToast('✅ 注册成功');
    
    studentIdInput.value = '';
    studentNameInput.value = '';
    studentMajorInput.value = '';
    studentGenderInput.value = '';
    
    capturedImageBase64 = null;
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.width = 640;
      canvas.height = 480;
    }
    
  } catch (err) {
    registerText.innerHTML = `<p class="error">注册失败: ${err.message}</p>`;
  }
}

document.getElementById('btnOpenCam').addEventListener('click', openCamera);
document.getElementById('btnCapture').addEventListener('click', captureImage);
document.getElementById('btnRegister').addEventListener('click', registerStudent);

document.addEventListener('beforeunload', () => {
  if (stream) {
    stream.getTracks().forEach(track => track.stop());
  }
});
