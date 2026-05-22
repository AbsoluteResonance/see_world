/* App Main — Wire everything together */

let currentAnalysisFileId = null;

function openAnalysis(fileId, url, type) {
  currentAnalysisFileId = fileId;
  const section = document.getElementById('analysisSection');
  const preview = document.getElementById('analysisPreview');
  const result = document.getElementById('analysisResult');
  const error = document.getElementById('analysisError');

  section.hidden = false;
  result.hidden = true;
  error.hidden = true;

  if (type === 'video') {
    preview.innerHTML = `<video src="${url}" controls muted style="max-width:100%;max-height:300px"></video>`;
  } else {
    preview.innerHTML = `<img src="${url}" alt="preview" style="max-width:100%;max-height:300px" />`;
  }

  // Scroll to analysis section
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function runAnalysis() {
  if (!currentAnalysisFileId) return;
  const prompt = document.getElementById('analysisPrompt').value.trim() || '请详细描述这张图片的内容';
  const resultDiv = document.getElementById('analysisResult');
  const errorDiv = document.getElementById('analysisError');
  const contentDiv = document.getElementById('analysisContent');
  const metaDiv = document.getElementById('analysisMeta');
  const btn = document.getElementById('analyzeBtn');

  resultDiv.hidden = true;
  errorDiv.hidden = true;
  btn.disabled = true;
  btn.textContent = '分析中…';
  contentDiv.textContent = '';

  try {
    const resp = await fetch(`/api/analyze/${currentAnalysisFileId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });
    const body = await resp.json();

    if (body.code !== 0) {
      throw new Error(body.message || 'Analysis failed');
    }

    const data = body.data;
    if (data.error) {
      errorDiv.textContent = data.content || '分析失败';
      errorDiv.hidden = false;
      return;
    }

    contentDiv.textContent = data.content || '无分析结果';
    if (data.tokens || data.model) {
      metaDiv.textContent = [
        data.model ? `模型: ${data.model}` : '',
        data.tokens?.input ? `输入: ${data.tokens.input} tokens` : '',
        data.tokens?.output ? `输出: ${data.tokens.output} tokens` : '',
      ].filter(Boolean).join(' | ');
    }
    resultDiv.hidden = false;
  } catch (err) {
    errorDiv.textContent = err.message || '网络错误';
    errorDiv.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = '分析';
  }
}

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initUpload();
  refreshGallery();

  // Refresh button
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) refreshBtn.addEventListener('click', refreshGallery);

  // Analysis button
  const analyzeBtn = document.getElementById('analyzeBtn');
  if (analyzeBtn) analyzeBtn.addEventListener('click', runAnalysis);

  // Close analysis
  const closeBtn = document.getElementById('closeAnalysis');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      document.getElementById('analysisSection').hidden = true;
      currentAnalysisFileId = null;
    });
  }

  // Keyboard shortcut: Ctrl+Enter to run analysis
  const promptInput = document.getElementById('analysisPrompt');
  if (promptInput) {
    promptInput.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'Enter') runAnalysis();
    });
  }
});
