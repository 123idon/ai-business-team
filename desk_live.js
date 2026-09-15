(() => {
  const params = new URLSearchParams(location.search);
  const room = document.getElementById('meeting')?.dataset.room;
  if (room) params.set('meeting', room);
  let updating = false;
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.dataset.sent) { event.preventDefault(); return; }
    form.dataset.sent = 'yes';
    setTimeout(() => form.querySelectorAll('button').forEach(b => { b.disabled = true; b.textContent = '접수 중…'; }), 0);
  });
  async function refresh() {
    if (updating || document.hidden) return;
    updating = true;
    try {
      const response = await fetch('/live?' + params.toString(), {cache:'no-store'});
      if (!response.ok) throw new Error('refresh');
      const data = await response.json();
      for (const [id, value] of Object.entries(data)) {
        const target = document.getElementById(id);
        if (target && !target.contains(document.activeElement) && target.innerHTML !== value) target.innerHTML = value;
      }
      const ready = document.querySelector('[data-meeting-ready]');
      document.querySelectorAll('.meeting-send').forEach(button => {
        if (!button.form.dataset.sent) {
          button.disabled = ready?.dataset.meetingReady === 'false';
          button.textContent = button.disabled ? '직원 발언을 기다리는 중' : '내 의견 보내고 답변 듣기';
        }
      });
      const status = document.getElementById('connection-state');
      if (status) status.textContent = '실제 작업 기록으로 자동 갱신 중 · ' + new Date().toLocaleTimeString('ko-KR');
    } catch (_) {
      const status = document.getElementById('connection-state');
      if (status) status.textContent = '사무실 연결을 다시 확인하고 있습니다. 작성 중인 내용은 유지됩니다.';
    } finally { updating = false; }
  }
  setInterval(refresh, 4000);
  refresh();
})();
