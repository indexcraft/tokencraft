const LOCAL_MODE = window.__TOKENCRAFT_LOCAL_MODE__;

// --- Info-icon popups (used by the Fast mode / AI vision '?' buttons) ---
function closeInfoPopup() {
  document.querySelectorAll('.info-popup').forEach((p) => p.remove());
}
document.querySelectorAll('.info-btn').forEach((btn) => {
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const alreadyOpen = btn._popupOpen;
    closeInfoPopup();
    if (alreadyOpen) { btn._popupOpen = false; return; }

    const tpl = document.getElementById(btn.dataset.info);
    if (!tpl) return;
    const popup = document.createElement('div');
    popup.className = 'info-popup';
    popup.appendChild(tpl.content.cloneNode(true));
    document.body.appendChild(popup);

    const rect = btn.getBoundingClientRect();
    const top = rect.bottom + window.scrollY + 6;
    let left = rect.left + window.scrollX;
    const maxLeft = window.innerWidth - popup.offsetWidth - 16;
    if (left > maxLeft) left = Math.max(16, maxLeft);
    popup.style.top = `${top}px`;
    popup.style.left = `${left}px`;

    btn._popupOpen = true;
    document.querySelectorAll('.info-btn').forEach((b) => { if (b !== btn) b._popupOpen = false; });
    document.addEventListener('click', closeInfoPopup, { once: true });
  });
});

const fileInput = document.getElementById('fileInput');
const dropzone = document.getElementById('dropzone');
const fileCountEl = document.getElementById('fileCount');
const ocrToggle = document.getElementById('ocrToggle');
const fastModeToggle = document.getElementById('fastModeToggle');
const apiKeyRow = document.getElementById('apiKeyRow');
const apiKeyInput = document.getElementById('apiKeyInput');
const convertBtn = document.getElementById('convertBtn');
const convertStatus = document.getElementById('convertStatus');

const statNative = document.getElementById('statNative');
const statConverted = document.getElementById('statConverted');
const statRatio = document.getElementById('statRatio');
const comparableNote = document.getElementById('comparableNote');
const chartEmptyNote = document.getElementById('chartEmptyNote');

const resultsBody = document.getElementById('resultsBody');
const downloadAllBtn = document.getElementById('downloadAllBtn');
const saveToFolderBtn = document.getElementById('saveToFolderBtn');
const openFolderBtn = document.getElementById('openFolderBtn');
const outputFolderInput = document.getElementById('outputFolder');
const browseBtn = document.getElementById('browseBtn');

let selectedFiles = [];
let lastResults = [];

// Remember output folder across visits (local mode only — this is just
// browser storage on the same machine, nothing sent anywhere).
if (LOCAL_MODE && outputFolderInput) {
  const saved = localStorage.getItem('tokencraft_output_folder');
  if (saved) outputFolderInput.value = saved;
  outputFolderInput.addEventListener('change', () => {
    localStorage.setItem('tokencraft_output_folder', outputFolderInput.value);
  });
}

dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });
dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('drag-over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('drag-over');
  if (e.dataTransfer.files.length) setFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', (e) => {
  if (e.target.files.length) setFiles(e.target.files);
});

function setFiles(fileList) {
  selectedFiles = Array.from(fileList);
  fileCountEl.textContent = `${selectedFiles.length} file(s) selected`;
}

ocrToggle.addEventListener('change', () => {
  apiKeyRow.hidden = !ocrToggle.checked;
});

function baseName(name) {
  return name.replace(/\.[^./]+$/, '');
}

function fmt(n) {
  return n === null || n === undefined ? '—' : n.toLocaleString();
}

function badgeForVerdict(verdict, pctSaved) {
  const map = {
    'Strong savings': 'badge-strong',
    'Moderate savings': 'badge-moderate',
    'No real difference': 'badge-none',
    'Conversion adds overhead': 'badge-overhead',
  };
  const cls = map[verdict] || 'badge-na';
  const label = (verdict === 'Conversion adds overhead' || verdict === 'No real difference')
    ? verdict
    : `${verdict} (${pctSaved}% fewer tokens)`;
  return `<span class="badge ${cls}">${label}</span>`;
}

const progressWrap = document.getElementById('progressWrap');
const progressBar = document.getElementById('progressBar');

function setProgress(pct, pulsing) {
  progressWrap.hidden = false;
  progressBar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  progressBar.classList.toggle('pulsing', !!pulsing);
}

function parseSSEBlock(block) {
  let event = 'message';
  let dataStr = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
  }
  if (!dataStr) return null;
  try { return { event, data: JSON.parse(dataStr) }; } catch { return null; }
}

convertBtn.addEventListener('click', async () => {
  if (!selectedFiles.length) {
    convertStatus.textContent = 'Select at least one file first.';
    return;
  }

  convertBtn.disabled = true;
  setProgress(2, true);
  convertStatus.textContent = `Starting — ${selectedFiles.length} file(s)…`;

  const form = new FormData();
  selectedFiles.forEach((f) => form.append('files', f));
  form.append('use_llm', ocrToggle.checked ? 'true' : 'false');
  form.append('api_key', apiKeyInput ? apiKeyInput.value : '');
  form.append('fast_mode', fastModeToggle.checked ? 'true' : 'false');

  const streamedResults = [];
  let finalSummary = null;

  try {
    const res = await fetch('/convert', { method: 'POST', body: form });
    if (!res.ok || !res.body) throw new Error(`Server returned ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const evt = parseSSEBlock(block);
        if (!evt) continue;

        if (evt.event === 'start') {
          setProgress(2, false);
        } else if (evt.event === 'file_start') {
          const { index, total, name } = evt.data;
          setProgress((index / total) * 100, false);
          convertStatus.textContent = `Converting ${index + 1} of ${total} — ${name}`;
        } else if (evt.event === 'file_done') {
          const { index, total, item } = evt.data;
          streamedResults[index] = item;
          setProgress(((index + 1) / total) * 100, false);
          convertStatus.textContent = `Converted ${index + 1} of ${total}`;
          // Live-update the table/stats as each file lands, instead of waiting for the end.
          renderResults(streamedResults.filter(Boolean), finalSummary || partialSummary(streamedResults));
        } else if (evt.event === 'complete') {
          finalSummary = evt.data.summary;
        }
      }
    }

    lastResults = streamedResults;
    renderResults(streamedResults, finalSummary);
    convertStatus.textContent = `Done — ${finalSummary.converted}/${finalSummary.total_files} converted.`;
    setProgress(100, false);
    setTimeout(() => { progressWrap.hidden = true; }, 1200);
  } catch (err) {
    convertStatus.textContent = `Error: ${err.message}`;
    progressWrap.hidden = true;
  } finally {
    convertBtn.disabled = false;
  }
});

function partialSummary(results) {
  // Lightweight running summary shown while the stream is still in
  // progress (before the server's authoritative 'complete' event arrives),
  // computed the same way as the backend so numbers don't visibly jump.
  const done = results.filter((r) => r && r.status === 'done');
  const comparable = done.filter((r) => r.native_tokens !== null);
  const summary = {
    total_files: results.length,
    converted: done.length,
    comparable_count: comparable.length,
    all_files_converted_tokens: done.reduce((s, r) => s + (r.converted_tokens || 0), 0),
    comparable_native_tokens: null,
    comparable_converted_tokens: null,
    overall_multiplier: null,
    overall_pct_saved: null,
  };
  if (comparable.length) {
    const nativeSum = comparable.reduce((s, r) => s + r.native_tokens, 0);
    const convSum = comparable.reduce((s, r) => s + r.converted_tokens, 0);
    summary.comparable_native_tokens = nativeSum;
    summary.comparable_converted_tokens = convSum;
    summary.overall_pct_saved = convSum ? Math.round(Math.max(0, (1 - convSum / nativeSum) * 1000)) / 10 : 0;
  }
  return summary;
}

let chartInstance = null;

function renderResults(results, summary) {
  // --- Stat cards: Native / Converted / Saved-% always come from the SAME
  // subset (files with a real native-upload baseline) so they can never
  // show mismatched numbers next to each other. ---
  if (summary.overall_pct_saved !== null && summary.overall_pct_saved !== undefined) {
    statNative.textContent = fmt(summary.comparable_native_tokens);
    statConverted.textContent = fmt(summary.comparable_converted_tokens);
    statRatio.textContent = `${summary.overall_pct_saved}%`;
    comparableNote.hidden = false;
    comparableNote.textContent = summary.comparable_count < summary.converted
      ? `Based on ${summary.comparable_count} of ${summary.converted} converted file(s) that have a native-upload baseline (PDFs / OCR'd images). ` +
        `All ${summary.converted} files together total ${fmt(summary.all_files_converted_tokens)} converted tokens.`
      : `Based on all ${summary.comparable_count} converted file(s).`;
  } else {
    statNative.textContent = 'N/A';
    statConverted.textContent = fmt(summary.all_files_converted_tokens);
    statRatio.textContent = 'N/A';
    comparableNote.hidden = false;
    comparableNote.textContent = "No PDFs or OCR'd images in this batch — token-savings comparisons only " +
      "apply to those formats (formats like .docx or .html are already read as text, so there's no " +
      "\"native upload\" baseline to compare against).";
  }

  // --- Chart: always an aggregate (Total Native vs Total Converted),
  // regardless of whether there's 1 file or 100 — a per-file bar chart
  // becomes unreadable past a handful of files, and the table below
  // already gives the per-file breakdown for anyone who wants it. ---
  try {
    const ctx = document.getElementById('tokenChart');
    if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    if (typeof Chart === 'undefined') {
      throw new Error('Chart.js did not load (likely blocked by a firewall/ad-blocker) — table below is unaffected.');
    }
    if (summary.comparable_count) {
      chartEmptyNote.hidden = true;
      chartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: [`Native upload (${summary.comparable_count} file${summary.comparable_count === 1 ? '' : 's'})`, 'Converted (Markdown)'],
          datasets: [{
            label: 'Tokens',
            data: [summary.comparable_native_tokens, summary.comparable_converted_tokens],
            backgroundColor: ['#ef4444', '#10b981'],
          }],
        },
        options: {
          responsive: true,
          indexAxis: 'y',
          plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true } },
        },
      });
    } else {
      chartEmptyNote.hidden = false;
      chartEmptyNote.textContent = "Nothing to chart yet — convert some files first.";
    }
  } catch (chartErr) {
    chartEmptyNote.hidden = false;
    chartEmptyNote.textContent = chartErr.message;
  }

  // --- Table: always runs, independent of whether the chart succeeded. ---
  if (!results.length) {
    resultsBody.innerHTML = '<tr class="empty-row"><td colspan="7">No files converted yet.</td></tr>';
  } else {
    resultsBody.innerHTML = results.map((r) => {
      if (r.status === 'error') {
        return `<tr>
          <td class="file-cell">${escapeHtml(r.name)}</td>
          <td class="mono">.${r.ext}</td>
          <td>—</td><td>—</td><td>—</td>
          <td class="status-failed">Failed: ${escapeHtml(r.error || '')}</td>
          <td></td>
        </tr>`;
      }
      let badge;
      if (r.native_tokens !== null) {
        const mult = r.native_tokens / r.converted_tokens;
        const pct = Math.max(0, Math.round((1 - r.converted_tokens / r.native_tokens) * 1000) / 10);
        let verdict = 'No real difference';
        if (mult >= 2) verdict = 'Strong savings';
        else if (mult >= 1.15) verdict = 'Moderate savings';
        else if (mult < 0.9) verdict = 'Conversion adds overhead';
        badge = badgeForVerdict(verdict, pct);
      } else {
        badge = '<span class="badge badge-na">No baseline for this format</span>';
      }
      return `<tr>
        <td class="file-cell">${escapeHtml(r.name)}${r.fast_mode_used ? ' <span class="badge badge-fast" title="Converted with Fast mode — plain text, no table structure">⚡ fast</span>' : ''}</td>
        <td class="mono">.${r.ext}</td>
        <td class="mono">${fmt(r.native_tokens)}</td>
        <td class="mono">${fmt(r.converted_tokens)}</td>
        <td>${badge}</td>
        <td class="status-success">Success</td>
        <td><button class="link-btn" onclick="downloadOne('${escapeHtml(r.name)}')">Download .md</button></td>
      </tr>`;
    }).join('');
  }

  const anyDone = results.some((r) => r.status === 'done');
  downloadAllBtn.disabled = !anyDone;
  if (saveToFolderBtn) saveToFolderBtn.disabled = !anyDone;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

window.downloadOne = function (name) {
  const item = lastResults.find((r) => r.name === name);
  if (!item) return;
  const blob = new Blob([item.content], { type: 'text/markdown' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = baseName(item.name) + '.md';
  a.click();
  URL.revokeObjectURL(a.href);
};

downloadAllBtn.addEventListener('click', async () => {
  const done = lastResults.filter((r) => r.status === 'done');
  if (!done.length) return;
  if (typeof JSZip === 'undefined') {
    convertStatus.textContent = 'Zip library failed to load (likely blocked by a firewall) — use "Download .md" per file instead.';
    return;
  }
  const zip = new JSZip();
  done.forEach((r) => zip.file(baseName(r.name) + '.md', r.content));
  const blob = await zip.generateAsync({ type: 'blob' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'tokencraft-export.zip';
  a.click();
  URL.revokeObjectURL(a.href);
});

if (LOCAL_MODE) {
  browseBtn.addEventListener('click', async () => {
    const res = await fetch('/pick-folder', { method: 'POST' });
    const data = await res.json();
    if (data.folder) {
      outputFolderInput.value = data.folder;
      localStorage.setItem('tokencraft_output_folder', data.folder);
    }
  });

  saveToFolderBtn.addEventListener('click', async () => {
    const done = lastResults.filter((r) => r.status === 'done');
    if (!done.length) return;
    const res = await fetch('/save-to-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        folder: outputFolderInput.value,
        files: done.map((r) => ({ name: r.name, content: r.content })),
      }),
    });
    const data = await res.json();
    convertStatus.textContent = res.ok
      ? `Saved ${data.count} file(s) to ${data.folder}`
      : `Error: ${data.detail || 'save failed'}`;
  });

  openFolderBtn.addEventListener('click', async () => {
    const res = await fetch('/open-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: outputFolderInput.value }),
    });
    if (!res.ok) {
      const data = await res.json();
      convertStatus.textContent = `Error: ${data.detail || 'could not open folder'}`;
    }
  });
}
